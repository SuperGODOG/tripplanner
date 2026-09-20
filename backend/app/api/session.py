"""多轮会话 API 与 SSE 流式协议接口 (Session API & SSE Streaming)

提供生产级多轮对话入口，支持：
1. Server-Sent Events (SSE) 流式传输（思考进度、未决澄清卡片、行程版本 JSON、Markdown 正文流）；
2. LangGraph 原生 `interrupt` 挂起与基于 `thread_id` 的断点恢复；
3. 会话状态快照与三轨数据（需求卡片、锁定项、行程版本、历史消息）查询。
"""
from __future__ import annotations

import json
import logging
from typing import Any, AsyncGenerator, Generator
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from langgraph.types import Command
from langgraph.checkpoint.memory import InMemorySaver

from ..graph.session_graph import build_session_graph, SessionGraphState
from ..models.session import EffectiveRequirements, PlanVersion

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/session", tags=["session"])

# 全局共享 Session Graph 单例（挂载 InMemorySaver 支持跨请求 thread_id 断点续跑）
_session_saver = InMemorySaver()
_session_graph = build_session_graph(checkpointer=_session_saver)


def get_session_graph():
    return _session_graph


class ChatRequest(BaseModel):
    """会话聊天请求载荷"""
    session_id: str = Field(default_factory=lambda: str(uuid4()))
    user_id: str = "default_user"
    input_text: str = ""
    action_type: str | None = None  # "SET_SLOT" | "RESUME" | None
    action_payload: dict[str, Any] | None = None  # 如 {"key": "city", "value": "北京"}


def _format_sse(event: str, data: Any) -> str:
    """格式化标准 SSE 报文"""
    json_str = json.dumps(data, ensure_ascii=False) if not isinstance(data, str) else data
    return f"event: {event}\ndata: {json_str}\n\n"


@router.post("/chat")
async def session_chat(request: ChatRequest):
    """统一多轮会话流式交互端点 (SSE)

    客户端通过该端点发送文本或点击交互选项，以 Server-Sent Events 流式接收：
    - event: thinking (Agent 阶段思考中继)
    - event: clarification (信息缺失触发的挂起澄清卡片)
    - event: plan_version (最新行程版本结构体)
    - event: message (助手最终回复文本)
    - event: done (本轮结束)
    """
    graph = get_session_graph()
    thread_id = request.session_id
    config = {"configurable": {"thread_id": thread_id}}

    def event_stream() -> Generator[str, None, None]:
        yield _format_sse("thinking", {"step": "init", "detail": "正在接入会话协同网络..."})

        # 检查当前线程是否存在未决的 interrupt
        current_state = graph.get_state(config)
        is_interrupted = False
        if current_state.tasks:
            for task in current_state.tasks:
                if task.interrupts:
                    is_interrupted = True
                    break

        try:
            if is_interrupted:
                # 处于挂起态，执行恢复
                yield _format_sse("thinking", {"step": "resuming", "detail": "收到补全信息，正在恢复行程规划..."})
                resume_payload = request.action_payload if request.action_payload is not None else request.input_text
                stream_generator = graph.stream(
                    Command(resume=resume_payload),
                    config=config,
                    stream_mode="updates",
                )
            else:
                # 正常新轮次执行
                yield _format_sse("thinking", {"step": "clarification", "detail": "正在解析出行意图、天数与偏好约束..."})
                # 读取已有需求或新建
                existing_req = current_state.values.get("requirements") if current_state.values else None
                existing_locks = current_state.values.get("locked_items") if current_state.values else []
                existing_messages = list(current_state.values.get("messages", [])) if current_state.values else []

                if request.input_text:
                    existing_messages.append({"role": "user", "content": request.input_text})

                input_state: SessionGraphState = {
                    "session_id": request.session_id,
                    "user_id": request.user_id,
                    "thread_id": thread_id,
                    "input_text": request.input_text,
                    "messages": existing_messages,
                    "requirements": existing_req or {},
                    "locked_items": existing_locks,
                }
                stream_generator = graph.stream(
                    input_state,
                    config=config,
                    stream_mode="updates",
                )

            # 遍历图流式产出
            plan_version_emitted = False
            for chunk in stream_generator:
                # 1. 捕获中断
                if "__interrupt__" in chunk:
                    interrupts = chunk["__interrupt__"]
                    if interrupts:
                        interrupt_data = interrupts[0].value
                        yield _format_sse("clarification", interrupt_data)
                        yield _format_sse("done", {"status": "waiting_clarification"})
                        return

                # 2. 捕获规划求解与自愈进度
                if "planning_node" in chunk:
                    yield _format_sse("thinking", {"step": "planning", "detail": "已完成空间聚类与初步路线求解，正在进行营业时效与闭馆事实核验..."})
                elif "diagnose_node" in chunk:
                    yield _format_sse("thinking", {"step": "diagnosing", "detail": "正在核验行程预算与景点开放约束..."})
                elif "repair_node" in chunk:
                    yield _format_sse("thinking", {"step": "repairing", "detail": "检测到行程硬伤冲突，Repair Agent 正在执行闭环自愈优化..."})
                elif "output_node" in chunk:
                    output_data = chunk["output_node"]
                    final_plan = output_data.get("current_plan") or graph.get_state(config).values.get("current_plan")
                    if final_plan and not plan_version_emitted:
                        yield _format_sse("plan_version", final_plan)
                        plan_version_emitted = True

                    final_response = output_data.get("final_response", "")
                    if final_response:
                        yield _format_sse("message", {"content": final_response})

            # 结束信号
            # 补发 plan_version (若 output_node 未直接捕获)
            if not plan_version_emitted:
                latest_state = graph.get_state(config)
                final_plan = latest_state.values.get("current_plan") if latest_state.values else None
                if final_plan:
                    yield _format_sse("plan_version", final_plan)

            yield _format_sse("done", {"status": "completed"})

        except Exception as e:
            logger.error("会话流式执行异常: %s", e, exc_info=True)
            yield _format_sse("error", {"error": str(e), "message": "会话执行出现异常，已为您保留当前状态"})
            yield _format_sse("done", {"status": "error"})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/{session_id}/state")
async def get_session_state(session_id: str):
    """查询指定会话的当前三轨状态快照

    供前端刷新页面或恢复界面时获取当前有效需求、行程版本、历史消息与未决澄清卡片。
    """
    graph = get_session_graph()
    config = {"configurable": {"thread_id": session_id}}
    state_snapshot = graph.get_state(config)

    if not state_snapshot.values:
        return {
            "session_id": session_id,
            "status": "new",
            "requirements": {},
            "current_plan": None,
            "locked_items": [],
            "messages": [],
            "pending_clarification": None,
        }

    values = state_snapshot.values
    pending_clarification = None

    if state_snapshot.tasks:
        for task in state_snapshot.tasks:
            if task.interrupts:
                pending_clarification = task.interrupts[0].value
                break

    return {
        "session_id": session_id,
        "user_id": values.get("user_id", "default_user"),
        "status": "waiting_clarification" if pending_clarification else values.get("status", "ready"),
        "requirements": values.get("requirements", {}),
        "current_plan": values.get("current_plan"),
        "locked_items": values.get("locked_items", []),
        "messages": values.get("messages", []),
        "pending_clarification": pending_clarification,
        "attempted_actions": values.get("attempted_actions", []),
        "final_response": values.get("final_response", ""),
    }
