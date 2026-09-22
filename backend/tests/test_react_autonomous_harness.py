"""Pi 风格大模型自主工具调用 (Autonomous ReAct Tool-Calling Harness) 深度专项测试

测试验证矩阵:
1. 完整 ReAct 闭环：模型提出 tool_call -> Harness 执行 -> Observation 回填 -> 模型再决策 -> 提交终态并验证通过。
2. 中途取消与协作抢占：工具执行前后检测 cancellation_token，安全发出 PreemptedEvent 并终止。
3. 步数上限防御：模型持续徘徊不收敛时，触发 max_steps 截断，严禁死循环并发出 ExecutionFailedEvent。
4. API 双轨调度验证：通过 /api/harness/stream 与 /api/session/chat 传入 strategy="react"，验证 SSE 报文正常分发。
"""
from __future__ import annotations

import asyncio
import json
from typing import Any
import pytest
from fastapi.testclient import TestClient

from app.api.main import app
from app.harness.agent_loop import TravelAgentHarness
from app.harness.events import (
    ThinkingEvent,
    ToolStartEvent,
    ToolEndEvent,
    PlanVersionEvent,
    TurnCompleteEvent,
    PreemptedEvent,
    ExecutionFailedEvent,
)
from app.harness.react_loop import AutonomousReActHarness, _extract_json_payload
from app.harness.registry import ToolRegistry
from app.harness.session_store import harness_session_store
from app.models.session import EffectiveRequirements


def test_extract_json_payload_resilience():
    """测试 JSON 鲁棒抽取机制 (支持裸 JSON、```json 块、混杂文本)"""
    # 1. 裸 JSON
    res1 = _extract_json_payload('{"thought": "test", "finish": true}')
    assert res1 == {"thought": "test", "finish": True}


    # 2. Markdown 代码块
    res2 = _extract_json_payload('Here is the plan:\n```json\n{"thought": "in_block", "tool_call": {"name": "search"}}\n```')
    assert res2 == {"thought": "in_block", "tool_call": {"name": "search"}}

    # 3. 混杂思考文本与外层大括号
    res3 = _extract_json_payload('I will call search now: {"thought": "mixed", "step": 1} Hope this helps!')
    assert res3 == {"thought": "mixed", "step": 1}

    # 4. 无效文本
    assert _extract_json_payload("No json here at all") is None


class MockScriptedLLM:
    """按预设步骤返回脚本决策的 Mock LLM"""

    def __init__(self, script_responses: list[str]):
        self.script_responses = list(script_responses)
        self.call_count = 0
        self.history: list[list[dict[str, str]]] = []

    def invoke(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        self.history.append(messages)
        if self.call_count < len(self.script_responses):
            resp = self.script_responses[self.call_count]
            self.call_count += 1
            return resp
        return json.dumps({"thought": "超出预设步数", "finish": True, "plan": {}})


@pytest.mark.asyncio
async def test_autonomous_react_full_loop_success():
    """1. 验证完整自主 ReAct 闭环：模型提出工具 -> 执行回填 -> 终态决策 -> 校验通过"""
    reg = ToolRegistry()

    @reg.register("search_scenic_pois", "mock search")
    def _m_search(city: str, preferences: list[str] | None = None):
        return [
            {"name": f"{city}西湖", "lng": 120.15, "lat": 30.25, "price": 0.0, "category": "风景"},
            {"name": f"{city}灵隐寺", "lng": 120.10, "lat": 30.24, "price": 45.0, "category": "寺庙"},
        ]

    @reg.register("cluster_days_kmeans", "mock cluster")
    def _m_cluster(pois: list[dict[str, Any]], days: int):
        return [{"day_index": 0, "pois": pois}]

    # 预设模型思考决策脚本
    script = [
        # Step 1: 模型决定先调用 search_scenic_pois
        json.dumps({
            "thought": "先检索杭州当地高品质人文自然景观",
            "tool_call": {
                "name": "search_scenic_pois",
                "arguments": {"city": "杭州", "preferences": ["风景"]},
            }
        }),
        # Step 2: 模型观察到景点后，调用 cluster_days_kmeans
        json.dumps({
            "thought": "将召回的 2 处景点聚簇分天",
            "tool_call": {
                "name": "cluster_days_kmeans",
                "arguments": {"pois": [{"name": "杭州西湖", "lng": 120.15, "lat": 30.25}], "days": 1},
            }
        }),
        # Step 3: 模型提交终态计划
        json.dumps({
            "thought": "全部工具调用完毕，整合生成 1 日完整行程",
            "finish": True,
            "plan": {
                "city": "杭州",
                "days": [
                    {
                        "day_index": 0,
                        "date": "2026-10-01",
                        "attractions": [
                            {"name": "杭州西湖", "lng": 120.15, "lat": 30.25, "arrive_time": "09:00", "price": 0.0},
                        ],
                    }
                ]
            }
        }),
    ]

    mock_llm = MockScriptedLLM(script)
    harness = AutonomousReActHarness(registry=reg, llm=mock_llm, max_steps=5)

    sess_id = "test-react-success-001"
    req = EffectiveRequirements()
    req.set_slot("city", "杭州")
    req.set_slot("days", 1)

    events = []
    async for ev in harness.run(
        session_id=sess_id,
        user_input="我想去杭州玩1天",
        user_id="react_tester",
        requirements=req,
    ):
        events.append(ev)

    # 1. 验证事件流发射
    tool_starts = [e for e in events if isinstance(e, ToolStartEvent)]
    assert len(tool_starts) == 2
    assert tool_starts[0].payload["tool"] == "search_scenic_pois"
    assert tool_starts[1].payload["tool"] == "cluster_days_kmeans"


    tool_ends = [e for e in events if isinstance(e, ToolEndEvent)]
    assert len(tool_ends) == 2

    # 2. 验证观察结果被回填至上下文 (Observation Feedback)
    second_step_prompt = mock_llm.history[1]
    # 第二轮的上下文中必须包含上一轮 search_scenic_pois 的 Observation
    assert any("search_scenic_pois" in m.get("content", "") for m in second_step_prompt)

    # 3. 验证产出合法 PlanVersionEvent
    plan_events = [e for e in events if isinstance(e, PlanVersionEvent)]
    assert len(plan_events) == 1
    assert plan_events[0].payload["plan"]["city"] == "杭州"

    # 4. 验证终态完成
    complete_events = [e for e in events if isinstance(e, TurnCompleteEvent)]
    assert len(complete_events) == 1
    assert complete_events[0].payload["success"] is True
    assert complete_events[0].payload["status"] == "completed"

    # 5. 验证会话快照落入内存存储
    snap = harness_session_store.get(sess_id, user_id="react_tester")
    assert snap.current_plan is not None
    assert snap.current_plan["city"] == "杭州"


@pytest.mark.asyncio
async def test_autonomous_react_step_limit_exhausted():
    """2. 验证步数上限截断防御：模型无限徘徊未达终态时安全报告失败"""
    reg = ToolRegistry()

    @reg.register("search_scenic_pois", "mock")
    def _m_search(city: str):
        return []

    # 模拟模型一直在重复调用 search_scenic_pois
    script = [
        json.dumps({
            "thought": f"尝试检索第 {i} 次",
            "tool_call": {"name": "search_scenic_pois", "arguments": {"city": "苏州"}}
        })
        for i in range(10)
    ]
    mock_llm = MockScriptedLLM(script)
    harness = AutonomousReActHarness(registry=reg, llm=mock_llm, max_steps=3)

    events = []
    async for ev in harness.run(
        session_id="test-react-limit-001",
        user_input="去苏州",
        user_id="limit_tester",
    ):
        events.append(ev)

    fail_events = [e for e in events if isinstance(e, ExecutionFailedEvent)]
    assert len(fail_events) == 1
    assert fail_events[0].payload["reason"] == "react_step_limit_exceeded"

    complete_events = [e for e in events if isinstance(e, TurnCompleteEvent)]
    assert len(complete_events) == 1
    assert complete_events[0].payload["success"] is False
    assert complete_events[0].payload["status"] == "failed"


@pytest.mark.asyncio
async def test_autonomous_react_midturn_preemption():
    """3. 验证 ReAct 循环中途取消抢占：在下一步决策前及时响应 cancellation_token"""
    reg = ToolRegistry()

    @reg.register("search_scenic_pois", "mock")
    def _m_search(city: str):
        return [{"name": "西湖", "lng": 120.15, "lat": 30.25}]

    abort_token = asyncio.Event()

    # Step 1 完成后，我们置位 abort_token
    class PreemptingMockLLM:
        def __init__(self):
            self.called = 0

        def invoke(self, messages, **kwargs):
            self.called += 1
            if self.called == 1:
                # 第一步返回工具调用，并同时触发取消信号
                abort_token.set()
                return json.dumps({
                    "thought": "正在检索景点...",
                    "tool_call": {"name": "search_scenic_pois", "arguments": {"city": "杭州"}}
                })
            return json.dumps({"thought": "下一步", "finish": True, "plan": {}})

    harness = AutonomousReActHarness(registry=reg, llm=PreemptingMockLLM(), max_steps=5)

    events = []
    async for ev in harness.run(
        session_id="test-react-preempt-001",
        user_input="去杭州",
        cancellation_token=abort_token,
    ):
        events.append(ev)

    preempt_events = [e for e in events if isinstance(e, PreemptedEvent)]
    assert len(preempt_events) == 1
    assert preempt_events[0].payload["reason"] == "steered_by_user"
    # 严禁广播计划
    assert len([e for e in events if isinstance(e, PlanVersionEvent)]) == 0


@pytest.mark.asyncio
async def test_travel_agent_harness_strategy_routing():
    """4. 验证 TravelAgentHarness 双轨路由：根据 strategy='react' 自动路由至自主 ReAct 闭环"""
    reg = ToolRegistry()

    @reg.register("search_scenic_pois", "mock")
    def _m_search(city: str, preferences=None):
        return [{"name": "故宫", "lng": 116.397, "lat": 39.918}]

    mock_llm = MockScriptedLLM([
        json.dumps({
            "thought": "ReAct 模式下自主规划",
            "finish": True,
            "plan": {
                "city": "北京",
                "days": [
                    {
                        "day_index": 0,
                        "date": "2026-10-01",
                        "attractions": [{"name": "故宫", "lng": 116.397, "lat": 39.918, "arrive_time": "09:00", "price": 60.0}],
                    }
                ]
            }
        })
    ])

    harness = TravelAgentHarness(registry=reg, strategy="react", llm=mock_llm)

    events = []
    async for ev in harness.run(
        session_id="test-dual-strategy-001",
        user_input="2026-10-01去北京玩1天",
        user_id="user_react",
    ):
        events.append(ev)

    # 验证产生 ReAct 专有思考事件与成功完成
    react_thinking = [e for e in events if isinstance(e, ThinkingEvent) and "react" in e.payload.get("step", "")]
    assert len(react_thinking) > 0

    complete_events = [e for e in events if isinstance(e, TurnCompleteEvent)]
    assert len(complete_events) == 1
    assert complete_events[0].payload["success"] is True


def test_api_session_chat_react_strategy(monkeypatch):
    """5. 验证 POST /api/session/chat 接收 strategy='react' 正常分发 SSE 报文 (密闭离线快速测试)"""
    mock_llm = MockScriptedLLM([
        json.dumps({
            "thought": "API 端点 ReAct 规划测试",
            "finish": True,
            "plan": {
                "city": "北京",
                "days": [
                    {
                        "day_index": 0,
                        "date": "2026-10-01",
                        "attractions": [{"name": "天安门", "lng": 116.397, "lat": 39.903, "arrive_time": "09:00", "price": 0.0}],
                    }
                ]
            }
        })
    ])
    monkeypatch.setattr("app.harness.react_loop.get_llm", lambda: mock_llm)

    client = TestClient(app)
    payload = {
        "session_id": "test-api-react-session",
        "user_id": "test_user_react_api",
        "input_text": "2026-10-01去北京玩1天",
        "strategy": "react",
    }

    resp = client.post("/api/session/chat", json=payload)
    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers["content-type"]
    text = resp.text
    # 验证产生 SSE 事件流格式
    assert "event:" in text
    assert "data:" in text
    assert "plan_version" in text

