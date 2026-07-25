# Interrupt-Resilient Agent 系统设计（分布式架构视角）

> 子 Agent: 分布式系统架构师 | 项目: TripPlanner

---

## 一、设计原则（五条铁律）

### 1. 状态外存化（Checkpoint）
每次 Node 执行后将 State 持久化到外部存储（SQLite / Redis / S3），而非仅靠内存。进程崩溃后能从最近断点恢复，不重跑已完成 Node。

### 2. 操作幂等化
每个外部调用（API / MCP / LLM）带上幂等键（idempotency key）。同一请求重放不产生副作用（重复扣费、重复创建资源）。

### 3. 超时 + 重试 + 退避
每次网络 I/O 必须有显式超时。重试使用指数退避（exponential backoff）+ 随机抖动（jitter），避免惊群效应。重试有上限，超限后走降级。

### 4. 熔断 + 降级
外部依赖（MCP Server / LLM API）连续失败超过阈值 → 熔断器打开 → 快速失败 → 走降级路径。熔断器半开后试探性放行一个请求。

### 5. 异步化（非关键路径放消息队列）
不阻塞主流程的副作用操作（写日志、发通知、更新画像）放入消息队列异步执行。主流程只等关键路径结果。

---

## 二、当前项目现状 vs 理想态

| 原则 | 现状（已做） | 缺口（可做） |
|------|-------------|-------------|
| **状态外存化** | LangGraph 默认启用 Checkpoint（**内存**） | ❌ 无持久化——进程崩溃后 State 丢失，无法从断点恢复 |
| **幂等化** | 无 | ❌ 无请求级幂等键，重复 POST /api/trip 会产生重复副作用 |
| **超时+重试+退避** | ✅ conditional edge 重试上限（MAX_RETRY=3, MAX_HOTEL_RETRY=2）；三层降级（around→text_search→fallback） | ⚠️ LLM/MCP 调用无显式超时；重试无退避策略（立即重试） |
| **熔断+降级** | ✅ FallbackTool 兜底；硬编码距离表；天气/城际交通有 fallback | ❌ MCP 连接无熔断器——amap-mcp-server 子进程 hang 住会阻塞整个图 |
| **异步化** | SSE 事件发射器（queue.Queue 跨线程） | ❌ 所有 Node 同步执行；记忆写入在主路径上；无消息队列 |

### 现有亮点（值得保留）
- **三层降级链路**：around 搜索 → 全城 text_search → FallbackTool，设计合理
- **本地校验闭环**：`_validate_and_refine()` 纯 Python 做硬伤/软伤/离群检测，不依赖 LLM
- **error_log 累积**：`Annotated[list, add]` 保证错误跨 retry 不丢失
- **中心覆写机制**：离群检测后重新计算中心，回环酒店重搜

---

## 三、最小改动升级方案（只加不改）

### 原则：不动现有 Node 逻辑，只在外围加"保护层"

### 改动 1：SQLite Checkpoint 持久化（~30 行）

```python
# backend/app/graph/checkpoint.py（新文件）
from langgraph.checkpoint.sqlite import SqliteSaver

def get_checkpointer(db_path: str = "data/checkpoints.db"):
    import os
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    return SqliteSaver.from_conn_string(db_path)
```

在 `builder.py` 中：
```python
# 原来: graph.compile()
# 改为:
from .checkpoint import get_checkpointer
checkpointer = get_checkpointer()
return graph.compile(checkpointer=checkpointer)
```

**效果**：进程崩溃重启后，相同 `thread_id` 从最后 Checkpoint 继续。

### 改动 2：MCP 调用加超时 + 熔断（~50 行）

```python
# backend/app/tools/resilience.py（新文件）
import time, threading

class CircuitBreaker:
    def __init__(self, failure_threshold=3, timeout=30):
        self.failure_count = 0
        self.failure_threshold = failure_threshold
        self.timeout = timeout
        self.last_failure_time = 0
        self.state = "closed"  # closed → open → half_open
        self._lock = threading.Lock()

    def call(self, fn, *args, **kwargs):
        with self._lock:
            if self.state == "open":
                if time.time() - self.last_failure_time > self.timeout:
                    self.state = "half_open"
                else:
                    raise Exception("Circuit breaker open")
        try:
            result = fn(*args, **kwargs)
            with self._lock:
                self.failure_count = 0
                self.state = "closed"
            return result
        except Exception:
            with self._lock:
                self.failure_count += 1
                self.last_failure_time = time.time()
                if self.failure_count >= self.failure_threshold:
                    self.state = "open"
            raise
```

在 `AmapToolWrapper._call_mcp` 最外层加超时包装：

```python
# 在 _call_mcp 方法中，_mcp.run(...) 改为带超时
import signal  # 或用 concurrent.futures
```

**效果**：MCP Server hang 住不会永久阻塞 Graph。

### 改动 3：LLM 调用加指数退避（~15 行）

在 `MultiAgentTripPlanner` 的 agent.run() 调用上加一层 retry wrapper：

```python
# 在 trip_planner_agent.py 或 llm_service.py 中
import time, random

def retry_with_backoff(fn, max_retries=3, base_delay=1):
    for i in range(max_retries):
        try:
            return fn()
        except Exception:
            if i == max_retries - 1:
                raise
            delay = base_delay * (2 ** i) + random.uniform(0, 1)
            time.sleep(delay)
```

**效果**：LLM 瞬时不可用不会立即失败。

### 改动 4：请求级幂等键（~20 行）

```python
# backend/app/api/trip.py 中
import uuid, hashlib

# plan_trip() 函数开头加:
request_hash = hashlib.sha256(
    f"{request.city}{request.days}{request.start_date}{request.preferences}".encode()
).hexdigest()[:16]
# 查 SQLite: 如果 request_hash 已有结果，直接返回缓存结果
```

**效果**：重复 POST 不会重复跑整个图。

---

## 四、总览

```
                     ┌─────────────────────────────────────┐
                     │         Interrupt-Resilient          │
                     │         Agent System                 │
                     ├─────────────────────────────────────┤
  幂等键 ──────────→ │  API 层: request_hash 去重           │
                     ├─────────────────────────────────────┤
  Checkpoint ───────→│  LangGraph: SQLite 持久化 State      │
                     │  每个 Node 后自动快照                 │
                     ├─────────────────────────────────────┤
  超时+退避 ────────→│  LLM 调用: retry_with_backoff        │
                     ├─────────────────────────────────────┤
  熔断 ────────────→ │  MCP: CircuitBreaker (3 次失败熔断)  │
                     ├─────────────────────────────────────┤
  降级 ────────────→ │  现有: 三层降级 (around→search→fallback)│
                     ├─────────────────────────────────────┤
  异步化 ──────────→│  记忆写入: 可选移入后台线程           │
                     └─────────────────────────────────────┘
```

### 不改的部分
- `nodes.py`（4 个 Node 函数）— 零改动
- `state.py` — 零改动
- `builder.py` — 仅 compile() 加 checkpointer 参数
- `AmapToolWrapper` — 仅 `_call_mcp` 外覆超时
- `trip.py` API 层 — 仅加幂等键查询

**总计新增代码 ~150 行，不修改任何现有 Node 逻辑。**
