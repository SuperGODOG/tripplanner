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
