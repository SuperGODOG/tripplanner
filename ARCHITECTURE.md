# TripPlanner — 全套架构图 (Mermaid)

_在 VSCode 中装 `Markdown Preview Mermaid Support` 插件后即可预览_

---

## 图 1：系统分层架构（5 层）

```mermaid
flowchart TB
    subgraph APILayer["API 层: 请求预处理（FastAPI）"]
        direction LR
        PRE1["日期计算<br/>Python 本地预计算<br/>不交 LLM"]
        PRE2["城际交通<br/>距离/时间/费用<br/>高德 API + fallback"]
    end

    subgraph Layer5["第 5 层: 多智能体编排"]
        direction LR
        N1["attraction_node<br/>景点 Agent + MCP"]
        N2["weather_node<br/>天气 Agent + MCP"]
        N3["hotel_node<br/>酒店 Agent + MCP"]
        N4["memory_node<br/>加载用户画像<br/>（纯本地读取）"]
        N5["planner_node<br/>整合 + 推理<br/>（无工具，纯推理）"]
    end

    subgraph Layer4["第 4 层: 图编排 (LangGraph)"]
        EDGE["Edge: attraction→weather→hotel→memory→planner"]
        ERRLOG["error_log: Annotated[list, add]<br/>所有 Node 降级写入，自动累积"]
        CHECKPOINT["Checkpoint: 每步 State 自动快照"]
    end

    subgraph Layer3["第 3 层: 框架封装 (HelloAgents)"]
        AGENT["SimpleAgent<br/>ReAct 循环 + Prompt + add_tool()"]
    end

    subgraph Layer2["第 2 层: Agent 内循环"]
        REACT["ReAct: Thought→Action→Observation<br/>Error-as-Observation 在此层"]
    end

    subgraph Layer1["第 1 层: 裸 LLM 调用"]
        LLM["HelloAgentsLLM<br/>DeepSeek API"]
    end

    subgraph ToolLayer["工具层"]
        direction LR
        WRAPPER["AmapToolWrapper<br/>内部 3 层: MCP→Format→Validate<br/>（Agent 只看到 1 个 Tool）"]
        FALLBACK["FallbackTool<br/>API 全挂时兜底<br/>纯本地生成"]
    end

    subgraph MemoryLayer["记忆层"]
        MEMORY["MemoryManager<br/>五因子权重 + 双轨异常检测<br/>数值型 IQR + 分类型频率比<br/>trip_count ≥ 5 才显示画像"]
    end

    USER["POST /api/trip<br/>城市 + 天数 + 偏好"] --> PRE1 & PRE2
    PRE1 & PRE2 --> N1
    N1 --> N2 --> N3 --> N4 --> N5
    N5 --> USER

    N1 -.-> WRAPPER
    N2 -.-> WRAPPER
    N3 -.-> WRAPPER
    N4 -.-> MEMORY
    N5 -.-> MEMORY

    style APILayer fill:#d0ebff,stroke:#1c7ed6
```

---

## 图 2：LangGraph 状态机流转（5 Node）

> 城际交通 + 日期计算在 **API 层预处理**，不在 LangGraph 图中。
> 图从 `graph.invoke(state)` 开始，此时 State 已含所有预处理数据。
> Agent 内部的 Error-as-Observation（第 2 层）见图 6。

```mermaid
stateDiagram-v2
    [*] --> AttractionNode: graph.invoke(state)

    AttractionNode --> WeatherNode: 景点搜索完成
    note right of AttractionNode: 失败时 status="failed"<br/>写入 error_log（Annotated[list, add]）<br/>不抛异常，下游继续

    WeatherNode --> HotelNode: 天气查询完成
    note right of WeatherNode: 失败时跳过<br/>写入 error_log<br/>规划阶段给通用穿衣建议

    HotelNode --> MemoryNode: 酒店搜索完成
    note right of HotelNode: 失败时跳过<br/>写入 error_log<br/>规划按预算推荐通用住宿

    MemoryNode --> PlannerNode: 画像已注入 State
    note right of MemoryNode: 纯本地读取 MemoryManager<br/>trip_count ≥ 5 时画像有效<br/>不调 LLM / API

    PlannerNode --> [*]: 返回 TripPlan JSON
    note right of PlannerNode: 读 State 中各 status<br/>自动降级标注<br/>参考 user_profile 个性化<br/>前端展示 error_log 降级列表
```

---

## 图 3：请求数据流时序

```mermaid
sequenceDiagram
    participant User as 用户
    participant API as FastAPI（请求预处理）
    participant Graph as LangGraph
    participant Attr as 景点Node
    participant Wthr as 天气Node
    participant Hotel as 酒店Node
    participant Mem as 记忆Node
    participant Plan as 规划Node
    participant MCP as amap-mcp-server

    User->>API: POST /api/trip

    Note over API: 🔧 API 层预处理<br/>① Python 本地 date_list 计算<br/>② 城际交通（高德 API + fallback）<br/>③ 写入记忆 + trip_count++

    API->>Graph: graph.invoke(state)<br/>(含 date_list + intercity_*)

    Note over Graph: 串行流水线<br/>LangGraph Edge 控制流转

    Graph->>Attr: attraction_node(state)
    Attr->>MCP: maps_text_search(景点, 城市)
    MCP-->>Attr: JSON 景点数据
    Attr-->>Graph: state.attraction_data<br/>+ attraction_status<br/>+ error_log（失败时）

    Graph->>Wthr: weather_node(state)
    Wthr->>MCP: maps_weather(城市)
    MCP-->>Wthr: JSON 天气数据
    Wthr-->>Graph: state.weather_data<br/>+ weather_status<br/>+ error_log（失败时）

    Graph->>Hotel: hotel_node(state)
    Hotel->>MCP: maps_text_search(酒店, 城市)
    MCP-->>Hotel: JSON 酒店数据
    Hotel-->>Graph: state.hotel_data<br/>+ hotel_status<br/>+ error_log（失败时）

    Graph->>Mem: memory_node(state)
    Note over Mem: 从 data/memory.json<br/>加载用户画像<br/>trip_count ≥ 5 时有效<br/>（纯本地，不调API）
    Mem-->>Graph: state.user_profile

    Graph->>Plan: planner_node(state)
    Note over Plan: 整合: 景点+天气+酒店+画像<br/>降级标注: 根据 status<br/>个性化: 参考 user_profile<br/>城际交通: 从 State 读取

    alt 数据正常
        Plan-->>Graph: state.final_plan (完整行程)
    else 部分缺失
        Plan-->>Graph: state.final_plan (含降级标注)
    end

    Graph-->>API: 最终 state（含 error_log）
    API-->>User: 200 OK + TripPlan JSON<br/>(含 error_log 列表 + user_profile)
```

---

## 图 4：工具架构 — Wrapper 模式 + add_tool() 注册

```mermaid
flowchart LR
    subgraph External["外部服务"]
        AMAP["高德地图 API<br/>POI / 天气 / 路线"]
    end

    subgraph MCPLayer["MCP 远程层"]
        MCPSRV["amap-mcp-server<br/>uvx 启动子进程<br/>JSON-RPC over stdio<br/>16 个工具自动发现"]
    end

    subgraph WrapperLayer["AmapToolWrapper（1 个 Tool，3 层内部处理）"]
        direction TB
        L1["第 1 层: MCP 调用<br/>maps_text_search<br/>maps_weather"]
        L2["第 2 层: Format<br/>JSON→结构化文本<br/>纯 Python，不调 LLM"]
        L3["第 3 层: Validate<br/>完整性检查+默认值<br/>纯 Python"]
        L1 --> L2 --> L3
    end

    subgraph FallbackLayer["FallbackTool"]
        FB["所有 API 不可用时<br/>生成降级模板<br/>纯本地 JSON 生成"]
    end

    subgraph AgentLayer["Agent 层（add_tool() 注册）"]
        direction TB
        A1["景点 Agent<br/>SimpleAgent<br/>add_tool(mcp_tool)"]
        A2["天气 Agent<br/>SimpleAgent<br/>add_tool(mcp_tool)"]
        A3["酒店 Agent<br/>SimpleAgent<br/>add_tool(mcp_tool)"]
        A4["规划 Agent<br/>SimpleAgent<br/>（无工具，纯推理）"]
    end

    AMAP -->|"HTTP API"| MCPSRV
    MCPSRV -->|"共享 MCPTool 实例<br/>（只建一次连接）"| A1
    MCPSRV -->|"共享 MCPTool 实例"| A2
    MCPSRV -->|"共享 MCPTool 实例"| A3
    L3 -.->|"Wrapper 模式<br/>（可选封装）"| A1

    style WrapperLayer fill:#c3fae8,stroke:#0c8599
    style FallbackLayer fill:#fff3cd,stroke:#ffc107
    style AgentLayer fill:#b2f2bb,stroke:#2b8a3e
```

---

## 图 5：记忆模块 — 五因子权重 + 双轨异常检测

```mermaid
flowchart TB
    subgraph Input["输入"]
        DIALOG["对话内容 / 用户偏好"]
    end

    subgraph Step1["Step 1: 领域分类 × 标签提取"]
        direction LR
        C1["景点类 2x"] --- C2["酒店类 1.5x"] --- C3["偏好类 1.5x"] --- C4["天气类 1x"]
        T1["城市"] --- T2["价格区间"] --- T3["饮食"] --- T4["交通/出行/距离/节奏/住宿/预算/景点"]
    end

    subgraph Step2["Step 2: 五因子权重计算"]
        direction LR
        F1["① domain<br/>领域权重"] --- F2["② decay<br/>时间衰减"] --- F3["③ interaction<br/>交互修正"] --- F4["④ frequency_boost<br/>频率加成"] --- F5["⑤ outlier_penalty<br/>异常惩罚"]
    end

    FORMULA["最终权重 = domain × decay × interaction × frequency_boost × outlier_penalty"]

    subgraph Step3["Step 3: 双轨异常检测"]
        direction LR
        T1A["轨道1 数值型 IQR<br/>5次¥300-500 → 1次¥1500<br/>偏离Q3+2IQR → penalty=0.3"]
        T2A["轨道2 分类型 频率比<br/>5次不吃辣 → 1次爱吃辣<br/>频次<众数×0.3 → penalty=0.3"]
    end

    RESULT["画像保持: 经济型 + 不吃辣<br/>偶然行为不污染画像"]

    subgraph Step4["Step 4: 8维画像 + 持久化"]
        DIMS["出行方式 | 距离 | 住宿 | 预算 | 饮食 | 交通 | 节奏 | 兴趣"]
        GATE["trip_count ≥ 5 → 画像生效<br/>前端: 6维度标签 + 降级面板"]
        STORE["写入 data/memory.json"]
    end

    DIALOG --> Step1
    Step1 --> Step2
    Step2 --> FORMULA
    FORMULA --> Step3
    Step3 --> RESULT
    RESULT --> Step4
    DIMS --> GATE --> STORE

    style Step3 fill:#fff3cd,stroke:#ffc107
    style FORMULA fill:#d0bfff,stroke:#6741d9
```

---

## 图 6：错误恢复 — 两层协同 + error_log 累积

> **图级** Conditional Routing（第 4 层）→ 见图 2。节点间路由，读 status 决定下一跳。
> **Agent 级** Error-as-Observation（第 2 层）→ 本图。Agent 内部处理工具调用失败。
> **累积机制** error_log: Annotated[list, add] — LangGraph 自动合并所有 Node 的降级信息。

```mermaid
flowchart LR
    subgraph Bad["❌ 传统做法（抛异常）"]
        ERR["Tool 抛异常"]
        CRASH["Agent 崩溃"]
        USERERR["用户看到 500"]
        ERR --> CRASH --> USERERR
    end

    subgraph Good["✅ Error-as-Observation（第 2 层: Agent 内 ReAct）"]
        OBS["Tool 返回错误文本<br/>而非抛异常"]
        REACT["Agent 在 Observation 中<br/>读到错误描述"]
        RETRY["ReAct 循环决策:<br/>重试 / 换参数 / 降级"]
        DONE["返回结构化结果<br/>含缺失标注"]
        OBS --> REACT --> RETRY --> DONE
    end

    subgraph GraphLayer["并行: Node 降级 + error_log 累积（第 4 层: 图级）"]
        GFAIL["Node 返回 status='failed'<br/>写入 error_log"]
        GEDGE["Edge 线性流转<br/>下游 Node 继续执行"]
        ACCUM["error_log: Annotated[list, add]<br/>LangGraph 自动累积<br/>所有 Node 的降级信息"]
        API_RET["API 层返回<br/>error_log 列表 → 前端展示"]
        GFAIL --> GEDGE --> ACCUM --> API_RET
    end

    subgraph FallbackPanel["前端降级列表面板"]
        FP["6 维度标签<br/>+ 出行方式选择<br/>+ 降级列表展示<br/>（来自 error_log）"]
    end

    RETRY -.->|"重试成功"| DONE
    RETRY -.->|"多次失败"| FB["FallbackTool<br/>生成降级模板"]
    API_RET -.-> FP

    style ACCUM fill:#c3fae8,stroke:#0c8599
    style FallbackPanel fill:#fff3cd,stroke:#ffc107
```

---

## 图 7：架构分层映射 — 5 层定位

```mermaid
flowchart LR
    subgraph L5["第 5 层: 多智能体编排"]
        direction TB
        N5["TripPlanner LangGraph<br/>5 个 Node:<br/>attraction→weather→hotel<br/>→memory→planner"]
    end

    subgraph L4["第 4 层: 图编排框架"]
        direction TB
        N4["LangGraph StateGraph<br/>Node + Edge<br/>+ error_log Annotated[list, add]<br/>+ Checkpoint 持久化"]
    end

    subgraph L3["第 3 层: 框架封装"]
        direction TB
        N3["HelloAgents<br/>SimpleAgent / Tool / add_tool()"]
    end

    subgraph L2["第 2 层: Agent 内循环"]
        direction TB
        N2["ReAct while 循环<br/>Thought→Action→Observation<br/>Error-as-Observation 在此层"]
    end

    subgraph L1["第 1 层: 裸 LLM 调用"]
        direction TB
        N1["HelloAgentsLLM<br/>DeepSeek API"]
    end

    subgraph L0["第 0 层: API 预处理"]
        direction TB
        N0["FastAPI trip.py<br/>日期本地预计算<br/>城际交通计算<br/>记忆写入 + trip_count++"]
    end

    N1 --> N2 --> N3 --> N4 --> N5 --> N0

    style L5 fill:#ab47bc,color:#fff
    style L4 fill:#7b1fa2,color:#fff
    style L3 fill:#1976d2,color:#fff
    style L2 fill:#388e3c,color:#fff
    style L1 fill:#e57373,color:#fff
    style L0 fill:#f59f00,color:#fff
```

---

_定位: `/home/caoruixin/projects/tripplanner/ARCHITECTURE.md`_
_最后更新: 2026-07-20 — 与实际代码对齐_
