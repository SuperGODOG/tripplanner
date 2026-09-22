"""测试基线 fixtures — 不依赖真实 LLM / 高德 MCP / 网络。

注入点:
- nodes._get_amap_wrapper → FakeAmapWrapper（确定性 POI 提供者，记录调用）
- nodes._city_center    → 固定中心（避免真实 maps_geo）
- nodes.get_planner     → FakePlanner（固定响应 + 真实 _parse_plan）
- repository.get_memory_repository → FakeRepository（内存，不写 data/memory.db）
"""
import json
import sys
import types
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models.candidates import PoiCandidate, HotelCandidate  # noqa: E402
from app.graph import nodes as nodes_module  # noqa: E402


# ── 确定性组件 ──

class FakeAmapWrapper:
    """确定性 POI 提供者：记录每次调用参数，返回固定候选。"""

    def __init__(self, pois=None, hotels=None, foods=None):
        self.pois = pois or []
        self.hotels = hotels or []
        self.foods = foods or []
        self.calls: list[tuple] = []   # (stype, keywords, center, radius)

    def search_pois(self, city, stype, keywords="", center="", radius="",
                    max_results=10):
        self.calls.append((stype, keywords, center, radius))
        # v3: hotel_node 走 around+"酒店" 关键词（stype 区分不了酒店），必须返回 hotels
        if stype == "hotel" or (stype == "around" and "酒店" in keywords):
            return list(self.hotels[:max_results])
        if stype == "food":
            return list(self.foods[:max_results])
        return list(self.pois[:max_results])


class FakePlanner:
    """确定性 LLM：返回固定响应，解析复用真实 _parse_plan。"""

    def __init__(self, response: str):
        self.response = response
        self.prompts: list[str] = []
        self.planner_agent = types.SimpleNamespace(run=self._run)
        self.day_agent = types.SimpleNamespace(run=self._run)  # v3: 单天文案 agent

    def _run(self, prompt: str, **kwargs) -> str:
        self.prompts.append(prompt)
        self.last_kwargs = kwargs  # 2026-08-21: 记录透传参数（验证 response_format）
        return self.response

    def _run_agent_with_retry(self, agent, prompt: str, max_retries=3, **kwargs) -> str:
        return agent.run(prompt, **kwargs)

    def _parse_plan(self, response: str) -> dict:
        from app.agents.trip_planner_agent import MultiAgentTripPlanner
        return MultiAgentTripPlanner._parse_plan(self, response)  # type: ignore[arg-type]


class FakeRepository:
    """内存记忆仓库：不落盘、不串用户。"""

    def __init__(self, profile=None):
        self.profile = profile or {}
        self.records: list[tuple] = []

    def get_profile(self, user_id: str) -> tuple[int, dict]:
        return 6, self.profile

    def record_trip(self, user_id: str, observations: list[str]) -> dict:
        self.records.append((user_id, observations))
        return self.profile


# ── 构造辅助 ──

def make_poi(name, lng, lat, district="", category="", price=None):
    return PoiCandidate(name=name, lng=lng, lat=lat, district=district,
                        category=category, price=price)


def make_hotel(name, lng, lat, rating="4.5", price_range="300-500元",
               hotel_type="舒适型"):
    return HotelCandidate(name=name, lng=lng, lat=lat, rating=rating,
                          price_range=price_range, hotel_type=hotel_type)


def make_plan_response(days=2, budget_total=1000, attractions_per_day=2,
                       city="北京") -> str:
    """生成通过硬伤校验的合法计划响应（含 ```json 围栏）。"""
    plan = {
        "city": city,
        "start_date": "2026-08-21",
        "end_date": "2026-08-22",
        "days": [],
        "weather_info": [
            {"date": "2026-08-21", "day_weather": "晴", "night_weather": "多云",
             "day_temp": 25, "night_temp": 15, "wind_direction": "南风", "wind_power": "1-3级"}
        ],
        "overall_suggestions": "推荐行程如下",
        "budget": {"total_attractions": 200, "total_hotels": 600,
                   "total_meals": 300, "total_transportation": 100,
                   "total": budget_total},
    }
    for i in range(days):
        plan["days"].append({
            "date": f"2026-08-{21 + i}",
            "day_index": i,
            "description": f"第{i + 1}天行程",
            "hotel": {"name": "测试酒店", "location": {"longitude": 116.4, "latitude": 39.9}},
            "attractions": [
                {"name": f"景点{i}-{j}", "location": {"longitude": 116.4 + j * 0.01, "latitude": 39.9},
                 "visit_duration": 120, "category": "历史"}
                for j in range(attractions_per_day)
            ],
            "meals": [],
        })
    return "```json\n" + json.dumps(plan, ensure_ascii=False) + "\n```"


# ── fixtures ──

@pytest.fixture
def fake_wrapper():
    return FakeAmapWrapper(
        pois=[
            make_poi("故宫", 116.397, 39.917, "东城区", "历史", 60),
            make_poi("颐和园", 116.275, 39.999, "海淀区", "公园", 30),
            make_poi("环球影城", 116.647, 39.855, "通州区", "游乐场", 400),
        ],
        hotels=[make_hotel("核心酒店", 116.40, 39.91)],
        foods=[make_poi("四季民福烤鸭", 116.397, 39.917, "东城区", "美食", 120),
               make_poi("老北京炸酱面", 116.398, 39.918, "东城区", "美食", 45),
               make_poi("糖葫芦小铺", 116.396, 39.916, "东城区", "美食", 15)],
    )


@pytest.fixture
def fake_planner():
    return FakePlanner(make_plan_response())


@pytest.fixture
def fake_repository():
    return FakeRepository()


@pytest.fixture
def patch_nodes(monkeypatch, fake_wrapper, fake_planner, fake_repository):
    """注入全部确定性组件到 nodes / repository 模块。"""
    monkeypatch.setattr(nodes_module, "_get_amap_wrapper", lambda: fake_wrapper)
    monkeypatch.setattr(nodes_module, "_city_center", lambda city: ("116.4", "39.9"))
    monkeypatch.setattr(nodes_module, "get_planner", lambda: fake_planner)
    from app.memory import repository as repo_module
    monkeypatch.setattr(repo_module, "get_memory_repository", lambda: fake_repository)
    return fake_wrapper, fake_planner, fake_repository


@pytest.fixture
def graph(monkeypatch, patch_nodes):
    """内存 checkpointer 的完整图（无网络、无 LLM）。"""
    from langgraph.checkpoint.memory import InMemorySaver
    from app.graph.builder import build_trip_graph
    return build_trip_graph(checkpointer=InMemorySaver())


def base_state(city="北京", days=2, prefs=None, budget=None):
    return {
        "user_id": "test-user",
        "origin": "上海", "city": city, "days": days,
        "start_date": "2026-08-21",
        "date_list": ["2026-08-21", "2026-08-22"],
        "transport_mode": "高铁",
        "preferences": prefs or [],
        "budget_total": budget,
        "day_start_hour": 9, "day_end_hour": 20,
        "intercity_distance_km": 1200, "intercity_duration_h": 4.5,
        "intercity_cost": 553, "distance_category": "长途",
        "attraction_data": "", "weather_data": "【天气信息】\n- 2026-08-21: 晴转多云, 25°C~15°C, 南风\n- 2026-08-22: 多云, 26°C~16°C, 南风",
        "hotel_data": "",
        "attraction_coords": [],
        "attraction_candidates": [], "hotel_candidates": [],
        "excursion_pois": [],
        "attraction_status": "", "weather_status": "success", "hotel_status": "",
        "final_plan": {}, "error_log": [], "user_profile": {},
    }


# ================================================================
# 全局网络隔离与确定性 Mock 夹具 (Autouse Network Mocks)
# ================================================================

@pytest.fixture(autouse=True)
def mock_external_network_services(monkeypatch):
    """全局自动拦截未被特定用例 mock 的外部网络与 API 调用，实现测试完全密封/脱机可用：
    1. 高德地图 AmapNativeClient._get：当未命中 Redis 缓存时，提供结构合法的确定性 Mock 返回，杜绝外部网络 HTTP 请求与配额消耗。
    2. 地理编码 _amap_geocode_lookup：提供确定性地名与行政代码解析，杜绝真实请求。
    3. 空间大模型 _llm_spatial_lookup：提供确定性大区与旅游名胜空间解析。
    """
    from datetime import datetime, timedelta
    from app.services.amap_native import AmapNativeClient
    import app.services.geo_entity_resolver as geo_resolver_module

    # 1. Mock AmapNativeClient._get
    def mock_amap_native_get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        today_str = datetime.now().strftime("%Y-%m-%d")
        if path == "/v3/weather/weatherInfo":
            city_name = params.get("city", "乐山")
            return {
                "status": "1",
                "info": "OK",
                "forecasts": [{
                    "city": city_name,
                    "adcode": "511100",
                    "province": "四川",
                    "reporttime": f"{today_str} 08:00:00",
                    "casts": [
                        {
                            "date": (datetime.now() + timedelta(days=i)).strftime("%Y-%m-%d"),
                            "dayweather": "晴",
                            "nightweather": "多云",
                            "daytemp": "26",
                            "nighttemp": "18",
                            "daywind": "微风",
                            "nightwind": "微风",
                            "daypower": "≤3",
                            "nightpower": "≤3",
                        }
                        for i in range(5)
                    ]
                }]
            }
        if path == "/v3/geocode/geo":
            addr = str(params.get("address", "北京市"))
            loc = "116.4074,39.9042"
            if "成都" in addr: loc = "104.0668,30.5728"
            elif "乐山" in addr: loc = "103.7656,29.5521"
            elif "峨眉" in addr: loc = "103.3392,29.5471"
            return {
                "status": "1",
                "info": "OK",
                "geocodes": [{
                    "formatted_address": addr,
                    "province": "北京市",
                    "city": params.get("city") or "北京市",
                    "district": "东城区",
                    "adcode": "110101",
                    "location": loc,
                    "level": "区县"
                }]
            }
        if path == "/v3/distance":
            return {
                "status": "1",
                "info": "OK",
                "results": [{
                    "origin_id": "1",
                    "dest_id": "1",
                    "distance": "1200",
                    "duration": "300"
                }]
            }
        if path == "/v3/place/detail":
            poi_id = str(params.get("id", "mock_id"))
            return {
                "status": "1",
                "info": "OK",
                "pois": [{
                    "id": poi_id,
                    "name": "高德官方认证名胜",
                    "location": "116.4074,39.9042",
                    "address": "测试文化路1号",
                    "business_area": "市中心商圈",
                    "cityname": "北京市",
                    "type": "风景名胜;国家级景点",
                    "open_time": "08:30-17:30",
                    "opentime2": "08:30-17:30",
                    "level": "AAAAA",
                    "cost": "50",
                    "rating": "4.9",
                    "biz_ext": {"rating": "4.9", "cost": "50"}
                }]
            }
        if path == "/v3/place/around":
            loc = str(params.get("location", "116.40,39.90"))
            lng, lat = 116.40, 39.90
            if "," in loc:
                try:
                    lng, lat = float(loc.split(",")[0]), float(loc.split(",")[1])
                except ValueError:
                    pass
            kw = str(params.get("keywords", ""))
            is_hotel = "酒店" in kw
            return {
                "status": "1",
                "info": "OK",
                "pois": [
                    {
                        "id": f"mock_around_{i}",
                        "name": f"精选{'舒适酒店' if is_hotel else '特色美食'}_{i}",
                        "type": "住宿服务;宾馆酒店" if is_hotel else "餐饮服务;中餐厅",
                        "typecode": "100100" if is_hotel else "050100",
                        "address": f"邻近路{i}号",
                        "location": f"{lng + 0.002 * i:.4f},{lat + 0.002 * i:.4f}",
                        "cityname": "成都市",
                        "adname": "锦江区",
                        "rating": "4.8",
                        "cost": "320" if is_hotel else "35",
                        "biz_ext": {"rating": "4.8", "cost": "320" if is_hotel else "35"}
                    }
                    for i in range(1, 5)
                ]
            }
        if path == "/v3/place/text":
            kw = str(params.get("keywords", ""))
            city = str(params.get("city", "北京"))
            is_hotel = "酒店" in kw
            return {
                "status": "1",
                "info": "OK",
                "pois": [
                    {
                        "id": f"mock_text_{i}",
                        "name": f"{city}{kw}_{i}",
                        "type": "住宿服务;宾馆酒店" if is_hotel else "风景名胜;国家级景点",
                        "typecode": "100100" if is_hotel else "110202",
                        "address": f"{city}建设大道{i}号",
                        "location": f"116.{40+i*0.01:.4f},39.{90+i*0.01:.4f}",
                        "cityname": city,
                        "adname": f"{city}市辖区",
                        "rating": "4.8",
                        "cost": "350" if is_hotel else "40",
                        "biz_ext": {"rating": "4.8", "cost": "350" if is_hotel else "40"}
                    }
                    for i in range(1, 6)
                ]
            }
        # 默认路径规划等
        return {
            "status": "1",
            "info": "OK",
            "route": {
                "paths": [{
                    "distance": "1500",
                    "duration": "300",
                    "steps": []
                }]
            }
        }

    monkeypatch.setattr(AmapNativeClient, "_get", mock_amap_native_get)

    # 2. Mock geo_entity_resolver._amap_geocode_lookup
    def mock_amap_geocode_lookup(name: str) -> dict[str, Any] | None:
        clean = name.replace("市", "").replace("省", "").replace("自治区", "").strip()
        if clean in ("川西", "陕北", "南疆"):
            return None  # 确保进入通道 B (大模型空间大区)
        if clean in ("四川", "云南", "新疆", "西藏", "陕西", "青海"):
            return {
                "formatted_address": f"{clean}省",
                "province": f"{clean}省",
                "city": f"{clean}省会",
                "district": "",
                "adcode": "510000",
                "location": "104.0668,30.5728",
                "level": "省"
            }
        if "峨眉" in clean:
            return {
                "formatted_address": "四川省乐山市峨眉山市",
                "province": "四川省",
                "city": "乐山市",
                "district": "峨眉山市",
                "adcode": "511181",
                "location": "103.3392,29.5471",
                "level": "区县"
            }
        if "乐山" in clean:
            return {
                "formatted_address": "四川省乐山市",
                "province": "四川省",
                "city": "乐山市",
                "district": "市中区",
                "adcode": "511100",
                "location": "103.7656,29.5521",
                "level": "市"
            }
        if "成都" in clean:
            return {
                "formatted_address": "四川省成都市",
                "province": "四川省",
                "city": "成都市",
                "district": "锦江区",
                "adcode": "510100",
                "location": "104.0668,30.5728",
                "level": "市"
            }
        return {
            "formatted_address": f"{clean}市",
            "province": "北京市",
            "city": f"{clean}市",
            "district": f"{clean}区",
            "adcode": "110101",
            "location": "116.4074,39.9042",
            "level": "市"
        }

    monkeypatch.setattr(geo_resolver_module, "_amap_geocode_lookup", mock_amap_geocode_lookup)

    # 3. Mock geo_entity_resolver._llm_spatial_lookup
    def mock_llm_spatial_lookup(name: str) -> dict[str, Any] | None:
        clean = name.replace("市", "").replace("省", "").replace("自治区", "").strip()
        spatial_map = {
            "川西": {
                "canonical_name": "川西高原",
                "dest_type": "region",
                "gateway_city": "成都市",
                "center_lng_lat": [102.22, 31.90],
                "core_scenic_pois": ["四姑娘山", "稻城亚丁", "九寨沟", "甲居藏寨"]
            },
            "陕北": {
                "canonical_name": "陕北",
                "dest_type": "region",
                "gateway_city": "延安市",
                "center_lng_lat": [109.48, 36.59],
                "core_scenic_pois": ["宝塔山", "黄河壶口瀑布", "延安革命纪念馆", "波浪谷"]
            },
            "南疆": {
                "canonical_name": "南疆",
                "dest_type": "region",
                "gateway_city": "喀什市",
                "center_lng_lat": [75.98, 39.46],
                "core_scenic_pois": ["喀什古城", "帕米尔高原", "白沙湖", "盘龙古道"]
            },
            "峨眉": {
                "canonical_name": "峨眉山",
                "dest_type": "scenic",
                "gateway_city": "乐山市",
                "center_lng_lat": [103.33, 29.54],
                "core_scenic_pois": ["峨眉山金顶", "万年寺", "清音阁", "报国寺"]
            },
            "四川": {
                "canonical_name": "四川省",
                "dest_type": "province",
                "gateway_city": "成都市",
                "center_lng_lat": [104.06, 30.57],
                "core_scenic_pois": ["九寨沟", "黄龙", "峨眉山", "乐山大佛"]
            },
        }
        return spatial_map.get(clean, {
            "canonical_name": clean,
            "dest_type": "city",
            "gateway_city": f"{clean}市",
            "center_lng_lat": [104.0, 30.0],
            "core_scenic_pois": [f"{clean}经典名胜1", f"{clean}经典名胜2"]
        })

    monkeypatch.setattr(geo_resolver_module, "_llm_spatial_lookup", mock_llm_spatial_lookup)
