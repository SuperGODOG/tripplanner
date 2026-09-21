"""Phase D 流式中途抢占与实时打断转向自动化测试 (Mid-turn Steering & Preemption Tests)

面向生产级 Agent 核心面试考点全覆盖：
1. HarnessExecutionCoordinator 并发注册与新任务就地抢占旧任务
2. TravelAgentHarness 异步主循环协作取消检查点 (Cooperative Cancellation)
3. 抢占中断后状态原子回滚：不落盘残缺计划，防止脑裂 (Split-Brain) 与幽灵写入 (Phantom Overwrite)
4. REST API /api/session/interrupt 与 /api/harness/interrupt 端点打断响应
5. 中途改口槽位差量热继承 (Slot Inheritance & Delta Mutation)
"""
from __future__ import annotations

import asyncio
import pytest
from fastapi.testclient import TestClient

from app.api.main import app
from app.harness.agent_loop import TravelAgentHarness
from app.harness.coordinator import HarnessExecutionCoordinator, execution_coordinator
from app.harness.events import PreemptedEvent, ThinkingEvent, PlanVersionEvent
from app.harness.registry import ToolRegistry
from app.harness.session_store import harness_session_store
from app.models.session import EffectiveRequirements, SlotOrigin

client = TestClient(app)


@pytest.mark.asyncio
async def test_coordinator_register_and_preemption():
    """1. 验证 Coordinator 任务协调器在相同 session_id 再次入队时的抢占取消"""
    coord = HarnessExecutionCoordinator()
    sess_id = "sess_coord_test_1"

    event_1 = asyncio.Event()
    
    async def dummy_coro():
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            pass

    task_1 = asyncio.create_task(dummy_coro())
    await coord.register(sess_id, abort_event=event_1, task=task_1)

    assert sess_id in coord._handles
    assert not event_1.is_set()
    assert not task_1.done()

    # 模拟用户在生成中途发出新请求，相同 session_id 再次注册
    event_2 = asyncio.Event()
    task_2 = asyncio.create_task(dummy_coro())
    await coord.register(sess_id, abort_event=event_2, task=task_2)

    # 验证旧任务被抢占取消，旧事件被触发
    assert event_1.is_set()
    await asyncio.sleep(0.01)
    assert task_1.cancelled() or task_1.done()
    assert not event_2.is_set()
    assert not task_2.done()

    # 清理
    await coord.unregister(sess_id, abort_event=event_2)
    task_2.cancel()


@pytest.mark.asyncio
async def test_harness_loop_cooperative_cancellation_and_no_split_brain():
    """2. 验证 Harness 调度循环在协作取消点立即优雅退出，且不向会话存储写入残缺计划"""
    mock_reg = ToolRegistry()
    abort_event = asyncio.Event()

    @mock_reg.register("search_scenic_pois", "mock")
    def _m1(city, preferences=None):
        # 模拟在检索到名胜时用户突然发出打断信号
        abort_event.set()
        return [
            {"name": f"{city}名胜1", "lng": 116.40, "lat": 39.90, "category": "名胜", "typecode": "110000", "price": 40},
            {"name": f"{city}名胜2", "lng": 116.42, "lat": 39.92, "category": "名胜", "typecode": "110000", "price": 50},
        ]

    @mock_reg.register("cluster_days_kmeans", "mock")
    def _m2(pois, days):
        return [{"day_index": 0, "pois": pois}]

    @mock_reg.register("select_minimax_hotel", "mock")
    def _m3(city, attraction_coords):
        return {"hotel_selected": {"name": "中心商圈酒店", "lng": 116.41, "lat": 39.91}}

    @mock_reg.register("solve_2opt_route", "mock")
    def _m4(pois):
        class Res:
            route = [{"name": p["name"], "distance_km": 1.0, "poi": p} for p in pois]
            total_ticket = 90.0
        return Res()

    @mock_reg.register("enrich_meals", "mock")
    def _m5(plan_days, city, food_preferences=None):
        return plan_days

    harness = TravelAgentHarness(registry=mock_reg)
    sess_id = "sess_midturn_abort_test"

    events = []
    async for ev in harness.run(
        session_id=sess_id,
        user_input="2026-10-01去北京玩2天",
        user_id="test_user_steer",
        cancellation_token=abort_event,
    ):
        events.append(ev)

    # 验证产生 PreemptedEvent 事件
    preempted_events = [e for e in events if isinstance(e, PreemptedEvent)]
    assert len(preempted_events) >= 1
    assert preempted_events[0].payload["reason"] == "steered_by_user"

    # 验证不会产生 PlanVersionEvent，防止残缺计划发射给用户
    plan_events = [e for e in events if isinstance(e, PlanVersionEvent)]
    assert len(plan_events) == 0

    # 验证 session store 中没有残缺计划（防脑裂覆写）
    snap = harness_session_store.get(sess_id, user_id="test_user_steer")
    assert not snap.current_plan


def test_interrupt_api_endpoints():
    """3. 验证 REST API 中断端点响应"""
    # 测试 /api/session/interrupt
    resp = client.post("/api/session/interrupt", json={
        "session_id": "non_existent_sess",
        "user_id": "alice_explorer",
        "reason": "user_clicked_stop",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    assert data["session_id"] == "non_existent_sess"
    assert data["interrupted"] is False  # 无活跃任务时不报错，平滑幂等返回

    # 测试 /api/harness/interrupt
    h_resp = client.post("/api/harness/interrupt", json={
        "session_id": "non_existent_sess",
        "reason": "user_clicked_stop",
    })
    assert h_resp.status_code == 200
    assert h_resp.json()["status"] == "success"


@pytest.mark.asyncio
async def test_slot_inheritance_across_steering():
    """4. 验证中途改口时已确立槽位（天数、作息、出发日期）安全继承，仅热替换变异槽位"""
    mock_reg = ToolRegistry()

    @mock_reg.register("search_scenic_pois", "mock")
    def _m1(city, preferences=None):
        return [
            {"name": f"{city}西湖", "lng": 120.15, "lat": 30.25, "category": "自然", "typecode": "110000", "price": 0},
            {"name": f"{city}灵隐寺", "lng": 120.10, "lat": 30.24, "category": "古迹", "typecode": "110000", "price": 75},
        ]

    @mock_reg.register("cluster_days_kmeans", "mock")
    def _m2(pois, days):
        return [{"day_index": i, "pois": pois} for i in range(days)]

    @mock_reg.register("select_minimax_hotel", "mock")
    def _m3(city, attraction_coords):
        return {"hotel_selected": {"name": f"{city}核心酒店", "lng": 120.12, "lat": 30.25}}

    @mock_reg.register("solve_2opt_route", "mock")
    def _m4(pois):
        class Res:
            route = [{"name": p["name"], "distance_km": 1.5, "poi": p} for p in pois]
            total_ticket = 75.0
        return Res()

    @mock_reg.register("enrich_meals", "mock")
    def _m5(plan_days, city, food_preferences=None):
        for d in plan_days:
            d["meals"] = [
                {"type": "breakfast", "name": "早点", "rating": 4.6},
                {"type": "lunch", "name": "正餐", "rating": 4.7},
                {"type": "dinner", "name": "晚餐", "rating": 4.8},
            ]
        return plan_days

    harness = TravelAgentHarness(registry=mock_reg)
    sess_id = "sess_steer_inheritance"
    user_id = "alice_explorer"

    # 前序状态：北京 3 天，预算 3000 元，出发日期 2026-10-01
    initial_req = EffectiveRequirements()
    initial_req.set_slot("city", "北京", origin=SlotOrigin.USER_EXPLICIT)
    initial_req.set_slot("days", 3, origin=SlotOrigin.USER_EXPLICIT)
    initial_req.set_slot("start_date", "2026-10-01", origin=SlotOrigin.USER_EXPLICIT)
    initial_req.set_slot("budget_total", 3000, origin=SlotOrigin.USER_EXPLICIT)

    harness_session_store.update(
        session_id=sess_id,
        user_id=user_id,
        requirements=initial_req,
        new_user_message="2026-10-01去北京玩3天，预算3000",
    )

    # 模拟中途改口转向：用户插话 "等等，改成去杭州！"
    events = []
    async for ev in harness.run(
        session_id=sess_id,
        user_input="等等，改成去杭州！",
        user_id=user_id,
        is_steering=True,
    ):
        events.append(ev)

    # 验证发射了 midturn_steered 思考事件
    thinking_details = [e.payload.get("detail", "") for e in events if isinstance(e, ThinkingEvent)]
    assert any("中途改口转向" in d and "杭州" in d for d in thinking_details)

    # 验证成功定案了杭州 3 天行程，继承了前序的天数 3
    plan_events = [e for e in events if isinstance(e, PlanVersionEvent)]
    assert len(plan_events) == 1
    new_plan = plan_events[0].payload["plan"]
    assert new_plan["city"] == "杭州"
    assert len(new_plan["days"]) == 3  # 继承了 3 天！
