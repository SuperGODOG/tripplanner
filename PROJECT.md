# TripPlanner 项目文档

> Multi-Agent Trip Planner — 基于 LangGraph + HelloAgents + MCP 的多智能体旅行规划系统

---

## 一、项目总览

### 1.1 一句话描述

5 个 Node 的 LangGraph 图编排 + MCP 协议调高德地图 + API 层城际交通预处理 + 双轨异常检测画像，零人工介入完成"输入城市→输出个性化多城行程"。

### 1.2 技术栈

| 组件 | 选型 | 定位 |
|------|------|------|
| 编排引擎 | LangGraph StateGraph | 第 4-5 层：图编排 + 多智能体 |
| Agent 框架 | HelloAgents SimpleAgent | 第 3 层：ReAct 循环封装 |
| 工具协议 | MCP (amap-mcp-server) | 远程工具标准化 |
| LLM | DeepSeek (via HelloAgentsLLM) | 第 1 层：裸 API 调用 |
| Web 框架 | FastAPI + Pydantic | REST API + 类型校验 |
| 记忆 | 自定义五因子权重模块 | 用户画像持久化 |

### 1.3 架构层级

```
第 6 层  API 层预处理       ← 城际交通 _compute_intercity() + 日期 _compute_dates()
第 5 层  多智能体编排       ← TripPlanner LangGraph（5 Node，仅市内数据）
第 4 层  图编排框架         ← LangGraph StateGraph（Node/Edge/Checkpoint）
第 3 层  框架封装           ← HelloAgents SimpleAgent/ToolRegistry
第 2 层  Agent 内循环       ← ReAct（Error-as-Observation 在此层）
第 1 层  裸 LLM 调用        ← HelloAgentsLLM.invoke()
```

### 1.4 项目结构

```
backend/
├── app/
│   ├── config.py              # 配置管理（pydantic-settings + .env）
│   ├── agents/
│   │   └── trip_planner_agent.py  # 4 个 SimpleAgent
│   ├── services/
│   │   ├── amap_service.py        # MCPTool 连接（单例）
│   │   └── llm_service.py         # HelloAgentsLLM（单例）
│   ├── tools/
│   │   ├── amap_wrapper.py        # MCPTool 包装器（3 层: MCP→Format→Validate）
│   │   ├── fallback.py            # 降级工具
│   │   └── intercity.py           # 城际交通计算（API 层 _compute_intercity）
│   ├── graph/
│   │   ├── state.py               # TripPlannerState（Annotated[list, add] error_log）
│   │   ├── nodes.py               # 5 个 Node 函数
│   │   └── builder.py             # StateGraph 构建
│   ├── models/
│   │   ├── schemas.py             # Pydantic 请求/响应模型
│   │   └── transport.py           # IntercityTransport 模型
│   ├── memory/
│   │   ├── models.py              # MemoryEntry（五因子权重）
│   │   ├── classifier.py          # 领域分类 + 标签提取
│   │   ├── anomaly.py             # 双轨异常检测（IQR + 频率比）
│   │   └── manager.py             # 记忆管理（trip_count 阈值 + 画像渐进构建）
│   └── api/
│       ├── main.py                # FastAPI 应用
│       └── trip.py                # POST /api/trip（含 _compute_dates 预处理）
├── frontend/                      # 前端（6 维度标签 + 降级面板 + 画像雷达图）
├── data/
│   └── memory.json                # 记忆持久化
├── .env / .env.example
├── requirements.txt
└── run.py
```

---

## 二、Phase 1: 环境搭建与 MCP 集成

### 2.1 做了什么

- 创建 Python 项目骨架（venv + `__init__.py` + 目录结构）
- 安装依赖（hello-agents, langgraph, fastapi, fastmcp 等）
- 配置 pydantic-settings 管理 API Key
- 通过 MCPTool 连接 amap-mcp-server，验证 16 个可用工具

### 2.2 关键设计决策

**为什么用 pydantic-settings 而非 os.getenv()？**

```python
class Settings(BaseSettings):
    llm_api_key: str
    port: int = 8000       # 类型校验：写错成 "八千" 会在启动时报错
    class Config:
        env_file = ".env"  # 自动从文件读取，不用手动 load_dotenv()
```

`os.getenv()` 返回 Optional[str]，每次都要写 `int(os.getenv("PORT", "8000"))`。pydantic-settings 自动做类型转换 + 校验。

**MCPTool 的实际工作原理：**

```python
MCPTool(
    server_command=["uvx", "amap-mcp-server"],  # 启动子进程
    env={"AMAP_MAPS_API_KEY": key},             # 环境变量传给子进程
    auto_expand=True,                           # 自动展开子进程提供的工具
)
```

每次 `mcp_tool.run(...)` 的底层流程：
1. 序列化参数为 JSON
2. 通过 stdin 发送 JSON-RPC 请求给子进程
3. 子进程调用高德 HTTP API
4. 子进程通过 stdout 返回 JSON-RPC 响应
5. 父进程解析结果

**amap-mcp-server 提供的 16 个工具**：maps_text_search, maps_weather, maps_geo, maps_regeocode, maps_distance, maps_bicycling, maps_direction_walking/driving/transit 等。

---

## 三、Phase 2: 4 Agent 定义

### 3.1 做了什么

- 定义 4 个 SimpleAgent 的 Prompt（景点/天气/酒店/规划）
- 3 个工具型 Agent 共用同一个 MCPTool 实例
- Planner Agent 不需要工具（纯 LLM 推理）
- 顺序编排验证 4 Agent 协作

### 3.2 关键设计决策

**为什么 Agent 1-3 有工具，Agent 4 没有？**

Agent 1-3 是**感知型 Agent**——它们的任务是"获取外部数据"。Agent 4 是**推理型 Agent**——它的任务是"理解和重组已有数据"。给 Planner 加工具反而让它分心。

**为什么 4 个 Agent 共享 MCPTool？**

每个 MCPTool 实例启动一个 amap-mcp-server 子进程（~500ms 握手）。4 个 Agent 各建一个 = 4 个子进程 = 2 秒启动。共享 = 1 个子进程 = 0.5 秒启动。HelloAgents 框架在每次调用时带 session_id 区分来源，不会混淆。

**ReAct 循环（每个 Agent 内部）：**

```
Thought: "用户要我搜景点，我需要调工具"
Action:  [TOOL_CALL:amap_maps_text_search:keywords=景点,city=北京]
Observation: {天安门广场, 故宫, 颐和园...}
Thought: "拿到结果了，整理回复"
→ 循环结束
```

Agent 在每轮决定"要不要继续调工具"——如果 Observation 不够好，它可以继续调（多轮 ReAct）。

---

## 四、Phase 3: LangGraph 图编排

### 4.1 做了什么

- 定义 TripPlannerState（TypedDict）
- 将 4 个 Agent 封装为 **5 个 Node 函数**（4 个 Agent + memory Node）
- 构建 StateGraph + 编译
- `graph.invoke(state)` 一行替代 Phase 2 的手动顺序调用
- **城际交通计算已从图中移出到 API 层预处理**（见 Phase 5），图内仅处理市内数据

### 4.2 关键设计决策

**为什么用 LangGraph 而非手写 while 循环？**

手写 while 能串联 Agent，但 LangGraph 提供三样东西：

1. **声明式图定义**：加一个 Node 只需 `add_node` + `add_edge`，不改现有代码
2. **Checkpoint 持久化**：每步自动保存 State 快照。中断后相同 thread_id 继续——不重跑已完成的 Node
3. **Conditional Edge**：Node 失败时自动路由到降级路径

**State 的 partial update 机制：**

```python
def attraction_node(state):
    return {"attraction_data": result, "attraction_status": "success"}
    # 只返回要修改的字段，LangGraph 自动 merge 回全局 State
```

**图级 Conditional Routing vs Agent 级 Error-as-Observation（面试必考点）：**

| | 层级 | 机制 | 行为 |
|---|------|------|------|
| Conditional Routing | 图级 | Edge 读 status 字段 | 景点失败→跳过，天气继续 |
| Error-as-Observation | Agent 级 | Node 内 catch 异常 | MCP 超时→返回降级文本→Agent 自主决定 |

当前图（5 Node，城际交通在 API 层预处理，不在图中）：

```
START → attraction → weather → hotel → memory → planner → END
```

**预留: Agent 反馈环**

当前是线性流，但 LangGraph 的 conditional edge 机制天然支持循环——这是图结构（状态机）对传统顺序调用的核心优势。

举例：Planner 发现酒店不匹配景点位置/预算 → 通过 conditional edge 回到 hotel Agent 重新搜索：

```python
graph.add_conditional_edges("planner", check_status, {
    "retry_hotel": "hotel",
    "done": END
})
```

只需改一行即可实现 Agent 间闭环反馈，而传统顺序调用要加这种逻辑需要大量 if/else 和异常处理。

### 4.3 5 Node 分工详表

| Node | 类型 | 调 LLM | 调 MCP | 职责 |
|------|------|--------|--------|------|
| **attraction** | Agent | ✅ | ✅ maps_text_search | 根据城市+偏好搜索景点。ReAct 循环：LLM 决定调什么关键词，MCP 返回 POI 列表，LLM 整理结果。失败 → attraction_status="failed"，不阻断下游 |
| **weather** | Agent | ✅ | ✅ maps_weather | 查询目的地 7 日天气。独立于景点——景点失败不影响天气查询。失败 → 降级为通用穿衣建议 |
| **hotel** | Agent | ✅ | ✅ maps_text_search | 搜索目的地酒店。与景点/天气并行无依赖（当前 linear，后续 conditional edge 可并行）。失败 → 降级为通用住宿推荐 |
| **memory** | 数据加载 | ❌ | ❌ | 从 `data/memory.json` 加载用户画像，注入 `state.user_profile`。纯本地 I/O，不消耗 token。trip_count < 5 时画像为空 |
| **planner** | Agent | ✅ | ❌ | 整合前三者数据 + 用户画像，生成结构化 TripPlan JSON。**唯一不调 MCP 的 Node**——输入已由前 4 个 Node 准备好，纯 LLM 推理。根据各 Node 的 status 自动生成降级标注 |

**为什么 memory 是独立 Node 而非 planner 内部调用？**

> 职责分离：memory 管数据获取，planner 管推理。分开后可以独立测试、独立替换（后续换向量检索不影响 planner）。面试关键词：**单一职责原则**。

**为什么 planner 没有工具？**

> Planner 的输入是前 4 个 Node 已经处理好的结构化数据。给它加工具反而让它分心——Planner 的职责是"理解和重组"，不是"搜索和获取"。Agent 1-3 是感知型，Agent 4 是推理型。

**为什么城际交通不在图中？** 城际交通需要跨城市距离矩阵计算（如北京→上海），这在 Node 内通过 MCP 逐个调用效率低且增加 ReAct 轮次。提前在 API 层批量计算后注入 State，图内 Node 无需感知城际逻辑。

---

## 五、Phase 4: 本地 Tool 与 Wrapper 模式

### 5.1 做了什么

- 实现 AmapToolWrapper：包装 MCPTool，内部完成 MCP 调用→格式化→校验
- 实现 FallbackTool：所有外部服务失败时的兜底方案
- 修改 Agent 使用 Wrapper 替代原始 MCPTool

### 5.2 关键设计决策

**为什么用 Wrapper 而非独立 Tool 串联？**

```
❌ 独立 Tool（Agent 需要调 3 次）:
   Agent → MCPTool → FormatTool → ValidateTool → 现在开始思考
   浪费 3 轮 ReAct，Agent 被迫理解流水线

✅ Wrapper（Agent 只调 1 次）:
   Agent → AmapToolWrapper → 内部: MCP→Format→Validate → 返回干净文本
```

Wrapper 内部三层处理：

| 层 | 名称 | 职责 | 依赖 |
|----|------|------|------|
| 1 | MCP 调用 | 通过子进程调高德 API | 网络 I/O |
| 2 | 格式化 | JSON→结构化文本（纯 Python） | 无 |
| 3 | 校验 | 补默认值、降级标注（纯 Python） | 无 |

第 2、3 层不消耗 LLM token，不占用上下文窗口。

**FormatTool 为什么不用 LLM？**

LLM 格式化有两个问题：
1. 消耗 token——格式化指令 + JSON 原文占用上下文，挤占 Planner 的推理空间
2. 不确定性——LLM 可能误解 JSON 结构，产生幻觉

纯 Python 格式化是确定性的，100% 可控。

---

## 六、Phase 5: API 层增强 — 城际交通预处理 + 出行方式选择 + 降级透明化

### 6.1 做了什么

- **城际交通从图 Node 移至 API 层预处理**（`_compute_intercity()`）
- 实现出行方式选择（高铁/飞机/自驾）与推理逻辑
- 定义 IntercityTransport Pydantic 模型
- **降级透明化**：所有错误通过 `Annotated[list, add]` 累积，前端列表展示
- Python 本地 `_compute_dates()` 预计算日期（不交 LLM）
- 保持原有 Pydantic 校验 + CORS + Swagger UI

### 6.2 关键设计决策

**为什么城际交通在 API 层而非图 Node？**

城际交通需要跨城市距离矩阵（如北京→上海→南京→杭州）。原方案在 weather_node 或 planner_node 中通过 MCP 逐个查询——每个城市对 1 次 MCP 调用，N 个城市产生 O(N²) 次调用，且占用 ReAct 轮次。API 层在图中之前批量计算所有城市对的距离/时间/费用，一次性注入 `State.intercity_transport`，图内 Node 无需感知城际逻辑。

```
API 层 _compute_intercity(cities):
  for i, origin in enumerate(cities[:-1]):
    调用 MCP 查询 origin → cities[i+1] 的驾车/公交/步行距离
    → 按距离分类: <200km 自驾, 200-800km 高铁, >800km 飞机
    → 估算费用: 高铁 0.5元/km, 飞机 0.8元/km, 自驾 1.0元/km
    → 填充 IntercityTransport 列表
  return transport_list → 注入 State
```

**出行方式选择逻辑：**

| 距离范围 | 推荐方式 | 推理依据 |
|----------|---------|---------|
| <200km | 自驾 | 灵活、成本低（1.0元/km）、适合短途搬家 |
| 200-800km | 高铁 | 速度快、准时、性价比高（0.5元/km） |
| >800km | 飞机 | 远距离唯一高效选择（0.8元/km） |

**IntercityTransport 模型：**

```python
class IntercityTransport(BaseModel):
    origin: str          # 出发城市
    destination: str     # 到达城市
    distance_km: float   # 城市间距离
    estimated_cost: float  # 估算费用
    travel_time_hours: float  # 预计耗时
    mode: Literal["高铁", "飞机", "自驾"]  # 推荐出行方式
    classification: Literal["short", "medium", "long"]  # 距离分类
```

**降级透明化 — `Annotated[list, add]` 解决多 Node 覆盖问题：**

LangGraph 的 State partial update 默认使用**覆盖语义**——如果两个 Node 都返回 `{"error_log": err}`，后者覆盖前者。解决方案：

```python
class TripPlannerState(TypedDict):
    error_log: Annotated[list[str], add]  # add = 累加而非覆盖
```

每个 Node 的错误追加到列表，不会互相覆盖。前端拿到完整 `error_log` 以列表形式展示：

```
前端降级面板:
  ⚠️ 景点数据部分缺失（MCP 超时）→ 已使用缓存推荐
  ⚠️ 城际交通查询失败（上海→南京）→ 已使用直线距离估算
  ✅ 其他数据正常
```

**`_compute_dates()` — 日期在 Python 本地算，不交 LLM：**

```python
def _compute_dates(start_date: str, days: int) -> list[str]:
    """纯 Python 日期计算，不消耗 LLM token"""
    from datetime import date, timedelta
    start = date.fromisoformat(start_date)
    return [str(start + timedelta(days=i)) for i in range(days)]
```

LLM 不擅长日期计算（容易算错跨月/跨年），纯 Python 100% 准确且零 token 消耗。

### 6.3 三层分离（保持）

```
api/trip.py     ← HTTP 层：路由、城际交通预处理、降级聚合
models/         ← 数据层：Pydantic 定义数据 shape（IntercityTransport, TripRequest, TripPlan）
agents/ + graph/ ← 业务层：Agent 编排、工具调用（仅市内数据）
```

换编排引擎（LangGraph）只需改 agents/ 里的代码，API 层不用动。

---

## 七、Phase 6: 记忆模块（双轨异常检测 + 多维度画像）

### 7.1 做了什么

- **双轨异常检测**：数值型 IQR + 分类型频率比，两轨并行互不干扰
- 分类型异常检测覆盖 **8 个维度**：饮食/交通/节奏/住宿/预算/景点/出行方式/距离
- 画像多维度构建：**出行方式/距离偏好/住宿/预算/饮食/交通/节奏/兴趣**
- **trip_count 阈值**：≥5 次出行才显示画像（渐进构建，避免小样本误判）
- `Annotated[list, add]` 应用于多 Node error_log 累加（与 Phase 5 降级机制一致）
- 集成到 LangGraph：memory_node 加载画像到 State

### 7.2 关键设计决策

**双轨异常检测架构：**

```
输入: 新记忆条目
        │
        ├─ 数值型字段（价格、距离、天数）→ IQR 检测
        │    Q1, Q3 = percentile(values, [25, 75])
        │    IQR = max(Q3 - Q1, min_iqr)
        │    异常 = value < Q1 - 2*IQR or value > Q3 + 2*IQR
        │
        └─ 分类型字段（饮食、交通、住宿档次）→ 频率比检测
             frequency_ratio = 该类别出现次数 / 总数
             异常 = frequency_ratio < 阈值（如 0.15 = 出现次数<总次数的15%）
```

**分类型异常检测的 8 个维度：**

| 维度 | 检测字段 | 异常判定逻辑 |
|------|---------|-------------|
| 饮食偏好 | 辣/清淡/海鲜/西餐... | 出现频率 < 15% 标为异常，不纳入偏好画像 |
| 交通方式 | 地铁/公交/打车/自驾... | 偶发选择不改变默认交通画像 |
| 旅行节奏 | 轻松/紧凑/适中 | 与历史节奏不一致时降低权重 |
| 住宿档次 | 经济型/舒适型/豪华型 | 偶发豪华住宿不改变经济型画像 |
| 预算范围 | 数值区间（元） | 数值型用 IQR，分类型预算标签用频率比 |
| 景点类型 | 自然/历史/博物馆/购物... | 低频类型不纳入推荐 |
| 出行方式 | 高铁/飞机/自驾 | 与交通方式维度互补，关注城际出行偏好 |
| 距离偏好 | 短途/中途/长途 | 多数出行距离范围决定默认推荐 |

**多维度画像结构：**

```python
class UserProfile(BaseModel):
    trip_count: int                     # 出行总次数
    profile_ready: bool                 # trip_count >= 5 时为 True
    transport_mode: dict[str, float]    # {"地铁": 0.7, "打车": 0.2, "自驾": 0.1}
    distance_preference: dict[str, float]  # {"短途": 0.6, "中途": 0.3, "长途": 0.1}
    accommodation: dict[str, float]     # {"经济型": 0.8, "舒适型": 0.2}
    budget_range: dict[str, float]      # 预算偏好分布
    food_preference: dict[str, float]   # {"不辣": 0.6, "清淡": 0.3}
    transport_mode_intercity: dict[str, float]  # {"高铁": 0.7, "飞机": 0.3}
    pace_preference: dict[str, float]   # {"轻松": 0.5, "适中": 0.3, "紧凑": 0.2}
    interest_tags: dict[str, float]     # {"自然": 0.5, "历史": 0.3, "美食": 0.2}
```

**trip_count 渐进构建策略：**

```
trip_count = 1-2:  只记录，不生成画像（profile_ready = False）
trip_count = 3-4:  生成临时画像，标注「低置信度」（样本不足）
trip_count >= 5:   生成正式画像，用户可见（profile_ready = True）
                   每次新出行动态更新画像权重
```

**Alex 案例（双轨检测的综合价值）：**

```
Alex 5 次出行都选经济型酒店（300-500 元），偏好吃不辣、地铁出行

第 6 次陪老板出差：
  → 酒店: 豪华型 1500 元 → IQR 数值异常（价格偏离 2*IQR）
  → 饮食: 高档西餐 → 频率比异常（此前从未出现）
  → 交通: 豪华专车 → 频率比异常（此前以地铁为主）

传统方案: 所有新记忆权重相同，画像被"污染"，下次推荐全变
本方案:
  数值型: 豪华酒店 outlier_penalty = 0.3, 最终权重 = 0.45
          经济型酒店最终权重 = 2.40（5.3 倍主导力）
  分类型: 高档西餐/豪华专车 frequency_ratio = 1/6 ≈ 0.17
          仍低于阈值 0.25，标记为异常不纳入偏好画像
  → 画像仍保持「经济型 + 不辣 + 地铁」
```

**`Annotated[list, add]` 在多 Node 场景的应用：**

与 Phase 5 降级机制一致，多 Node 的 error_log 通过 `Annotated[list, add]` 累加：

```python
class TripPlannerState(TypedDict):
    error_log: Annotated[list[str], add]     # 累加而非覆盖
    memory_error_log: Annotated[list[str], add]  # 记忆模块独立错误通道
```

memory_node 自身出错不会污染其他 Node 的 error_log，前端区分「系统降级」和「画像异常」。

### 7.3 五因子权重公式（保持）

```
最终权重 = domain × decay × interaction × frequency_boost × outlier_penalty
```

| 因子 | 含义 | 计算方式 |
|------|------|---------|
| domain | 领域重要性 | 景点 2x > 酒店 1.5x > 天气 1x |
| decay | 时间衰减 | e^(-0.05 × 距今天数) |
| interaction | 用户反馈 | modify +0.5 / confirm +0.2 / observe 1.0 |
| frequency_boost | 统计置信度 | 1.0 + min(出现次数 × 0.15, 1.0) |
| outlier_penalty | 异常检测 | 数值型 IQR 异常 = 0.3，分类型频率比异常 = 0.2 |

### 7.4 面试讲述要点

> "我们的记忆系统有两层信号处理。第一层是**双轨异常检测**——数值型字段走 IQR，分类型字段走频率比，两轨并行互不干扰。第二层是**渐进画像构建**——不到 5 次出行不给画像，避免小样本误判。Alex 陪老板住一次豪华酒店不会永久改变他的经济型画像，分类型的高档西餐同样被频率比过滤。这是从'存/取'到'统计信号处理'的升级。"

---

## 八、Phase 7: 前端交互设计

### 8.1 做了什么

- **6 维度标签系统**：城市/天数/预算/节奏/饮食/兴趣的交互式选择
- **出行方式选择器**：高铁/飞机/自驾（与后端 IntercityTransport 模型对应）
- **降级列表面板**：前端以列表形式展示 `error_log`（按严重程度着色）
- **画像渐进构建**：trip_count < 5 时显示「画像构建中」，≥5 次展示完整画像
- 日期选择器对接后端 `_compute_dates()`

### 8.2 关键设计决策

**6 维度标签体系：**

| 维度 | 标签示例 | 交互方式 |
|------|---------|---------|
| 城市 | 北京/上海/南京...（多选） | 搜索 + 多选 badges |
| 天数 | 3/5/7/自定义 | 滑块 + 数字输入 |
| 预算 | 经济/舒适/豪华 | 三档单选，对应价格区间 |
| 节奏 | 轻松/适中/紧凑 | 三档单选，影响每日景点数 |
| 饮食 | 不辣/微辣/辣/海鲜/素食... | 多选标签 |
| 兴趣 | 自然/历史/美食/购物/亲子... | 多选标签，最多选 3 个 |

**出行方式选择器：**

与后端 `_compute_intercity()` 的分类逻辑完全对应。前端默认按距离推荐，用户可覆盖选择。选择结果写入 `State.preferred_transport_mode`。

```
北京 → 上海（1200km）: 默认推荐 ✈️ 飞机  [可选: 🚄高铁]
上海 → 南京（300km）: 默认推荐 🚄 高铁  [可选: 🚗自驾]
```

**降级列表面板：**

后端 `error_log` 通过 `Annotated[list, add]` 累加后返回前端。前端按严重程度渲染：

```
🟢 正常: 所有数据加载成功
🟡 降级: 景点推荐使用了缓存（实时 API 超时）
🟡 降级: 酒店价格查询失败，使用估算价格
🔴 异常: 画像数据加载失败，本次使用默认推荐
```

降级不影响主流程，但让用户清楚知道哪些数据是实时/缓存/估算的——**降级透明化**。

**画像渐进构建（前端视角）：**

```
trip_count = 0:  不展示画像区域
trip_count = 1-2: 显示「完成更多出行以解锁个性化画像」
trip_count = 3-4: 显示低置信度画像 + 「基于有限数据的初步画像」
trip_count >= 5:  显示完整画像雷达图（8 维度）
```
---

## 九、端到端流程

```
用户请求 POST /api/trip {"city":"北京","days":3,"cities":["北京","上海","南京"]}
     │
     ▼
API 层预处理（Phase 5）:
  ├─ _compute_dates(start_date, days)         → Python 本地日期列表
  ├─ _compute_intercity(cities)               → IntercityTransport 列表（出行方式/距离/费用）
  └─ 注入 State.intercity_transport + State.dates
     │
     ▼
graph.invoke(state)
     │
     ├─ Node 1: attraction_node   景点 Agent + MCP（Wrapper 3 层）→ 景点列表
     ├─ Node 2: weather_node      天气 Agent + MCP（Wrapper 3 层）→ 7 日预报
     ├─ Node 3: hotel_node        酒店 Agent + MCP（Wrapper 3 层）→ 酒店列表
     ├─ Node 4: memory_node       加载用户画像（双轨异常检测 + trip_count 阈值）
     └─ Node 5: planner_node      整合市内数据 + 画像 + 城际交通 → 结构化 JSON
     │
     ▼
降级聚合（Phase 5）:
  └─ error_log 通过 Annotated[list, add] 累加 → 前端降级面板
     │
     ▼
200 OK + TripPlan JSON（含 intercity_transport + dates + error_log + user_profile）
```

每一步自动 Checkpoint 持久化。中断后可续。

**关键架构要点速览：**

| 关注点 | 方案 | 位置 |
|--------|------|------|
| 城际交通 | API 层 `_compute_intercity()` 预计算 | Phase 5 |
| 出行方式 | 距离分类（<200/200-800/>800km）→ 自驾/高铁/飞机 | Phase 5 |
| 降级透明化 | `Annotated[list, add]` 累加 error_log | Phase 5 |
| 日期计算 | Python 本地 `_compute_dates()`，不交 LLM | Phase 5 |
| 数值异常检测 | IQR 方法 | Phase 6 |
| 分类异常检测 | 频率比 < 15% 阈值（8 维度） | Phase 6 |
| 画像阈值 | trip_count >= 5 才显示 | Phase 6 |
| 前端降级面板 | 按严重程度着色（🟢🟡🔴） | Phase 7 |
| 前端画像 | 雷达图（8 维度）× trip_count 渐进展示 | Phase 7 |
