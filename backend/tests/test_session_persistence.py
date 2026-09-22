"""会话状态持久化与快照恢复测试集 (Session State Persistence & Recovery Tests)

验证指标:
1. 会话状态快照接口 GET /api/session/{session_id}/state 的字段完整性；
2. 正常完成规划后的三轨状态持久性（requirements, current_plan, locked_items, attempted_actions）；
3. 意图缺失触发 interrupt 挂起态时的未决澄清卡片恢复（waiting_clarification, pending_clarification）。
"""
import pytest
from fastapi.testclient import TestClient
from app.api.main import app

client = TestClient(app)


def test_session_state_new_session():
    """测试全新未知会话的状态快照"""
    resp = client.get("/api/session/non_existent_session_999/state")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "new"
    assert data["session_id"] == "non_existent_session_999"
    assert data["current_plan"] is None


def test_session_state_after_full_planning():
    """测试完整规划后能够通过 session_id 准确恢复三轨状态"""
    session_id = "test_persist_sess_001"

    # 1. 触发会话规划
    chat_resp = client.post(
        "/api/session/chat",
        json={
            "session_id": session_id,
            "input_text": "我想去乐山峨眉山玩3天左右，2026-09-21出发，给我推荐一些美食和景点,我一个人",
        },
    )
    assert chat_resp.status_code == 200

    # 2. 查询快照状态
    state_resp = client.get(f"/api/session/{session_id}/state")
    assert state_resp.status_code == 200
    state = state_resp.json()

    assert state["session_id"] == session_id
    assert state["status"] in ("ready", "completed")

    # 验证三轨需求恢复
    reqs = state.get("requirements", {})
    slots = reqs.get("slots", {})
    assert slots.get("city", {}).get("value") == "乐山"
    assert slots.get("days", {}).get("value") == 3

    # 验证锁定项恢复
    assert "峨眉山" in state.get("locked_items", [])

    # 验证行程版本看板恢复
    plan = state.get("current_plan")
    assert plan is not None
    assert len(plan.get("days", [])) == 3

    # 验证自愈记录存在
    assert isinstance(state.get("attempted_actions"), list)


def test_session_state_pending_clarification_recovery():
    """测试未决澄清状态在刷新时能被准确检索恢复"""
    session_id = "test_clarify_sess_002"

    # 发送缺少城市的模糊请求触发澄清挂起
    chat_resp = client.post(
        "/api/session/chat",
        json={
            "session_id": session_id,
            "input_text": "我想出去玩3天",
        },
    )
    assert chat_resp.status_code == 200

    state_resp = client.get(f"/api/session/{session_id}/state")
    assert state_resp.status_code == 200
    state = state_resp.json()

    assert state["status"] == "waiting_clarification"
    assert state.get("pending_clarification") is not None
    assert "city" in state["pending_clarification"].get("missing_slots", [])
