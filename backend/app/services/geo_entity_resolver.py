"""分级地理实体解析器 (Generalized Hierarchical Geographic Entity Resolver)

核心架构职责:
1. 彻底摒弃静态城市/大区字典枚举，采用“Redis 缓存 -> 高德行政地理编码 -> 大模型零样本空间理解”三级动态流水线；
2. 自动判定目的地形态（PROVINCE 省份 / TOURISM_REGION 线路大区 / SCENIC_AREA 名胜景区 / CITY 行政城市）；
3. 动态提取规范名称 (canonical_name)、中心经纬度 (center_coord)、集散枢纽城市 (gateway_city) 与 4-8 个真实代表性名胜 (core_pois)；
4. 解析结果写入 Redis 缓存 (TTL=30天)，全系统多租户共享亚秒级极速响应，零硬编码。
"""
from __future__ import annotations

import json
import logging
import os
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any

from .cache_service import get_cache_manager, compute_fingerprint

logger = logging.getLogger(__name__)


class DestinationType(str, Enum):
    """目的地层级与空间形态分类"""
    CITY = "city"                       # 标准行政城市 (如 北京、杭州、成都)
    PROVINCE = "province"               # 宏观省级行政区 (如 四川、云南、新疆)
    TOURISM_REGION = "tourism_region"   # 跨地市风光/自驾大区 (如 川西、陕北、南疆、皖南)
    SCENIC_AREA = "scenic_area"         # 知名旅游名胜/县级市 (如 峨眉山、九寨沟、都江堰、庐山)


@dataclass
class ResolvedDestination:
    """解析后的结构化地理实体"""
    raw_name: str
    canonical_name: str
    display_name: str
    dest_type: DestinationType
    gateway_city: str
    center_coord: tuple[float, float]   # (lng, lat)
    core_pois: list[str] = field(default_factory=list)
    search_keywords: list[str] = field(default_factory=list)
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["dest_type"] = self.dest_type.value
        d["center_coord"] = list(self.center_coord)
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ResolvedDestination:
        c = dict(data)
        if "dest_type" in c and isinstance(c["dest_type"], str):
            c["dest_type"] = DestinationType(c["dest_type"])
        if "center_coord" in c and isinstance(c["center_coord"], list):
            c["center_coord"] = (float(c["center_coord"][0]), float(c["center_coord"][1]))
        return cls(**c)


def _amap_geocode_lookup(name: str) -> dict[str, Any] | None:
    """通道 A: 调用高德官方 Geocoding API 进行确定性行政层级判定 (优先命中 Redis 指纹缓存)"""
    cache_mgr = get_cache_manager()
    fp = compute_fingerprint({"address": name, "city": ""})
    cached = cache_mgr.get("maps_geo", fp)
    if cached and isinstance(cached, dict) and cached.get("return"):
        return cached["return"][0]

    api_key = os.getenv("AMAP_API_KEY")
    if not api_key:
        return None
    url = f"https://restapi.amap.com/v3/geocode/geo?address={urllib.parse.quote(name)}&key={api_key}"
    req = urllib.request.Request(url)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(req, timeout=3) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            geocodes = data.get("geocodes", [])
            if geocodes:
                try:
                    cache_mgr.set("maps_geo", fp, {"return": geocodes}, ttl=86400 * 90)
                except Exception:
                    pass
                return geocodes[0]
    except Exception as e:
        logger.debug("高德 Geocoding 解析 [%s] 降级: %s", name, e)
    return None


def _llm_spatial_lookup(name: str) -> dict[str, Any] | None:
    """通道 B: 大模型零样本空间与大区解析（针对川西、陕北、南疆等无行政代码的大区）"""
    try:
        from .llm_service import get_llm
        llm = get_llm()
        prompt = (
            f"请以纯 JSON 格式解析中国旅游目的地【{name}】：\n"
            "{\n"
            "  \"canonical_name\": \"规范标准名称 (如 峨眉山、川西高原、陕北、南疆、西双版纳)\",\n"
            "  \"dest_type\": \"province|region|city|scenic\",\n"
            "  \"gateway_city\": \"主要集散枢纽城市 (地级市名称，如 成都市、延安市、喀什市、乐山市)\",\n"
            "  \"center_lng_lat\": [经度浮点数, 纬度浮点数],\n"
            "  \"core_scenic_pois\": [\"真实知名景点1\", \"真实知名景点2\", \"真实知名景点3\", \"真实知名景点4\"]\n"
            "}\n"
            "严格只输出合法 JSON，严禁任何 markdown 围栏或额外文字。"
        )
        resp = llm.invoke([{"role": "user", "content": prompt}])
        text = str(resp).strip()
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()
        parsed = json.loads(text)
        if isinstance(parsed, dict) and "canonical_name" in parsed:
            return parsed
    except Exception as e:
        logger.info("LLM 动态空间理解跳过或失败 (%s)", e)
    return None


class GeoEntityResolver:
    """通用分级地理实体解析器"""

    @classmethod
    def resolve(cls, destination: str) -> ResolvedDestination:
        """输入自然语言地名，通用动态解析其真实空间与行政属性（零硬编码）"""
        raw = destination or ""
        clean_name = raw.replace("市", "").replace("省", "").replace("自治区", "").strip()
        if not clean_name:
            clean_name = "北京"

        cache_mgr = get_cache_manager()
        cache_key = f"geo_entity:{clean_name}"

        # 1. 查阅 Redis 缓存 (30天 TTL)
        cached = cache_mgr.get("geo_resolve", cache_key)
        if cached and isinstance(cached, dict):
            try:
                return ResolvedDestination.from_dict(cached)
            except Exception:
                pass

        resolved: ResolvedDestination | None = None

        # 2. 通道 A: 确定性高德行政编码判定
        geo_info = _amap_geocode_lookup(clean_name)
        if geo_info:
            lvl = geo_info.get("level", "")
            loc_str = geo_info.get("location", "")
            province = geo_info.get("province", "") or ""
            city_name = geo_info.get("city", "") or ""
            district_name = geo_info.get("district", "") or ""

            # 解析经纬度
            coord = (116.407, 39.904)
            if loc_str and "," in loc_str:
                parts = loc_str.split(",")
                try:
                    coord = (float(parts[0]), float(parts[1]))
                except ValueError:
                    pass

            # 若属于标准行政级别：省、市、区县、著名风景名胜
            if lvl == "省":
                # 省级行政区：如 四川省，调用空间智能获取省会枢纽与全省核心名胜
                llm_res = _llm_spatial_lookup(clean_name)
                gateway = (llm_res.get("gateway_city") if llm_res else None) or district_name or city_name or f"{clean_name}省会"
                core_pois = (llm_res.get("core_scenic_pois") if llm_res else None) or []
                resolved = ResolvedDestination(
                    raw_name=raw,
                    canonical_name=f"{clean_name}省" if not clean_name.endswith("省") else clean_name,
                    display_name=f"{clean_name}省 (以{gateway}为门户枢纽)",
                    dest_type=DestinationType.PROVINCE,
                    gateway_city=gateway,
                    center_coord=coord,
                    core_pois=core_pois,
                    search_keywords=[clean_name, province, gateway] + core_pois[:4],
                    description=f"{clean_name}省级行政区，以{gateway}为枢纽辐射全省核心名胜。",
                )
            elif lvl in ("市", "区县") and lvl != "村庄":
                dest_type = DestinationType.CITY if lvl == "市" else DestinationType.SCENIC_AREA
                canonical = district_name if lvl == "区县" and district_name else (city_name or clean_name)
                canonical_clean = canonical.replace("市", "").replace("区", "").replace("县", "")
                resolved = ResolvedDestination(
                    raw_name=raw,
                    canonical_name=canonical_clean,
                    display_name=f"{canonical} ({province})",
                    dest_type=dest_type,
                    gateway_city=city_name or district_name or clean_name,
                    center_coord=coord,
                    core_pois=[],
                    search_keywords=[clean_name, canonical_clean],
                    description=f"隶属{province}的标准行政空间。",
                )

        # 3. 通道 B: 若高德未给出明确级别，或识别为村庄等微弱地名（典型如“川西”、“陕北”、“南疆”），触发 LLM 零样本空间认知
        if resolved is None:
            llm_res = _llm_spatial_lookup(clean_name)
            if llm_res:
                raw_type = str(llm_res.get("dest_type", "region")).lower()
                dest_type = {
                    "province": DestinationType.PROVINCE,
                    "region": DestinationType.TOURISM_REGION,
                    "scenic": DestinationType.SCENIC_AREA,
                    "city": DestinationType.CITY,
                }.get(raw_type, DestinationType.TOURISM_REGION)

                c_list = llm_res.get("center_lng_lat") or [104.0, 30.0]
                coord = (float(c_list[0]), float(c_list[1]))
                canonical = str(llm_res.get("canonical_name", clean_name)).strip()
                gateway = str(llm_res.get("gateway_city", clean_name)).strip()
                core_pois = [str(p).strip() for p in llm_res.get("core_scenic_pois", []) if str(p).strip()]

                resolved = ResolvedDestination(
                    raw_name=raw,
                    canonical_name=canonical,
                    display_name=f"{canonical} (枢纽: {gateway})",
                    dest_type=dest_type,
                    gateway_city=gateway,
                    center_coord=coord,
                    core_pois=core_pois,
                    search_keywords=[canonical, gateway] + core_pois[:3],
                    description=f"动态零样本空间理解：{canonical}，以{gateway}为集散中心。",
                )

        # 4. 通用兜底（离线无网且高德未命中）
        if resolved is None:
            resolved = ResolvedDestination(
                raw_name=raw,
                canonical_name=clean_name,
                display_name=f"{clean_name}",
                dest_type=DestinationType.CITY,
                gateway_city=clean_name,
                center_coord=(104.0, 30.0),
                core_pois=[],
                search_keywords=[clean_name],
                description=f"{clean_name}常规旅游空间。",
            )

        # 写入持久化缓存 (30天 TTL)
        try:
            cache_mgr.set("geo_resolve", cache_key, resolved.to_dict(), ttl=86400 * 30)
        except Exception as e:
            logger.debug("缓存地理实体失败: %s", e)

        return resolved


resolve_destination = GeoEntityResolver.resolve
