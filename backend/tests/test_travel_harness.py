"""Travel Agent Harness 单元与集成测试 (Harness & Invariants Tests)

验证核心目标:
1. 领域不变式 TravelInvariants 能够精准拦截违规并放行合规行程;
2. 工具注册中心 ToolRegistry 具备强类型调度与耗时遥测能力;
3. 核心单轮主循环 TravelAgentHarness 产出标准完整的强类型事件流。
"""
import pytest
from app.harness.events import (
    HarnessEvent,
    ThinkingEvent,
    ToolStartEvent,
    ToolEndEvent,
    PlanVersionEvent,
    MessageDeltaEvent,
    TurnCompleteEvent,
)
from app.harness.invariants import TravelInvariants
from app.harness.registry import ToolRegistry
from app.harness.agent_loop import TravelAgentHarness


def test_invariants_rejects_empty_days():
    violations = TravelInvariants.verify_plan({"days": []})
    assert len(violations) > 0
    assert any("不能为空" in v for v in violations)


def test_invariants_rejects_commercial_pois():
    bad_plan = {
        "days": [{
            "day_number": 1,
            "attractions": [
                {"name": "烫火锅(环球购物中心店)", "typecode": "050100"},
            ],
            "hotel": {"name": "舒适酒店", "price": 300},
            "meals": [{"type": "breakfast"}, {"type": "lunch"}, {"type": "dinner"}],
        }]
    }
    violations = TravelInvariants.verify_plan(bad_plan)
    assert any("景点池污染" in v for v in violations)


def test_invariants_approves_clean_plan():
    good_plan = {
        "days": [{
            "day_number": 1,
            "attractions": [
                {"name": "武侯祠博物馆", "typecode": "141200", "price": 50},
                {"name": "大熊猫繁育研究基地", "typecode": "110202", "price": 55},
            ],
            "hotel": {"name": "成都中心酒店", "price": 400},
            "meals": [
                {"type": "breakfast", "name": "老字号包子"},
                {"type": "lunch", "name": "地道川菜馆"},
                {"type": "dinner", "name": "传统家常菜"},
            ],
        }]
    }
    violations = TravelInvariants.verify_plan(good_plan, budget_limit=1000)
    assert len(violations) == 0


@pytest.mark.asyncio
async def test_tool_registry_execution():
    reg = ToolRegistry()

    @reg.register("add", "加法运算")
    def add(a: int, b: int):
        return a + b

    res, dur_ms = await reg.call("add", a=10, b=25)
    assert res == 35
    assert dur_ms >= 0


@pytest.mark.asyncio
async def test_travel_harness_loop_stream():
    """测试 Harness 主循环产出完整的事件流序列"""
    mock_reg = ToolRegistry()

    @mock_reg.register("search_scenic_pois", "mock")
    def _m1(city, preferences=None):
        return [
            {"name": f"{city}名胜A", "lng": 104.0, "lat": 30.0, "category": "风景名胜", "typecode": "110200", "price": 20},
            {"name": f"{city}名胜B", "lng": 104.05, "lat": 30.05, "category": "风景名胜", "typecode": "110200", "price": 30},
        ]

    @mock_reg.register("cluster_days_kmeans", "mock")
    def _m2(pois, days):
        return [{"day_index": 0, "pois": pois}]

    @mock_reg.register("select_minimax_hotel", "mock")
    def _m3(city, attraction_coords):
        return {"hotel_selected": {"name": "Minimax中心酒店", "price": 350}}

    @mock_reg.register("solve_2opt_route", "mock")
    def _m4(pois):
        class Res:
            route = [{"name": p["name"], "arrive_time": "09:00", "depart_time": "11:00", "distance_km": 2.0} for p in pois]
            total_ticket = 50.0
        return Res()

    @mock_reg.register("enrich_meals", "mock")
    def _m5(plan_days, city, food_preferences=None):
        for d in plan_days:
            d["meals"] = [
                {"type": "breakfast", "name": "早点", "rating": 4.6},
                {"type": "lunch", "name": "午餐", "rating": 4.7},
                {"type": "dinner", "name": "晚餐", "rating": 4.8},
            ]
        return plan_days

    @mock_reg.register("fetch_tavily_notes", "mock")
    def _m6(city, poi_name):
        return {"booking_policy": "需线上提前购票", "tips": ["早点入园避坑"], "summary": "必游景点"}

    harness = TravelAgentHarness(registry=mock_reg)

    events: list[HarnessEvent] = []
    async for ev in harness.run("session_test_123", "2026-09-21去成都玩1天"):
        events.append(ev)

    event_types = [e.event_type for e in events]

    assert "thinking" in event_types
    assert "tool_start" in event_types
    assert "tool_end" in event_types
    assert "map_action" in event_types
    assert "plan_version" in event_types
    assert "message_delta" in event_types
    assert "done" in event_types

    # 验证生成的版本内容
    plan_events = [e for e in events if isinstance(e, PlanVersionEvent)]
    assert len(plan_events) == 1
    plan = plan_events[0].payload["plan"]
    assert plan["city"] == "成都"
    assert len(plan["days"]) == 1
    assert plan["days"][0]["hotel"]["name"] == "Minimax中心酒店"


@pytest.mark.asyncio
async def test_map_action_events_and_hidden_gems():
    """测试 Pi 风格地图控制器指令流与在地秘境发现引擎"""
    from app.tools.search_tools import discover_hidden_gems_tool
    from app.harness.events import MapActionEvent

    # 1. 验证在地秘境工具发现质量
    gems_bj = discover_hidden_gems_tool(city="北京", center_coords=(116.407, 39.904), limit=2)
    assert len(gems_bj) == 2
    assert all(g.get("is_hidden_gem") is True for g in gems_bj)
    assert any("东交民巷" in g["name"] or "人艺" in g["name"] for g in gems_bj)

    # 2. 验证 Harness 循环完整发射 4 类地图控制动作
    mock_reg = ToolRegistry()

    @mock_reg.register("search_scenic_pois", "mock")
    def _m1(city, preferences=None):
        return [
            {"name": f"{city}名胜1", "lng": 116.40, "lat": 39.90, "category": "文化古迹", "typecode": "110200", "price": 40},
            {"name": f"{city}名胜2", "lng": 116.42, "lat": 39.92, "category": "文化古迹", "typecode": "110200", "price": 50},
        ]

    @mock_reg.register("discover_hidden_gems", "mock")
    def _m_gem(city, center_coords=None, limit=2):
        return discover_hidden_gems_tool(city=city, center_coords=center_coords, limit=limit)

    @mock_reg.register("cluster_days_kmeans", "mock")
    def _m2(pois, days):
        return [{"day_index": 0, "pois": pois}]

    @mock_reg.register("select_minimax_hotel", "mock")
    def _m3(city, attraction_coords):
        return {"hotel_selected": {"name": "王府井商圈酒店", "lng": 116.41, "lat": 39.91, "price": 420}}

    @mock_reg.register("solve_2opt_route", "mock")
    def _m4(pois):
        class Res:
            route = [{"name": p["name"], "arrive_time": "09:30", "depart_time": "11:30", "distance_km": 1.8, "poi": p} for p in pois]
            total_ticket = 90.0
        return Res()

    @mock_reg.register("enrich_meals", "mock")
    def _m5(plan_days, city, food_preferences=None):
        return plan_days

    @mock_reg.register("fetch_tavily_notes", "mock")
    def _m6(city, poi_name):
        return {"booking_policy": "需提前线上预约", "tips": ["避开早高峰"], "summary": "小众秘境"}

    harness = TravelAgentHarness(registry=mock_reg)
    events = []
    async for ev in harness.run("sess_map_controller", "2026-09-21去北京玩1天"):
        events.append(ev)

    map_actions = [e for e in events if isinstance(e, MapActionEvent)]
    assert len(map_actions) >= 3

    action_names = [e.payload.get("action") for e in map_actions]
    assert "FLY_TO" in action_names
    assert "SPOTLIGHT_POI" in action_names
    assert "SHOW_ISOCHRONE" in action_names
    assert "DRAW_ROUTE" in action_names

    # 验证 FLY_TO 数据
    fly_to_event = next(e for e in map_actions if e.payload.get("action") == "FLY_TO")
    assert fly_to_event.payload["data"]["city"] == "北京"
    assert len(fly_to_event.payload["data"]["center"]) == 2

    # 验证 SHOW_ISOCHRONE 数据
    isochrone_event = next(e for e in map_actions if e.payload.get("action") == "SHOW_ISOCHRONE")
    assert isochrone_event.payload["data"]["hotel_name"] == "王府井商圈酒店"
    assert isochrone_event.payload["data"]["walking_minutes"] == 15

    # 验证 DRAW_ROUTE 数据
    draw_event = next(e for e in map_actions if e.payload.get("action") == "DRAW_ROUTE")
    assert draw_event.payload["data"]["day_number"] == 1
    assert len(draw_event.payload["data"]["polyline"]) >= 2

