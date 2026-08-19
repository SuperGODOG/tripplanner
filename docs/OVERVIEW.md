# TripPlanner 项目总览

> Multi-Agent Trip Planner — 基于 LangGraph + HelloAgents + MCP 的多智能体旅行规划系统

_精简版；架构图见 [`ARCHITECTURE.md`](../ARCHITECTURE.md)。_

---

## 一、一句话描述

4 个 Node 的 LangGraph 图编排 + MCP 协议调高德地图 + API 层天气/城际交通预处理 + 双轨异常检测画像，零人工介入完成"输入城市 → 输出个性化多城行程"。

## 二、技术栈

| 组件 | 选型 | 定位 |
|------|------|------|
| 编排引擎 | LangGraph StateGraph | 第 4-5 层：图编排 + 多智能体 |
| Agent 框架 | HelloAgents SimpleAgent | 第 3 层：ReAct 循环封装 |
| 工具协议 | MCP (amap-mcp-server, 16 个工具) | 远程工具标准化 |
| LLM | DeepSeek (via HelloAgentsLLM) | 第 1 层：裸 API 调用 |
| Web 框架 | FastAPI + Pydantic v2 | REST API + 类型校验 |
| Checkpoint | SqliteSaver | 断点续传（`data/checkpoints.db`） |
| 记忆 | 自定义五因子权重 + 双轨异常检测 | 用户画像持久化 |
| 前端 | Vue 3 + Vite | 6 维度标签 + 降级面板 + 画像 |

## 三、架构层级（6 层）

```
第 6 层  API 层预处理       ← 天气 _fetch_weather() + 城际 _compute_intercity() + 日期本地计算
                              （intercity ∥ weather 并发；maps_geo 双查并发）
第 5 层  多智能体编排       ← TripPlanner LangGraph（4 Node + fan-out/join + Conditional Edge）
第 4 层  图编排框架         ← LangGraph StateGraph（Node/Edge/Conditional/Checkpoint）
第 3 层  框架封装           ← HelloAgents SimpleAgent/ToolRegistry
第 2 层  Agent 内循环       ← ReAct（Error-as-Observation 在此层）
第 1 层  裸 LLM 调用        ← HelloAgentsLLM.invoke() + 指数退避重试
```

## 四、项目结构

```
tripplanner/
├── README.md                    # 项目入口 + 快速部署
├── CLAUDE.md                    # 项目备忘录（Claude Code 自动读取）
├── ARCHITECTURE.md              # 7 张 Mermaid 架构图
├── docs/                        # 详细文档
│   ├── OVERVIEW.md              # 本文件
│   └── technical-notes/         # 深入技术设计
├── backend/
│   ├── app/
│   │   ├── config.py            # 配置管理（pydantic-settings + .env）
│   │   ├── agents/
│   │   │   └── trip_planner_agent.py  # 4 个 SimpleAgent
│   │   ├── services/
│   │   │   ├── amap_service.py        # MCPTool 单例
│   │   │   └── llm_service.py         # HelloAgentsLLM 单例
│   │   ├── tools/
│   │   │   ├── amap_wrapper.py        # MCPTool 3 层封装（MCP→Format→Validate）
│   │   │   └── fallback.py            # 降级工具
│   │   ├── graph/
│   │   │   ├── state.py               # TripPlannerState（Annotated[list, add] error_log）
│   │   │   ├── nodes.py               # 4 Node 函数 + 离群检测
│   │   │   ├── builder.py             # StateGraph 构建（fan-out/join + Conditional Edge）
│   │   │   └── events.py              # SSE 事件发射器
│   │   ├── memory/
│   │   │   ├── models.py, classifier.py, manager.py  # 五因子权重 + 双轨异常检测
│   │   └── api/
│   │       ├── main.py, trip.py       # FastAPI + API 层预处理
│   ├── data/                          # memory.json + checkpoints.db
│   └── run.py
└── frontend/                          # Vue 3 单页应用
```

## 五、当前拓扑（2026-07-26 最新）

```
POST /api/trip
  │
  ├─ API 层预处理（并发 ThreadPoolExecutor）
  │   ├─ _compute_intercity()          （内部两次 maps_geo 双查也并发）
  │   └─ _fetch_weather()               （与 intercity 并行提交）
  │
  └─ graph.invoke(state, config={thread_id})
       │
       ├─ START ─┬─ attraction (LLM + MCP)   ← 长任务
       │        └─ memory      (纯本地 JSON) ← 与 attraction 并行
       │
       ├─ attraction → hotel (LLM + MCP)
       │                 │
       └─ hotel + memory → planner (LLM，双入边 join)
                            │
                            ├─ retry_planner  (硬伤，MAX_RETRY=3)
                            ├─ retry_hotel    (离群，MAX_HOTEL_RETRY=2)
                            └─ done → END
       │
       └─ SqliteSaver 每步 Checkpoint（进程重启从最后成功 Node 恢复）
```

## 六、核心设计决策速览

| 关注点 | 方案 | 代码位置 |
|--------|------|---------|
| 天气查询 | API 层 `_fetch_weather()` 直接调 MCP，不占图 Node | `api/trip.py` |
| 城际交通 | API 层 `_compute_intercity()` 预计算 + 距离分类 | `api/trip.py` |
| 景点坐标增强 | maps_geo 城市中心 + maps_around 20km 半径 | `graph/nodes.py:20-70` |
| 景点群质心 | 本地 Python 计算，不交 LLM | `graph/nodes.py:53-63` |
| 景点离群检测 | 标准差法 mean+1.5σ + 80km 硬上限 | `graph/nodes.py:215-282` |
| 数值异常检测 | IQR 方法（价格） | `memory/anomaly.py` |
| 分类异常检测 | 频率比 < 阈值（饮食/交通/住宿 等 8 维） | `memory/anomaly.py` |
| Planner 自回环 | 硬伤重生成，`MAX_RETRY=3` | `graph/nodes.py:117` |
| Hotel 重试上限 | 离群重算，`MAX_HOTEL_RETRY=2` | `graph/nodes.py:118` |
| 画像阈值 | `trip_count >= 5` 才显示 | `memory/manager.py` |
| Checkpoint 持久化 | SqliteSaver → `data/checkpoints.db` | `graph/builder.py:104-107` |
| LLM 退避重试 | 指数退避 1s→2s→4s + jitter | `agents/trip_planner_agent.py:238-247` |
| MCP 超时保护 | ThreadPool + 10s 超时 | `tools/amap_wrapper.py:88-95` |
| SSE 取消传播 | cancel_event + CancelledError | `api/trip.py:184-187` |
| 记忆去重 | 连续相同记录跳过 | `memory/manager.py.add()` |
| Wrapper 3 层 | MCP → Format → Validate（Agent 只见 1 个 Tool） | `tools/amap_wrapper.py` |
| **API 层并发** | `_compute_intercity` ∥ `_fetch_weather`；maps_geo 双查并发 | `api/trip.py:32-37, 325-333` |
| **图内 fan-out** | `START → [attraction, memory]` 并行；planner 双入边 join | `graph/builder.py:79-87` |

## 七、并发安全说明

- `MCPTool.run()` 每次调用内部新建独立 event loop + MCPClient 连接，**无共享 mutable state**——多线程并发安全无需 Lock（`hello_agents.protocol_tools:339-466`）
- `error_log` 由 `Annotated[list[str], add]` reducer 自动合并——多 Node 并发写不冲突
- 已有先例：`amap_wrapper.py:126` 5-worker 线程池并发调 `maps_geo`

## 八、快速部署

见 [`README.md`](../README.md#-快速部署)。

## 九、扩展文档索引

| 想看什么 | 去哪里 |
|---------|--------|
| 项目主页 / 部署 | [`README.md`](../README.md) |
| 架构图（Mermaid） | [`ARCHITECTURE.md`](../ARCHITECTURE.md) |
| Claude Code 项目备忘录 | [`CLAUDE.md`](../CLAUDE.md) |
| 分布式容错评估 | [`docs/technical-notes/interrupt-resilient-design.md`](technical-notes/interrupt-resilient-design.md) |
