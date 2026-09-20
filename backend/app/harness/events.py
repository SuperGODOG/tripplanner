"""Pi 风格强类型事件体系 (Typed Harness Events)

统一前后端通信与 Harness 内部生命周期可观测性：
每个事件均为强类型数据类，具备事件类型名、时间戳与强结构载荷。
天然支持直通 SSE 流式输出或本地终端日志。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class HarnessEvent:
    """Harness 基础事件契约"""
    event_type: str
    payload: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def to_sse_dict(self) -> dict[str, Any]:
        """序列化为 SSE 友好格式"""
        return {
            "type": self.event_type,
            "timestamp": round(self.timestamp, 3),
            **self.payload,
        }


@dataclass
class ThinkingEvent(HarnessEvent):
    """思考与规划阶段状态广播"""
    def __init__(self, step: str, detail: str):
        super().__init__(
            event_type="thinking",
            payload={"step": step, "detail": detail}
        )


@dataclass
class ToolStartEvent(HarnessEvent):
    """工具开始执行事件"""
    def __init__(self, tool_name: str, arguments: dict[str, Any]):
        super().__init__(
            event_type="tool_start",
            payload={"tool": tool_name, "args": arguments}
        )


@dataclass
class ToolEndEvent(HarnessEvent):
    """工具执行完成事件"""
    def __init__(self, tool_name: str, result_summary: Any, duration_ms: float = 0.0):
        super().__init__(
            event_type="tool_end",
            payload={"tool": tool_name, "summary": result_summary, "duration_ms": round(duration_ms, 1)}
        )


@dataclass
class InvariantViolationEvent(HarnessEvent):
    """领域不变式校验失败与自愈触发事件"""
    def __init__(self, violations: list[str], trigger_healing: bool = True):
        super().__init__(
            event_type="invariant_violation",
            payload={"violations": violations, "trigger_healing": trigger_healing}
        )


@dataclass
class ClarificationEvent(HarnessEvent):
    """未决槽位主动交互澄清事件（前端渲染选择卡片）"""
    def __init__(self, prompt_text: str, options: list[dict[str, Any]], slot_key: str = ""):
        super().__init__(
            event_type="clarification",
            payload={
                "prompt_text": prompt_text,
                "options": options,
                "slot_key": slot_key,
            }
        )


@dataclass
class PlanVersionEvent(HarnessEvent):
    """生成或更新完整行程版本事件"""
    def __init__(self, plan: dict[str, Any]):
        super().__init__(
            event_type="plan_version",
            payload={"plan": plan}
        )


@dataclass
class MessageDeltaEvent(HarnessEvent):
    """助手最终文本回复分块流事件"""
    def __init__(self, delta: str):
        super().__init__(
            event_type="message_delta",
            payload={"delta": delta}
        )


@dataclass
class TurnCompleteEvent(HarnessEvent):
    """单轮任务完整结束事件"""
    def __init__(self, session_id: str, success: bool = True):
        super().__init__(
            event_type="done",
            payload={"session_id": session_id, "success": success}
        )
