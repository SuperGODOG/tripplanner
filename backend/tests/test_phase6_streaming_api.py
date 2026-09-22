"""Phase 6 自动化集成测试集: 多轮会话 API & SSE 流式协议

覆盖目标:
1. 缺少城市时触发 event: clarification 澄清事件与选项卡片 (test_session_chat_missing_city_triggers_clarification_event)
2. 携带相同 session_id 提交选项卡片有效恢复挂起 (test_session_chat_resume_with_option_payload)
3. 完整需求一次性输入生成 event: plan_version 与 event: message (test_session_chat_full_input_generates_plan_version)
4. 自愈优化在流式报文与行程方案中完整透出 (test_session_chat_self_healing_reflected_in_stream)
5. 会话三轨状态快照查询接口 GET /api/session/{session_id}/state (test_get_session_state_snapshot)
6. 既有老接口 /health 与主应用向下兼容性 (test_backward_compatibility_old_endpoints)
"""
import json
import os
import pytest

os.environ.setdefault("LLM_API_KEY", "mock_key_for_test")

from fastapi.testclient import TestClient
from app.api.main import app


@pytest.fixture
def client():
    return TestClient(app)


def parse_sse_events(text: str) -> list[tuple[str, dict | str]]:
    """解析标准 SSE 事件流报文"""
    events = []
    current_event = None
    current_data = None
    for line in text.split("\n"):
        line = line.strip()
        if line.startswith("event:"):
            current_event = line.replace("event:", "").strip()
        elif line.startswith("data:"):
            raw_data = line.replace("data:", "").strip()
            try:
                current_data = json.loads(raw_data)
            except Exception:
                current_data = raw_data
        elif line == "" and current_event is not None:
            events.append((current_event, current_data))
            current_event = None
            current_data = None
    return events


def test_session_chat_missing_city_triggers_clarification_event(client):
    """测试发送缺失城市的模糊输入，触发 event: clarification"""
    session_id = "test_sse_session_001"
    payload = {
        "session_id": session_id,
        "input_text": "我想带家人出去旅游，预算1万元",
    }
    response = client.post("/api/session/chat", json=payload)
    assert response.status_code == 200
    assert "text/event-stream" in response.headers.get("content-type", "")

    events = parse_sse_events(response.text)
    event_names = [e[0] for e in events]

    assert "thinking" in event_names
    assert "clarification" in event_names

    # 验证澄清卡片结构
    clarification_event = next(e[1] for e in events if e[0] == "clarification")
    assert isinstance(clarification_event, dict)
    assert "city" in clarification_event.get("missing_slots", [])
    assert len(clarification_event.get("options", [])) >= 3


def test_session_chat_resume_with_option_payload(client):
    """测试通过选项交互卡片恢复执行"""
    session_id = "test_sse_session_resume_002"

    # 1. 首次触发城市缺失
    client.post("/api/session/chat", json={"session_id": session_id, "input_text": "我想出去玩耍"})

    # 2. 模拟前端用户点击了城市选项卡片【北京】
    resume_payload = {
        "session_id": session_id,
        "action_type": "SET_SLOT",
        "action_payload": {"key": "city", "value": "北京"},
    }
    res2 = client.post("/api/session/chat", json=resume_payload)
    assert res2.status_code == 200

    events = parse_sse_events(res2.text)
    event_names = [e[0] for e in events]

    # 此时城市已补全，断言继续挂起追问天数或已推进
    assert "thinking" in event_names
    assert "clarification" in event_names
    clarification_event = next(e[1] for e in events if e[0] == "clarification")
    assert "days" in clarification_event.get("missing_slots", [])

    # 3. 模拟用户提供天数
    res3 = client.post("/api/session/chat", json={
        "session_id": session_id,
        "action_type": "SET_SLOT",
        "action_payload": {"key": "days", "value": 2},
    })
    events3 = parse_sse_events(res3.text)
    event_names3 = [e[0] for e in events3]

    # 此时城市和天数已补全，断言继续挂起追问出发日期
    assert "thinking" in event_names3
    assert "clarification" in event_names3
    clarification_event3 = next(e[1] for e in events3 if e[0] == "clarification")
    assert "start_date" in clarification_event3.get("missing_slots", [])

    # 4. 模拟用户提供出发日期
    res4 = client.post("/api/session/chat", json={
        "session_id": session_id,
        "action_type": "SET_SLOT",
        "action_payload": {"key": "start_date", "value": "2026-09-21"},
    })
    events4 = parse_sse_events(res4.text)
    event_names4 = [e[0] for e in events4]

    assert "plan_version" in event_names4
    assert "message" in event_names4
    assert "done" in event_names4


def test_session_chat_full_input_generates_plan_version(client):
    """测试一次性完整输入生成 plan_version 和 message 交付"""
    session_id = "test_sse_session_full_003"
    payload = {
        "session_id": session_id,
        "input_text": "我想去北京玩3天，2026-09-21出发，预算5000元，必须去故宫和天坛，平时一直吃辣",
    }
    response = client.post("/api/session/chat", json=payload)
    assert response.status_code == 200

    events = parse_sse_events(response.text)
    event_names = [e[0] for e in events]

    assert "thinking" in event_names
    assert "plan_version" in event_names
    assert "message" in event_names
    assert "done" in event_names

    # 验证行程版本结构
    plan_event = next(e[1] for e in events if e[0] == "plan_version")
    assert isinstance(plan_event, dict)
    assert len(plan_event.get("days", [])) == 3
    assert "故宫" in plan_event.get("locked_items", [])


def test_session_chat_self_healing_reflected_in_stream(client):
    """测试周一闭馆在流式执行中触发自愈并在回复中提示"""
    session_id = "test_sse_self_healing_004"
    # 2026-08-24 为周一，安排故宫
    payload = {
        "session_id": session_id,
        "input_text": "2026年8月24日去北京玩2天，必须去故宫博物院",
    }
    response = client.post("/api/session/chat", json=payload)
    assert response.status_code == 200

    events = parse_sse_events(response.text)
    event_names = [e[0] for e in events]

    assert "plan_version" in event_names
    message_event = next(e[1] for e in events if e[0] == "message")
    content = message_event.get("content", "")

    # 自愈提示必须在最终文案中透出
    assert "第 1 天" in content
    assert "第 2 天" in content


def test_get_session_state_snapshot(client):
    """测试查询会话三轨状态快照接口 GET /api/session/{session_id}/state"""
    # 1. 查询一个全新会话
    res_new = client.get("/api/session/non_existent_id/state")
    assert res_new.status_code == 200
    data_new = res_new.json()
    assert data_new["status"] == "new"

    # 2. 推进一个已存在的会话
    session_id = "test_state_query_005"
    client.post("/api/session/chat", json={
        "session_id": session_id,
        "input_text": "去北京玩2天，2026-09-21出发，必须去颐和园",
    })

    res_exist = client.get(f"/api/session/{session_id}/state")
    assert res_exist.status_code == 200
    data = res_exist.json()
    assert data["session_id"] == session_id
    assert data["requirements"]["slots"]["city"]["value"] == "北京"
    assert data["current_plan"] is not None
    assert len(data["current_plan"]["days"]) == 2
    assert "颐和园" in data["locked_items"]


def test_backward_compatibility_old_endpoints(client):
    """保证基础健康检查与老接口不受任何干扰"""
    res_health = client.get("/health")
    assert res_health.status_code == 200
    assert res_health.json() == {"status": "healthy"}

    res_root = client.get("/")
    assert res_root.status_code == 200
    assert "TripPlanner" in res_root.json().get("name", "")
