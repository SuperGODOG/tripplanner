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
from pathlib import Path

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
