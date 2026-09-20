"""高德地图原生高性能进程内适配器 (Amap Native In-Process Adapter)

设计理念：
1. 零子进程冷启动：彻底切断 `uvx amap-mcp-server` 进程风暴，零外部解释器派生；
2. 原生连接池复用：基于单例 `httpx.Client(trust_env=False)` 维护长连接池与 Keep-Alive，
   规避 macOS 代理环境变量导致的 `socksio` 缺失错误；
3. 细粒度 Redis / 内存双层指纹缓存：毫秒级响应，极大减轻高德 API QPS 压力；
4. 100% 协议契约兼容：对外保留与 MCPTool 相同的接口格式 (`run(parameters)`)，
   返回 `"工具 '<tool_name>' 执行结果:\n{...}"`，上层调用完全无感。
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional
import httpx

from .cache_service import compute_fingerprint, get_cache_manager

logger = logging.getLogger(__name__)

AMAP_BASE_URL = "https://restapi.amap.com"


class AmapNativeClient:
    """高德地图原生 REST API 客户端（单例连接池）"""

    def __init__(self, api_key: str):
        if not api_key:
            raise ValueError("高德地图 API Key 不能为空")
        self.api_key = api_key
        # 禁用系统代理环境读取 (trust_env=False)，彻底规避 socksio 缺失导致的异常
        self._client = httpx.Client(
            base_url=AMAP_BASE_URL,
            trust_env=False,
            timeout=httpx.Timeout(10.0, connect=5.0),
            limits=httpx.Limits(max_keepalive_connections=20, max_connections=50),
        )
        self._cache = get_cache_manager()

    def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        """执行底层 HTTP GET 请求"""
        resp = self._client.get(path, params=params)
        resp.raise_for_status()
        return resp.json()

    # ────────────────────────────────────────────────────────
    # 工具实现集
    # ────────────────────────────────────────────────────────

    def maps_geo(self, address: str, city: Optional[str] = None) -> Dict[str, Any]:
        """地理编码：根据地址获取坐标"""
        fp = compute_fingerprint({"address": address, "city": city or ""})
        cached = self._cache.get("maps_geo", fp)
        if cached is not None:
            return cached

        params = {"key": self.api_key, "address": address}
        if city:
            params["city"] = city

        data = self._get("/v3/geocode/geo", params=params)
        if data.get("status") != "1":
            return {"error": f"Geocoding failed: {data.get('info') or data.get('infocode')}"}

        geocodes = data.get("geocodes", [])
        results = []
        for geo in geocodes:
            results.append({
                "country": geo.get("country"),
                "province": geo.get("province"),
                "city": geo.get("city"),
                "citycode": geo.get("citycode"),
                "district": geo.get("district"),
                "street": geo.get("street"),
                "number": geo.get("number"),
                "adcode": geo.get("adcode"),
                "location": geo.get("location"),
                "level": geo.get("level"),
            })
        res = {"return": results}
        self._cache.set("maps_geo", fp, res, ttl=86400 * 7)
        return res

    def maps_regeocode(self, location: str) -> Dict[str, Any]:
        """逆地理编码：经纬度转地址"""
        fp = compute_fingerprint({"location": location})
        cached = self._cache.get("maps_regeocode", fp)
        if cached is not None:
            return cached

        params = {"key": self.api_key, "location": location}
        data = self._get("/v3/geocode/regeo", params=params)
        if data.get("status") != "1":
            return {"error": f"Regeocoding failed: {data.get('info') or data.get('infocode')}"}

        regeocode = data.get("regeocode", {})
        res = {
            "formatted_address": regeocode.get("formatted_address"),
            "addressComponent": regeocode.get("addressComponent"),
        }
        self._cache.set("maps_regeocode", fp, res, ttl=86400 * 7)
        return res

    def maps_ip_location(self, ip: str) -> Dict[str, Any]:
        """IP 定位"""
        params = {"key": self.api_key, "ip": ip}
        data = self._get("/v3/ip", params=params)
        if data.get("status") != "1":
            return {"error": f"IP Location failed: {data.get('info') or data.get('infocode')}"}
        return {
            "province": data.get("province"),
            "city": data.get("city"),
            "adcode": data.get("adcode"),
            "rectangle": data.get("rectangle"),
        }

    def maps_weather(self, city: str) -> Dict[str, Any]:
        """城市天气预报查询"""
        fp = compute_fingerprint({"city": city})
        cached = self._cache.get("maps_weather", fp)
        if cached is not None:
            return cached

        params = {"key": self.api_key, "city": city, "extensions": "all"}
        data = self._get("/v3/weather/weatherInfo", params=params)
        if data.get("status") != "1":
            return {"error": f"Get weather failed: {data.get('info') or data.get('infocode')}"}

        forecasts = data.get("forecasts", [])
        if not forecasts:
            return {"error": "No forecast data available"}

        res = {
            "city": forecasts[0].get("city", city),
            "forecasts": forecasts[0].get("casts", []),
        }
        self._cache.set("maps_weather", fp, res, ttl=1800)
        return res

    def maps_distance(self, origins: str, destination: str, type: str = "1") -> Dict[str, Any]:
        """两点间距离测量 (支持驾车、步行、球面距离)"""
        fp = compute_fingerprint({"origins": origins, "destination": destination, "type": str(type)})
        cached = self._cache.get("maps_distance", fp)
        if cached is not None:
            return cached

        params = {"key": self.api_key, "origins": origins, "destination": destination, "type": str(type)}
        data = self._get("/v3/distance", params=params)
        if data.get("status") != "1":
            return {"error": f"Direction Distance failed: {data.get('info') or data.get('infocode')}"}

        results = []
        for result in data.get("results", []):
            results.append({
                "origin_id": result.get("origin_id"),
                "dest_id": result.get("dest_id"),
                "distance": result.get("distance"),
                "duration": result.get("duration"),
            })
        res = {"results": results}
        self._cache.set("maps_distance", fp, res, ttl=86400 * 7)
        return res

    def maps_text_search(self, keywords: str, city: str = "", citylimit: str = "false") -> Dict[str, Any]:
        """POI 关键词搜索 (返回丰富字段，含原生经纬度与评分)"""
        fp = compute_fingerprint({"keywords": keywords, "city": city, "citylimit": citylimit})
        cached = self._cache.get("maps_text_search", fp)
        if cached is not None:
            return cached

        params = {
            "key": self.api_key,
            "keywords": keywords,
            "city": city,
            "citylimit": citylimit,
            "offset": "20",
            "page": "1",
            "extensions": "all",
        }
        data = self._get("/v3/place/text", params=params)
        if data.get("status") != "1":
            return {"error": f"Text Search failed: {data.get('info') or data.get('infocode')}"}

        suggestion_cities = []
        if data.get("suggestion", {}).get("cities"):
            for c in data["suggestion"]["cities"]:
                suggestion_cities.append({"name": c.get("name")})

        pois = []
        for poi in data.get("pois", []):
            p_dict = {
                "id": poi.get("id"),
                "name": poi.get("name"),
                "address": poi.get("address"),
                "typecode": poi.get("typecode"),
                "type": poi.get("type"),
                "location": poi.get("location"),
                "adname": poi.get("adname"),
                "cityname": poi.get("cityname"),
                "tel": poi.get("tel"),
            }
            if poi.get("biz_ext"):
                p_dict["biz_ext"] = poi["biz_ext"]
                if isinstance(poi["biz_ext"], dict) and poi["biz_ext"].get("rating"):
                    p_dict["rating"] = poi["biz_ext"]["rating"]
                if isinstance(poi["biz_ext"], dict) and poi["biz_ext"].get("cost"):
                    p_dict["cost"] = poi["biz_ext"]["cost"]
            if poi.get("rating"):
                p_dict["rating"] = poi["rating"]
            pois.append(p_dict)

        res = {
            "suggestion": {
                "keywords": data.get("suggestion", {}).get("keywords"),
                "cities": suggestion_cities,
            },
            "pois": pois,
        }
        self._cache.set("maps_text_search", fp, res, ttl=86400)
        return res

    def maps_around_search(self, location: str, radius: str = "1000", keywords: str = "") -> Dict[str, Any]:
        """周边 POI 搜索 (美食/酒店/生活设施)"""
        fp = compute_fingerprint({"location": location, "radius": str(radius), "keywords": keywords})
        cached = self._cache.get("maps_around_search", fp)
        if cached is not None:
            return cached

        params = {
            "key": self.api_key,
            "location": location,
            "radius": str(radius),
            "keywords": keywords,
            "offset": "20",
            "page": "1",
            "extensions": "all",
        }
        data = self._get("/v3/place/around", params=params)
        if data.get("status") != "1":
            return {"error": f"Around Search failed: {data.get('info') or data.get('infocode')}"}

        pois = []
        for poi in data.get("pois", []):
            p_dict = {
                "id": poi.get("id"),
                "name": poi.get("name"),
                "address": poi.get("address"),
                "typecode": poi.get("typecode"),
                "type": poi.get("type"),
                "location": poi.get("location"),
                "adname": poi.get("adname"),
                "cityname": poi.get("cityname"),
                "tel": poi.get("tel"),
            }
            if poi.get("biz_ext"):
                p_dict["biz_ext"] = poi["biz_ext"]
                if isinstance(poi["biz_ext"], dict) and poi["biz_ext"].get("rating"):
                    p_dict["rating"] = poi["biz_ext"]["rating"]
                if isinstance(poi["biz_ext"], dict) and poi["biz_ext"].get("cost"):
                    p_dict["cost"] = poi["biz_ext"]["cost"]
            if poi.get("rating"):
                p_dict["rating"] = poi["rating"]
            pois.append(p_dict)

        res = {"pois": pois}
        self._cache.set("maps_around_search", fp, res, ttl=86400)
        return res

    def maps_search_detail(self, id: str) -> Dict[str, Any]:
        """POI 详情查询 (营业时间、评级、门票、电话等)"""
        fp = compute_fingerprint({"id": id})
        cached = self._cache.get("maps_search_detail", fp)
        if cached is not None:
            return cached

        params = {"key": self.api_key, "id": id}
        data = self._get("/v3/place/detail", params=params)
        if data.get("status") != "1":
            return {"error": f"Get poi detail failed: {data.get('info') or data.get('infocode')}"}

        if not data.get("pois"):
            return {"error": "No POI found"}

        poi = data["pois"][0]
        result = {
            "id": poi.get("id"),
            "name": poi.get("name"),
            "location": poi.get("location"),
            "address": poi.get("address"),
            "business_area": poi.get("business_area"),
            "city": poi.get("cityname"),
            "type": poi.get("type"),
            "alias": poi.get("alias"),
            "open_time": poi.get("open_time") or poi.get("opentime2"),
            "opentime2": poi.get("opentime2"),
            "level": poi.get("level"),
            "cost": poi.get("cost"),
            "rating": poi.get("rating"),
        }
        if poi.get("biz_ext"):
            result.update(poi["biz_ext"])

        self._cache.set("maps_search_detail", fp, result, ttl=86400 * 7)
        return result

    def maps_direction_driving_by_coordinates(self, origin: str, destination: str) -> Dict[str, Any]:
        """坐标驾车路径规划"""
        params = {"key": self.api_key, "origin": origin, "destination": destination}
        data = self._get("/v3/direction/driving", params=params)
        if data.get("status") != "1":
            return {"error": f"Driving route failed: {data.get('info') or data.get('infocode')}"}
        return data.get("route", {})

    def maps_direction_walking_by_coordinates(self, origin: str, destination: str) -> Dict[str, Any]:
        """坐标步行路径规划"""
        params = {"key": self.api_key, "origin": origin, "destination": destination}
        data = self._get("/v3/direction/walking", params=params)
        if data.get("status") != "1":
            return {"error": f"Walking route failed: {data.get('info') or data.get('infocode')}"}
        return data.get("route", {})

    def maps_bicycling_by_coordinates(self, origin_coordinates: str, destination_coordinates: str) -> Dict[str, Any]:
        """坐标骑行路径规划"""
        params = {"key": self.api_key, "origin": origin_coordinates, "destination": destination_coordinates}
        data = self._get("/v4/direction/bicycling", params=params)
        if data.get("errcode") != 0 and data.get("status") != "1":
            return {"error": f"Bicycling route failed: {data.get('errmsg') or data.get('info')}"}
        return data.get("data", {})

    def maps_direction_driving_by_address(
        self, origin_address: str, destination_address: str,
        origin_city: Optional[str] = None, destination_city: Optional[str] = None
    ) -> Dict[str, Any]:
        """地址驾车路径规划"""
        orig_geo = self.maps_geo(origin_address, origin_city)
        dest_geo = self.maps_geo(destination_address, destination_city)
        if not orig_geo.get("return") or not dest_geo.get("return"):
            return {"error": "Failed to geocode addresses"}
        orig_loc = orig_geo["return"][0]["location"]
        dest_loc = dest_geo["return"][0]["location"]
        return self.maps_direction_driving_by_coordinates(orig_loc, dest_loc)

    def maps_direction_walking_by_address(
        self, origin_address: str, destination_address: str,
        origin_city: Optional[str] = None, destination_city: Optional[str] = None
    ) -> Dict[str, Any]:
        """地址步行路径规划"""
        orig_geo = self.maps_geo(origin_address, origin_city)
        dest_geo = self.maps_geo(destination_address, destination_city)
        if not orig_geo.get("return") or not dest_geo.get("return"):
            return {"error": "Failed to geocode addresses"}
        orig_loc = orig_geo["return"][0]["location"]
        dest_loc = dest_geo["return"][0]["location"]
        return self.maps_direction_walking_by_coordinates(orig_loc, dest_loc)

    def maps_bicycling_by_address(
        self, origin_address: str, destination_address: str,
        origin_city: Optional[str] = None, destination_city: Optional[str] = None
    ) -> Dict[str, Any]:
        """地址骑行路径规划"""
        orig_geo = self.maps_geo(origin_address, origin_city)
        dest_geo = self.maps_geo(destination_address, destination_city)
        if not orig_geo.get("return") or not dest_geo.get("return"):
            return {"error": "Failed to geocode addresses"}
        orig_loc = orig_geo["return"][0]["location"]
        dest_loc = dest_geo["return"][0]["location"]
        return self.maps_bicycling_by_coordinates(orig_loc, dest_loc)

    def maps_direction_transit_integrated_by_coordinates(
        self, origin: str, destination: str, city: str, cityd: str
    ) -> Dict[str, Any]:
        """坐标公交综合路径规划"""
        params = {"key": self.api_key, "origin": origin, "destination": destination, "city": city, "cityd": cityd}
        data = self._get("/v3/direction/transit/integrated", params=params)
        if data.get("status") != "1":
            return {"error": f"Transit route failed: {data.get('info') or data.get('infocode')}"}
        return data.get("route", {})

    def maps_direction_transit_integrated_by_address(
        self, origin_address: str, destination_address: str, origin_city: str, destination_city: str
    ) -> Dict[str, Any]:
        """地址公交综合路径规划"""
        orig_geo = self.maps_geo(origin_address, origin_city)
        dest_geo = self.maps_geo(destination_address, destination_city)
        if not orig_geo.get("return") or not dest_geo.get("return"):
            return {"error": "Failed to geocode addresses"}
        orig_loc = orig_geo["return"][0]["location"]
        dest_loc = dest_geo["return"][0]["location"]
        return self.maps_direction_transit_integrated_by_coordinates(orig_loc, dest_loc, origin_city, destination_city)


# ────────────────────────────────────────────────────────
# 工具契约元数据（与 amap-mcp-server 完全一致）
# ────────────────────────────────────────────────────────

AVAILABLE_TOOLS_META: list[dict[str, str]] = [
    {"name": "maps_geo", "description": "地理编码：根据给定的结构化地址或者标准名称，获取对应的经纬度坐标"},
    {"name": "maps_regeocode", "description": "逆地理编码：将一个高德经纬度坐标转换为行政区划及详细地址信息"},
    {"name": "maps_ip_location", "description": "IP 定位：根据用户输入的 IP 地址，定位 IP 的所在位置"},
    {"name": "maps_weather", "description": "天气查询：根据城市名称或者标准 adcode 查询指定城市的天气预报"},
    {"name": "maps_distance", "description": "距离测量：测量两个经纬度坐标之间的距离，支持驾车、步行以及球面距离测量"},
    {"name": "maps_text_search", "description": "关键词搜索：根据用户输入的关键字进行 POI 搜索，并返回相关的信息"},
    {"name": "maps_around_search", "description": "周边搜索：根据用户传入关键词以及坐标 location，搜索出 radius 半径范围的 POI"},
    {"name": "maps_search_detail", "description": "POI 详情查询：查询关键词搜或者周边搜获取到的 POI ID 的详细信息"},
    {"name": "maps_direction_driving_by_coordinates", "description": "驾车路径规划：根据起终点坐标规划驾车路线"},
    {"name": "maps_direction_walking_by_coordinates", "description": "步行路径规划：根据起终点坐标规划步行路线"},
    {"name": "maps_bicycling_by_coordinates", "description": "骑行路径规划：根据起终点坐标规划骑行路线"},
    {"name": "maps_direction_driving_by_address", "description": "地址驾车规划：根据起终点地址规划驾车路线"},
    {"name": "maps_direction_walking_by_address", "description": "地址步行规划：根据起终点地址规划步行路线"},
    {"name": "maps_bicycling_by_address", "description": "地址骑行规划：根据起终点地址规划骑行路线"},
    {"name": "maps_direction_transit_integrated_by_coordinates", "description": "坐标公交规划：根据起终点坐标规划公共交通路线"},
    {"name": "maps_direction_transit_integrated_by_address", "description": "地址公交规划：根据起终点地址规划公共交通路线"},
]


class AmapNativeTool:
    """高德地图原生工具类（与 MCPTool 100% 鸭子类型兼容）"""

    def __init__(self, api_key: str):
        self.name = "amap"
        self.description = "高德地图原生高性能服务，支持 POI 搜索、路线规划、天气查询"
        self.client = AmapNativeClient(api_key)
        self._available_tools = AVAILABLE_TOOLS_META

    def run(self, parameters: Dict[str, Any]) -> str:
        """执行工具操作，输出完全兼容 MCPTool 的执行结果格式"""
        action = parameters.get("action", "").lower()
        if not action and "tool_name" in parameters:
            action = "call_tool"

        if action == "list_tools":
            result = f"找到 {len(self._available_tools)} 个工具:\n"
            for tool in self._available_tools:
                result += f"- {tool['name']}: {tool['description']}\n"
            return result

        if action == "call_tool":
            tool_name = parameters.get("tool_name", "")
            arguments = parameters.get("arguments", {})
            if not tool_name:
                return "错误：必须指定 tool_name 参数"

            handler = getattr(self.client, tool_name, None)
            if handler is None or not callable(handler):
                return f"错误：不支持的工具 '{tool_name}'"

            try:
                raw_res = handler(**arguments)
                return f"工具 '{tool_name}' 执行结果:\n{json.dumps(raw_res, ensure_ascii=False)}"
            except Exception as e:
                logger.error("AmapNativeClient 工具 %s 调用异常: %s", tool_name, e, exc_info=True)
                return f"工具 '{tool_name}' 执行失败: {str(e)}"

        return f"错误：不支持的操作 '{action}'"
