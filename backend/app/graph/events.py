"""SSE 事件管理器 — 让前端实时看到每个 Node 的进度

用法:
  emitter = SSEEmitter()
  emitter.emit("attraction", "start")
  # ... Node 执行 ...
  emitter.emit("attraction", "done", {"count": 10})
"""
import asyncio
import json
from typing import AsyncGenerator


class SSEEmitter:
    """收集 Node 进度事件，通过 async generator 发给 SSE"""

    def __init__(self):
        self._queue: asyncio.Queue = asyncio.Queue()

    def emit(self, node: str, status: str, data: dict | None = None):
        """发送事件（同步调用，内部 put 到 async queue）"""
        event = {"node": node, "status": status, "data": data or {}}
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.call_soon_threadsafe(self._queue.put_nowait, event)
        except RuntimeError:
            pass

    async def stream(self) -> AsyncGenerator[str, None]:
        """SSE generator — 逐个 yield 事件"""
        while True:
            event = await self._queue.get()
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
            if event["status"] == "error":
                break
