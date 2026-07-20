"""SSE 事件管理器 — 让前端实时看到每个 Node 的进度

用法:
  emitter = SSEEmitter()
  emitter.emit("attraction", "start")
  # ... Node 执行 ...
  emitter.emit("attraction", "done", {"count": 10})

注意: 使用 queue.Queue（线程安全），避免 asyncio.Queue 跨线程通信问题。
"""

import json
import queue
from typing import AsyncGenerator


class SSEEmitter:
    """收集 Node 进度事件，通过线程安全的 queue.Queue 跨线程通信"""

    def __init__(self):
        self._queue: queue.Queue = queue.Queue()

    def emit(self, node: str, status: str, data: dict | None = None):
        """发送事件（线程安全，可在任何线程调用）"""
        event = {"node": node, "status": status, "data": data or {}}
        self._queue.put(event)

    def get_nowait(self):
        """非阻塞获取事件，空队列时抛出 queue.Empty"""
        return self._queue.get_nowait()

    def empty(self) -> bool:
        return self._queue.empty()

    async def stream(self) -> AsyncGenerator[str, None]:
        """SSE generator — 持续 yield 事件（由调用方控制停止）"""
        import asyncio
        while True:
            try:
                event = self._queue.get(timeout=0.3)
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
            except queue.Empty:
                await asyncio.sleep(0)
