"""Harness 多轮对话、主动澄清与会话持久化集成测试 (Multi-Turn & Clarification Tests)"""
import pytest
from app.harness.agent_loop import TravelAgentHarness
from app.harness.events import ClarificationEvent, PlanVersionEvent, TurnCompleteEvent
from app.harness.session_store import harness_session_store, HarnessSessionStore
from app.models.session import EffectiveRequirements


@pytest.mark.asyncio
async def test_harness_clarification_on_missing_city_and_days():
    """测试当城市与天数均缺失时，Harness 主动发射澄清事件并挂起"""
    harness = TravelAgentHarness()
    events = []
    async for ev in harness.run(
        session_id="test_clar_sess_1",
        user_input="我想出去散散心，预算2000元",
    ):
        events.append(ev)

    # 验证第一阶段包含了澄清事件
    clar_events = [e for e in events if isinstance(e, ClarificationEvent)]
    assert len(clar_events) == 1
    assert "哪座城市" in clar_events[0].payload["prompt_text"]
    assert len(clar_events[0].payload["options"]) >= 3

    # 验证本轮任务正常挂起结束
    done_events = [e for e in events if isinstance(e, TurnCompleteEvent)]
    assert len(done_events) == 1

    # 验证状态库已记录未决澄清
    snap = harness_session_store.get("test_clar_sess_1")
    assert snap.pending_clarification is not None


@pytest.mark.asyncio
async def test_harness_clarification_on_missing_days_only():
    """测试已知目的地但缺失游玩天数时，Harness 主动询问天数"""
    harness = TravelAgentHarness()
    events = []
    async for ev in harness.run(
        session_id="test_clar_sess_2",
        user_input="我想去成都旅游",
    ):
        events.append(ev)

    clar_events = [e for e in events if isinstance(e, ClarificationEvent)]
    assert len(clar_events) == 1
    assert "成都" in clar_events[0].payload["prompt_text"]
    assert any("3天" in opt["label"] for opt in clar_events[0].payload["options"])


@pytest.mark.asyncio
async def test_harness_resume_via_action_payload():
    """测试前端点击澄清卡片回传 SET_SLOT 后，Harness 恢复执行并生成方案"""
    harness = TravelAgentHarness()
    events = []
    async for ev in harness.run(
        session_id="test_clar_sess_3",
        user_input="",
        action_type="SET_SLOT",
        action_payload={"key": "city", "value": "北京", "days": 2, "start_date": "2026-09-21"},
    ):
        events.append(ev)

    # 应当不再有澄清事件，而是直接进入规划
    clar_events = [e for e in events if isinstance(e, ClarificationEvent)]
    assert len(clar_events) == 0

    plan_events = [e for e in events if isinstance(e, PlanVersionEvent)]
    assert len(plan_events) == 1
    assert plan_events[0].payload["plan"]["city"] == "北京"
    assert len(plan_events[0].payload["plan"]["days"]) == 2

    # 验证存储库记录已更新且澄清已清除
    state = harness_session_store.to_frontend_state("test_clar_sess_3")
    assert state["pending_clarification"] is None
    assert state["current_plan"] is not None


def test_harness_session_store_lifecycle():
    """测试会话存储生命周期与前端协议兼容性"""
    store = HarnessSessionStore(max_entries=10)
    store.update(
        session_id="test_lifecycle",
        requirements={"slots": {"city": "西安", "days": 3}},
        current_plan={"city": "西安", "days": []},
        locked_items=["兵马俑"],
        new_user_message="我想去西安",
        new_assistant_message="行程已生成",
    )

    state = store.to_frontend_state("test_lifecycle")
    assert state["session_id"] == "test_lifecycle"
    assert state["effective_requirements"]["slots"]["city"] == "西安"
    assert state["locked_items"] == ["兵马俑"]
    assert len(state["messages"]) == 2
