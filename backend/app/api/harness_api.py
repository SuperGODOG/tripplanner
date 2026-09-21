"""Travel Agent Harness 极简流式 API (The Pi-Style Stream Endpoint)

设计宗旨:
1. 告别复杂的图框架胶水层，直接消费 TravelAgentHarness 产出的强类型事件流；
2. 零中间转换：ThinkingEvent、ToolStartEvent、ToolEndEvent、PlanVersionEvent 1:1 映射为标准 SSE；
3. 支持双轨并行运行：与现有的 /api/trip 和 /api/session 互不冲突，用于研发对比与平滑演进。
"""
from __future__ import annotations

import json
import logging
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ..harness.agent_loop import TravelAgentHarness
from ..harness.registry import travel_tools
from ..models.session import EffectiveRequirements

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/harness", tags=["harness"])


class HarnessChatRequest(BaseModel):
    """Harness 规划请求载荷"""
    session_id: str = Field(default_factory=lambda: str(uuid4()), description="会话唯一标识")
    user_id: str = Field(default="default_user", description="用户标识")
    input_text: str = Field(default="", description="自然语言旅行规划输入")
    action_type: str | None = Field(default=None, description="操作类型 (如 SET_SLOT / RESUME)")
    action_payload: dict[str, Any] | None = Field(default=None, description="操作载荷 (如选项卡点击)")
    requirements: dict[str, Any] | None = Field(default=None, description="已有生效需求（可选）")


def _format_sse_event(event_type: str, data: Any) -> str:
    """格式化为标准 Server-Sent Events 协议"""
    payload_str = json.dumps(data, ensure_ascii=False) if not isinstance(data, str) else data
    return f"event: {event_type}\ndata: {payload_str}\n\n"


@router.post("/stream")
async def harness_stream_chat(request: HarnessChatRequest):
    """统一 Harness 单轮流式交互端点 (SSE)

    直接产出强类型事件流：
    - event: thinking (思考推进与槽位提取)
    - event: clarification (主动交互澄清卡片)
    - event: tool_start (算法与名胜检索开始)
    - event: tool_end (算法执行完毕与耗时统计)
    - event: invariant_violation (领域不变式审计预警)
    - event: plan_version (最终排定行程快照)
    - event: message_delta (行程正文分块流)
    - event: done (单轮完成)
    """
    req_obj = None
    if request.requirements and isinstance(request.requirements, dict):
        try:
            req_obj = EffectiveRequirements(**request.requirements)
        except Exception as e:
            logger.warning("解析传入 requirements 失败: %s", e)

    harness = TravelAgentHarness(registry=travel_tools)

    async def event_generator():
        try:
            async for event in harness.run(
                session_id=request.session_id,
                user_input=request.input_text,
                user_id=request.user_id,
                current_requirements=req_obj,
                action_type=request.action_type,
                action_payload=request.action_payload,
            ):
                yield _format_sse_event(event.event_type, event.to_sse_dict())
        except Exception as e:
            logger.exception("Harness 流式执行异常: %s", e)
            yield _format_sse_event("error", {"error": str(e), "session_id": request.session_id})

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/session/{session_id}/state")
async def get_harness_session_state(session_id: str, x_user_id: str | None = Header(None)):
    """查询指定 Harness 会话的状态快照 (100% 契合前端 fetchSessionState，支持多租户鉴权)"""
    from fastapi import HTTPException
    from ..harness.session_store import harness_session_store
    try:
        return harness_session_store.to_frontend_state(session_id, user_id=x_user_id)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.get("/tools")
async def list_harness_tools():
    """查看当前 Harness 注册的所有标准算法与契约工具"""
    return {
        "status": "ok",
        "total": len(travel_tools._registry),
        "tools": travel_tools.list_tools(),
    }
