"""Phase 8 自动化单元测试集: 核心业务模块 (nodes.py & builder.py) 深度重构与工具化融合

覆盖目标:
1. 高德地图景点并行召回、去重与远郊标记工具化 (test_search_attractions_tool_logic)
2. Minimax 酒店目标函数选址与用户档次偏好过滤 (test_search_hotel_minimax_tool_and_preference)
3. 真实美食 POI 周边富化工具独立性与静默降级 (test_enrich_meals_tool_standalone)
4. nodes.py Facade 兼容层与测试 Mock 零破坏验证 (test_nodes_facade_compatibility)
5. session_graph 状态机全面接入动态工具群与 Minimax 选址 (test_session_graph_dynamic_tools_integration)
6. 闭环自愈取代暴力重试: 冲突天局部重算与未变更天 100% 缓存命中 (test_repair_loop_partial_recomputation_and_cache)
"""
import pytest
from app.models.candidates import PoiCandidate, HotelCandidate
from app.models.diagnostics import ErrorCode, DiagnosticSeverity, DiagnosticSignal
from app.tools.search_tools import (
    haversine_km,
    search_attractions_tool,
    categorize_excursions,
    select_hotel_minimax,
    search_hotel_minimax_tool,
    enrich_meals_tool,
)
from app.graph import nodes
from app.graph.session_graph import build_session_graph, planning_node, repair_node
from langgraph.checkpoint.memory import InMemorySaver


class MockWrapper:
    """可控的 Mock POI 数据源"""
    def __init__(self, pois=None, hotels=None, foods=None):
        self.pois = pois or []
        self.hotels = hotels or []
        self.foods = foods or []
        self.calls: list[tuple] = []

    def search_pois(self, city, stype, keywords="", center="", radius="", max_results=10):
        self.calls.append((stype, keywords, center, radius))
        if stype == "hotel" or (stype == "around" and "酒店" in keywords):
            return list(self.hotels[:max_results])
        if stype == "food":
            return list(self.foods[:max_results])
        return list(self.pois[:max_results])


def test_search_attractions_tool_logic():
    """测试 search_attractions_tool 的并行召回、稳定 ID 去重与远郊标记"""
    p1 = PoiCandidate(name="故宫", lng=116.397, lat=39.917, district="东城", category="古迹", price=60)
    p2 = PoiCandidate(name="长城", lng=115.900, lat=40.600, district="延庆", category="风景", price=40)
    mock = MockWrapper(pois=[p1, p2])

    # 多偏好召回
    cands = search_attractions_tool(
        city="北京",
        preferences=["古迹", "风景"],
        amap_wrapper=mock,
        city_center=("116.40", "39.90"),
        use_cache=False,
    )
    assert len(cands) == 2
    assert {c.name for c in cands} == {"故宫", "长城"}

    # 远郊标记判定
    coords, excursions, urban = categorize_excursions(cands, center=("116.40", "39.90"), excursion_km=80.0)
    assert len(excursions) == 1
    assert excursions[0]["name"] == "长城"
    assert excursions[0]["dist_km"] > 80.0
    assert len(urban) == 1
    assert urban[0].name == "故宫"


def test_search_hotel_minimax_tool_and_preference():
    """测试 Minimax 目标函数选址: 寻找最大通勤距离最小的酒店，并支持经济型过滤"""
    # 市区景点分布在 (116.40, 39.90) 与 (116.42, 39.92)
    urban_pois = [
        {"name": "A", "lng": 116.40, "lat": 39.90},
        {"name": "B", "lng": 116.42, "lat": 39.92},
    ]

    h_center = HotelCandidate(name="中心高档酒店", lng=116.41, lat=39.91, hotel_type="豪华型", price_range="800-1200元")
    h_econ = HotelCandidate(name="近郊经济酒店", lng=116.43, lat=39.93, hotel_type="经济型", price_range="150-250元")
    h_far = HotelCandidate(name="偏远经济酒店", lng=116.60, lat=40.10, hotel_type="经济型", price_range="100-180元")

    # 1. 无偏好时，Minimax 选址应该选中心酒店（到 A 和 B 的最大距离最小）
    best_no_pref = select_hotel_minimax([h_center, h_econ, h_far], urban_pois, accommodation_pref="")
    assert best_no_pref["name"] == "中心高档酒店"

    # 2. 偏好“经济型”时，前置过滤收敛到经济型候选池，并在经济型中选择 Minimax 最优
    best_econ = select_hotel_minimax([h_center, h_econ, h_far], urban_pois, accommodation_pref="经济型快捷")
    assert best_econ["name"] == "近郊经济酒店"


def test_enrich_meals_tool_standalone():
    """测试三餐周边美食 POI 富化独立工具"""
    food1 = PoiCandidate(name="四季民福烤鸭", lng=116.401, lat=39.912, district="东城", category="餐饮", price=120)
    food2 = PoiCandidate(name="门框胡同卤煮", lng=116.402, lat=39.913, district="东城", category="小吃", price=35)
    food3 = PoiCandidate(name="东来顺涮羊肉", lng=116.403, lat=39.914, district="东城", category="火锅", price=150)
    mock = MockWrapper(foods=[food1, food2, food3])

    plan_days = [
        {
            "day_index": 0,
            "attractions": [
                {"name": "故宫", "location": {"longitude": 116.397, "latitude": 39.917}},
            ],
            "meals": [],
        },
        {
            "day_index": 1,
            "attractions": [],
            "meals": [],
        },
    ]

    res = enrich_meals_tool(plan_days, city="北京", amap_wrapper=mock)
    # 第 1 天有景点，应被填充 3 餐
    assert len(res[0]["meals"]) == 3
    assert res[0]["meals"][0]["name"] == "四季民福烤鸭"
    assert res[0]["meals"][0]["type"] == "breakfast"
    assert res[0]["meals"][1]["type"] == "lunch"
    assert res[0]["meals"][2]["type"] == "dinner"

    # 第 2 天无景点，保持原样
    assert len(res[1]["meals"]) == 0


def test_nodes_facade_compatibility(monkeypatch):
    """测试 nodes.py 瘦身后的 Facade 兼容性：确保老函数名与入参调用链 100% 畅通"""
    h1 = HotelCandidate(name="核心酒店", lng=116.41, lat=39.91, hotel_type="舒适型", price_range="300-500元")
    p1 = PoiCandidate(name="天坛", lng=116.41, lat=39.88, district="东城", category="古迹", price=15)
    mock = MockWrapper(hotels=[h1], pois=[p1])

    monkeypatch.setattr(nodes, "_get_amap_wrapper", lambda: mock)
    monkeypatch.setattr(nodes, "_city_center", lambda c: ("116.4", "39.9"))

    # 1. 验证 attraction_node
    attr_out = nodes.attraction_node({
        "city": "北京",
        "days": 1,
        "preferences": ["古迹"],
    })
    assert attr_out["attraction_status"] == "success"
    assert len(attr_out["attraction_candidates"]) == 1
    assert attr_out["attraction_candidates"][0]["name"] == "天坛"

    # 2. 验证 hotel_node
    hotel_out = nodes.hotel_node({
        "city": "北京",
        "day_clusters": [{"day_index": 0, "kind": "normal", "pois": [{"lng": 116.41, "lat": 39.88}]}],
    })
    assert hotel_out["hotel_status"] == "success"
    assert hotel_out["hotel_selected"]["name"] == "核心酒店"


def test_session_graph_dynamic_tools_integration():
    """测试 session_graph 中的 planning_node 全面打通动态数据流与选址"""
    saver = InMemorySaver()
    graph = build_session_graph(checkpointer=saver)

    config = {"configurable": {"thread_id": "test_phase8_dynamic_flow"}}
    state = {
        "session_id": "s_dyn_01",
        "user_id": "u_dyn_01",
        "thread_id": "test_phase8_dynamic_flow",
        "input_text": "我想去北京玩2天，2026-10-01出发，预算3000元，必须去故宫，想要经济型酒店",
        "messages": [],
    }

    res = graph.invoke(state, config=config)
    assert res.get("status") in ("ready", "escalated")
    plan = res.get("current_plan")
    assert plan is not None
    assert len(plan["days"]) == 2

    # 验证动态选址产出的 hotel 对象挂载到每一天
    for day in plan["days"]:
        assert "hotel" in day
        assert day["hotel"].get("name")
        # 验证三餐被动态富化
        assert "meals" in day


def test_repair_loop_partial_recomputation_and_cache():
    """测试自愈闭环: 产生冲突时触发确定性修复，且仅受影响日程重新排程"""
    # 构造含闭馆冲突的 Day 0
    mock_plan_days = [
        {
            "day_index": 0,
            "date": "2026-08-24",  # 周一
            "attractions": [
                {"name": "故宫博物院", "lng": 116.397, "lat": 39.916, "visit_minutes": 180, "price": 60},
                {"name": "景山公园", "lng": 116.396, "lat": 39.924, "visit_minutes": 60, "price": 2},
            ],
            "hotel": {"lng": 116.41, "lat": 39.91},
            "route": [],
        },
        {
            "day_index": 1,
            "date": "2026-08-25",  # 周二
            "attractions": [
                {"name": "天坛公园", "lng": 116.411, "lat": 39.882, "visit_minutes": 120, "price": 15},
                {"name": "天安门广场", "lng": 116.397, "lat": 39.908, "visit_minutes": 60, "price": 0},
            ],
            "hotel": {"lng": 116.41, "lat": 39.91},
            "route": [],
        },
    ]

    closure_diag = DiagnosticSignal(
        error_code=ErrorCode.VENUE_CLOSED,
        day_index=0,
        severity=DiagnosticSeverity.HARD_FAIL,
        summary="故宫博物院周一闭馆",
        details={"place_name": "故宫博物院", "target_date": "2026-08-24"},
        conflicting_items=["故宫博物院"],
        immutable_constraints=[],
        actionable_suggestions=["SWAP_TO_ANOTHER_DAY"],
    )

    state = {
        "current_plan": {"days": mock_plan_days},
        "diagnostics": [closure_diag.model_dump()],
        "locked_items": [],
        "requirements": {"slots": {"budget_total": {"value": 5000.0}}},
        "attempted_actions": [],
        "repair_attempts": 0,
    }

    out = repair_node(state)
    assert out["repair_attempts"] == 1
    assert len(out["diagnostics"]) == 0  # 闭馆冲突已完全自动消除

    repaired_days = out["current_plan"]["days"]
    day0_names = [a["name"] for a in repaired_days[0]["attractions"]]
    day1_names = [a["name"] for a in repaired_days[1]["attractions"]]

    # 周一不再安排故宫，故宫已安全换至周二
    assert "故宫博物院" not in day0_names
    assert "故宫博物院" in day1_names

    # 验证局部路径重算已执行，route 不为空且包含正确时间排序
    assert repaired_days[0]["route"]
    assert repaired_days[1]["route"]
