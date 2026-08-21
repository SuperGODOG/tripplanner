# Interrupt-Resilient Agent 系统设计（分布式架构视角）

> 子 Agent: 分布式系统架构师 | 项目: TripPlanner
> 版本: **v3（2026-08-21 对齐）**——本文描述 v3 现状与已知缺口；v2 时代的"最小改动升级方案"已全部落地，并随 v3 重构（Send 分日并行、全图无回环）演进。

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

## 二、当前项目现状（v3） vs 理想态

| 原则 | 现状（v3 已做） | 缺口（可做） |
|------|-------------|-------------|
| **状态外存化** | ✅ SqliteSaver 持久化（`data/checkpoints.db`，graph.invoke 每步自动快照） | ⚠️ thread_id 每请求 uuid4——机制在但 API 层未接线，实际不可续传（见 §3.4） |
| **幂等化** | 无请求级幂等键 | ❌ 重复 POST /api/trip 会重复跑图（MCP 查询只读、记忆有入口去重，实际危害低；v3 单次规划 <10s） |
| **超时+重试+退避** | ✅ MCP 统一 `run_mcp(timeout=10)`；LLM `retry_with_backoff`（1s→2s→4s + jitter，3 次） | 无 LLM 熔断器；退避上限固定 3 次 |
| **熔断+降级** | ✅ MCP 超时快速失败 + 局部降级（三层检索降级、天气/城际 fallback、单天文案本地模板兜底） | ❌ 无熔断器——amap-mcp-server 子进程 hang 由 10s 超时兜底，不会永久阻塞 |
| **异步化** | SSE 事件发射器（queue.Queue 跨线程） | ❌ 所有 Node 同步执行；记忆写入在主路径上；无消息队列（记忆写 SQLite 毫秒级，异步化零收益，刻意不做） |

### 现有亮点（v3 仍保留）
- **三层降级链路**：多偏好 around 搜索（无城市中心时退化全城 text_search）→ 天气 `_weather_fallback` → 城际 `_intercity_fallback`（硬编码距离表），设计合理
- **本地校验闭环**：`_validate_and_refine()` 纯 Python 做硬伤/软伤检测，不依赖 LLM；v3 中校验失败只记录 error_log 透明交付（**不回环**）
- **error_log 累积**：`Annotated[list, add]` 保证错误跨节点/跨天不丢失
- **单天文案本地兜底**：day_node 文案 LLM 失败 → 本地模板生成文案，不阻断全链路
- **v3 结构性韧性**：景点集合（聚类互斥）/顺序（route_solver）/预算（本地计算）全部本地确定，LLM 只写文案——硬伤在结构上不可能由 LLM 引入，校验回环整体删除

---

## 三、v3 实际落地（对照原升级方案逐项核对）

### 3.1 SQLite Checkpoint 持久化 ✅

`builder.py`：

```python
def open_trip_graph():            # builder.py L123-137
    _project_root = os.path.abspath(os.path.join(
        os.path.dirname(__file__), "..", "..", ".."))
    db_path = os.path.join(_project_root, "data", "checkpoints.db")
    conn = sqlite3.connect(db_path, check_same_thread=False, timeout=30)
    return build_trip_graph(SqliteSaver(conn)), conn
```

- LangGraph 在 `graph.invoke` **每步 Node 执行后自动保存 State 快照**到 SQLite
- `check_same_thread=False`：LangGraph 在不同线程读写 checkpoint（实测需要）
- **连接管理（2026-08-21 修复）**：`open_trip_graph()` 返回 `(graph, conn)`，调用方 `finally` 必须 `conn.close()`——每请求独享连接，不关会累积 fd 泄漏。POST（`trip.py` L49-53）与 SSE（L123-170）两处均已接
- 旧 `get_trip_graph()` 仅保留给根目录旧验证脚本（test_graph.py / test_memory_integration.py）

**效果**：进程崩溃重启后，相同 `thread_id` 从最后 Checkpoint 继续，不重跑已完成 Node。

### 3.2 全局 MCP 并发闸 + 超时 ✅（v3 新增，防 QPS 打爆）

`amap_service.py`：

```python
MCP_MAX_WORKERS = 10
def get_mcp_executor(): ...        # 全局单例线程池，永不 shutdown
def run_mcp(args, timeout=10):     # 唯一 MCP 入口：池内提交叶子任务 + future.result(timeout)
```

- **背景**：attraction 外层多偏好并行 × 内层 geo 增强并行，嵌套放大 25+ 路并发，个人 key QPS 撑不住 → 全局池把 MCP 并发峰值钉死在 10
- **防死锁铁律**：全局池只提交「叶子 mcp.run 任务」——池内任务（search_pois 等）不得再向池内提交并等待（池满时互相等 = 死锁）；外层并行壳（多偏好 / geo 增强 / 城际双查）保持独立临时线程池
- 超时返回 `{"error": "MCP timeout"}`，调用方走降级（返回空候选 / fallback 文本）
- `AmapToolWrapper._mcp_run_with_timeout()` 现在是 `run_mcp` 的薄封装（旧"实例级临时线程池"实现已随全局池引入退役）

**效果**：MCP Server hang 不会永久阻塞 Graph；高德 QPS 不会被打爆。

### 3.3 LLM 指数退避重试 ✅（v3 只剩 1 处调用点）

`llm_service.py`：

```python
def retry_with_backoff(fn, max_retries=3, base_delay=1):
    # 重试间隔: base_delay * 2^i + random.uniform(0, 0.5)  → 1s → 2s → 4s（均加抖动）
    # 最后一次失败直接 raise，由调用方兜底
```

`trip_planner_agent.py` 的 `_run_agent_with_retry(agent, prompt, max_retries=3, **kwargs)` 包装 `agent.run()`，**kwargs（如 `response_format`）透传给 SimpleAgent.run → llm.invoke。

**v3 变化（重要）**：v2 文档"nodes.py 中 5 处 LLM 调用全部替换为 `planner._run_agent_with_retry(...)`"**已不成立**——v3 图内 LLM 调用只剩 **1 处**：`day_node` 的单天文案调用（`nodes.py` L632-635）：

```python
result = planner._run_agent_with_retry(
    planner.day_agent, text,
    response_format={"type": "json_object"},   # JSON mode 透传，输出纯 JSON 无围栏
)
```

N 天 = N 路并行调用（Send fan-out），单次输出规模缩小一个量级。planner_agent（整单 JSON 生成）已随 v2→v3 退役，不再被图引用。

**注意**：day_node 的文案 LLM 失败**不走重试兜底链路**——`retry_with_backoff` 3 次仍失败后抛异常，由 `except` 捕获 → 本地模板文案（status=`llm_fallback`）+ error_log 记录"第N天文案生成失败（已用本地模板）"，**不阻断全链路**。这是 v3 对"重试上限超限后走降级"的落地形态。

### 3.4 thread_id 配置 ✅（机制在，续传缺口已知）

`context.py`：`RequestContext.create(user_id)` → `trip_id = str(uuid4())`，`checkpoint_config = {"configurable": {"thread_id": trip_id, "checkpoint_ns": user_id, "event_sink": ...}}`。POST 与 SSE 均通过 config 传入 graph.invoke（`trip.py` L47-48 / L125-126）。没有 thread_id 时 LangGraph 无法做 checkpoint。

**⚠️ 可达性缺口（2026-08-21 评估确认）**：`RequestContext.create()` 每次生成全新 uuid4——API 层每个请求都是新 thread_id，进程重启后不可能用相同 thread_id 续传，**断点续传机制存在但实际不可达**。v3 后一次规划 10 秒内完成，中断恢复场景进一步弱化。修复方向（未做）：前端生成 trip_id 随请求传回（同会话可续），或后端按 (user_id, city, start_date, 参数哈希) 派生——参数哈希必须含预算/偏好，否则改参数重跑会命中旧 checkpoint 返回旧结果。面试若被问 checkpoint，主动交代"机制在、API 层未接线"比被戳穿强。

### 3.5 SSE 客户端断开处理 ✅

`trip.py` `/trip/stream`：`try/except asyncio.CancelledError` 包裹 run_in_executor 代码块；`cancel_event = threading.Event()` 在 CancelledError 时 set，提交给 executor 的 lambda 检查 `cancel_event.is_set()` 后短路；断开时 yield `cancelled` 事件 → return，避免线程空跑；`finally` 关闭每请求 SQLite 连接。事件经每请求独立的 SSEEmitter（queue.Queue）由轮询线程排空（50ms 间隔，有事件立即续跑）。

### 3.6 记忆去重（入口层）✅

`MemoryManager.add()` 入口检查最后一条 `_entries[-1].content == text`，相同则 return 已有 entry 跳过写入。这是 `_prune_and_dedup()` 的补充——入口层去重更高效，不连续的重复由 prune 兜底（Top-N 裁剪时按 content[:30] 去重）。

### 3.7 请求级幂等键 ❌ 未做

v2 方案"request_hash 去重缓存"未落地。现状：重复 POST /api/trip 会重复跑整个图。风险可控：MCP 查询只读无副作用、记忆写入有入口去重、v3 单次规划 <10s。

---

## 四、v3 图拓扑与韧性落点

```
START → [attraction, memory]（fan-out）→ hotel → _fan_out（Send × days）
      → day_node × N（并行）→ merge_node → END
```

- **5 个 Node**：attraction / memory / hotel 确定性检索 + day_node × N（Send 动态分发）+ merge_node（Send 汇聚只触发 1 次，实测确认）
- **v2 的 retry_planner 回环已删**：景点集合（聚类互斥）/顺序（route_solver）/预算（本地计算）全部本地确定，硬伤在结构上不可能由 LLM 引入，merge 校验失败只记录 error_log 透明交付
- day_node：本地路径求解（贪心+2-opt+时间窗）→ LLM 只写 4 段文案（description/transportation/accommodation/tips，JSON mode）→ 失败本地模板兜底；leisure 天零 LLM
- merge_node：按 day_index 排序 → 天气正则解析 → 全程酒店填充（hotel_selected）→ 三餐真实 POI → 本地预算 `_compute_budget` → `_validate_and_refine` 校验（硬伤只记录"已按当前结果交付"）→ final_plan
- checkpoint 在 graph.invoke 每步保存（SqliteSaver，`data/checkpoints.db`）

### 各层韧性职责
- **API 层**：天气/城际 fallback（`_weather_fallback` / `_FALLBACK_DISTANCES` 硬编码距离表）；SSE 断开传播取消
- **确定性节点**：检索失败 → error_log + 空数据继续（attraction 失败不阻断 hotel/day 链路）
- **MCP 层**：全局并发闸（≤10）+ 10s 超时 + geo_cached LRU(256) 缓存（失败 None 也缓存）
- **LLM 层**：指数退避重试 → 仍失败本地模板兜底（文案），不阻断
- **记忆层**：入口去重 + prune 兜底

---

## 五、总览

```
                     ┌─────────────────────────────────────┐
                     │         Interrupt-Resilient          │
                     │         Agent System（v3）           │
                     ├─────────────────────────────────────┤
  Checkpoint ───────→│  LangGraph: SqliteSaver → data/checkpoints.db
                     │  open_trip_graph() 每请求独享 conn，finally 必须 close
                     ├─────────────────────────────────────┤
  并发闸+超时 ───────→│  MCP: 全局池 max_workers=10 + run_mcp(timeout=10)
                     ├─────────────────────────────────────┤
  超时+退避 ────────→│  LLM: retry_with_backoff（1s→2s→4s+jitter，3 次）
                     ├─────────────────────────────────────┤
  降级 ────────────→ │  三层检索降级 + 天气/城际 fallback + 单天文案本地模板
                     ├─────────────────────────────────────┤
  取消传播 ─────────→│  SSE: CancelledError → cancel_event → 短路
                     ├─────────────────────────────────────┤
  去重 ─────────────→│  记忆写入: 入口层去重（add 对比末条）+ prune 兜底
                     └─────────────────────────────────────┘
```

### 已退役 / 未做
- v2 的 retry_planner / retry_hotel 回环（v3 全图无回环）——历史教训仍然有效：**conditional edge 自环必须有过硬的重试上限**（未来新增自环时必须带上限）
- 请求级幂等键（未做，实际危害低）
- MCP 熔断器（未做，10s 超时兜底）

---

## 六、测试基线（60 用例）

`tests/conftest.py` 全 Fake 注入，无网络无 LLM：

- 注入点：monkeypatch `nodes._get_amap_wrapper` / `nodes._city_center` / `nodes.get_planner` / `repository.get_memory_repository`（模块级单例函数）
- `build_trip_graph(checkpointer=InMemorySaver())`；**invoke 必须传 config** `{"configurable": {"thread_id": "..."}}`，否则报 "Checkpointer requires one or more of the following 'configurable' keys"
- FakePlanner 复用真实 `_parse_plan`（未绑定调用）；必须透传 kwargs（`response_format` 断言靠 `last_kwargs`）；v3 起必须带 `day_agent` 属性
- FakeAmapWrapper 镜像生产路由：`stype="around"` + keywords 含"酒店"要返回 hotels（hotel_node 走 around+"酒店"）
- v3 重点覆盖：day_node 文案 LLM 失败 → 本地模板兜底（test_planner_retry.py，6 用例）/ leisure 天零 LLM / merge 乱序聚合排序 / 全链路跨天景点互斥（数据层保证）/ minimax 酒店选址（远郊点排除、经济型过滤）
- 基线实证：`pytest tests/ --collect-only` = **50 tests collected**（v2 时代 42 例）
