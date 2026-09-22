"""会话运行态任务协调器与中途抢占中枢 (Execution Coordinator & Preemption Manager)

负责管理 Sovereign Harness 会话的并发执行生命周期：
1. 注册每个活跃会话的 asyncio.Task 与 cancellation_token (asyncio.Event)；
2. 当收到用户中途打断 (Interrupt) 或改口抢占 (Mid-turn Steering) 时，瞬时终止旧任务；
3. 防止迟到的旧协程向 SQLite 或内存会话存储覆盖已作废的破损数据（防脑裂与幽灵写入）；
4. 提供优雅的协作取消边界与结构化退出通道。
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class SessionExecutionHandle:
    """会话运行态句柄"""
    session_id: str
    abort_event: asyncio.Event
    task: asyncio.Task | None = None
    reason: str = ""
    steering_input: str | None = None
    created_at: float = field(default_factory=time.time)


class HarnessExecutionCoordinator:
    """Sovereign Harness 运行态协程协调器"""

    def __init__(self):
        self._handles: dict[str, SessionExecutionHandle] = {}
        self._lock = asyncio.Lock()

    async def register(
        self,
        session_id: str,
        abort_event: asyncio.Event,
        task: asyncio.Task | None = None,
    ) -> None:
        """注册活跃会话，若该会话此前已在运行，则就地抢占取消旧任务"""
        async with self._lock:
            if session_id in self._handles:
                old_handle = self._handles[session_id]
                logger.info(
                    "会话 [%s] 检测到新请求入队，正在抢占取消前序活跃任务 (preempting old task)",
                    session_id,
                )
                old_handle.abort_event.set()
                if old_handle.task and not old_handle.task.done():
                    old_handle.task.cancel()

            self._handles[session_id] = SessionExecutionHandle(
                session_id=session_id,
                abort_event=abort_event,
                task=task,
            )

    async def attach_task(self, session_id: str, task: asyncio.Task) -> None:
        """为已注册的句柄附加 Task 引用"""
        async with self._lock:
            if session_id in self._handles:
                self._handles[session_id].task = task

    async def interrupt(
        self,
        session_id: str,
        reason: str = "steered_by_user",
        steering_input: str | None = None,
    ) -> bool:
        """主动中断指定会话当前正在执行的规划任务"""
        async with self._lock:
            handle = self._handles.get(session_id)
            if not handle:
                logger.info("会话 [%s] 当前无活跃任务，无需中断", session_id)
                return False

            logger.info("会话 [%s] 收到外部中断信号 (reason=%s)", session_id, reason)
            handle.reason = reason
            handle.steering_input = steering_input
            handle.abort_event.set()

            if handle.task and not handle.task.done():
                handle.task.cancel()

            return True

    async def unregister(self, session_id: str, abort_event: asyncio.Event | None = None) -> None:
        """注销已结束的会话句柄（校验 abort_event 防误删新接管任务）"""
        async with self._lock:
            handle = self._handles.get(session_id)
            if handle:
                if abort_event is None or handle.abort_event is abort_event:
                    self._handles.pop(session_id, None)

    def is_interrupted(self, session_id: str) -> bool:
        """同步检查该会话是否已被标记中断"""
        handle = self._handles.get(session_id)
        if handle and handle.abort_event.is_set():
            return True
        return False

    def get_handle(self, session_id: str) -> SessionExecutionHandle | None:
        """读取会话句柄"""
        return self._handles.get(session_id)

    @property
    def active_count(self) -> int:
        """当前活跃在途任务数"""
        return len(self._handles)


# 全局单例协调器
execution_coordinator = HarnessExecutionCoordinator()
