# TripPlanner 面试准备文档

> 策略：**不被动等提问，主动埋钩子引导面试官往你准备最充分的方向问。**

---

## 一、面试引导策略总览

### 核心原则

每次介绍一个技术点时，你主动说的内容中故意留一个"为什么"——面试官追问这个"为什么"时，恰好进入你的主场。

### 三层递进法

```
第一层：抛概念（你主动说）        → 面试官好奇，追问"为什么"
第二层：展开细节（你准备好的回答）  → 面试官认可，追问更深
第三层：工程取舍（你的 trade-off） → 面试官看到你的判断力
```

---

## 二、6 个钩子（按 Phase 排列）

### 钩子 1: LangGraph 编排（Phase 3）

**你主动说：**

> "我们的 4 个 Agent 是通过 LangGraph StateGraph 编排的——每个 Agent 是一个图节点，通过 Edge 定义流转顺序。LangGraph 的 Conditional Routing 和 Checkpoint 机制让我们在节点失败时自动降级，中断后还能从断点恢复。"

**埋的钩子：** "Conditional Routing"、"Checkpoint"、"从断点恢复"

**面试官大概率追问：** "为什么用 LangGraph 不用手写 ReAct？"

**你的回答（已准备）：**

> "手写 ReAct 的 while 循环适合单 Agent 的 Thought-Action-Observation。但 4 个 Agent 有明确上下游——这是多节点编排问题，不是单 Agent 推理问题。LangGraph 给了我们三样手写循环做不到的事：
>
> 第一，**声明式图定义**——加一个 Node 只需 add_node + add_edge，不改现有代码。Phase 6 加记忆模块时，我们只是加了一个 memory_node 和一条 edge。
>
> 第二，**Checkpoint 持久化**——每个 Node 执行后的 State 自动保存快照。如果服务器中断，相同 thread_id 重启后从断点继续，已完成的 Node 不重跑。这在长链路 Agent 中很关键——你不会希望景点搜索成功后因为天气查询超时就重搜一次景点。
>
> 第三，**条件边（Conditional Edge）**——我们定义了景点失败→跳过景点继续天气的路由规则，这和 Agent 内部的 Error-as-Observation 是两层独立的容错机制。"

**面试官可能追问：** "两层容错具体怎么区分的？"

> "图级做节点间路由——这个 Node 失败了，Edge 决定下一跳去哪。Agent 级做调用内决策——这次 MCP 调用超时了，Agent 自己是重试还是降级。两者的关键区别是：图级路由不消耗 LLM token（纯确定性逻辑），Agent 级降级需要 LLM 推理（语义理解）。"

---

### 钩子 2: MCP + 本地 Tool（Phase 1 & 4）

**你主动说：**

> "工具链分两层——MCP 协议调高德地图，本地 Tool 做数据格式化和校验。但设计上和常见的做法不同：我们没有把 FormatTool 和 ValidateTool 注册为独立 Tool，而是通过 AmapToolWrapper 包装——Agent 只看到一个 Tool，调一次拿到干净结果。"

**埋的钩子：** "不是独立 Tool"、"Wrapper 包装"、"调一次拿到干净结果"

**面试官大概率追问：** "为什么不写成独立 Tool？"

**你的回答（已准备）：**

> "如果 Format 和 Validate 是独立 Tool，Agent 需要用 3 轮 ReAct 调三个 Tool——先调 MCPTool 拿原始 JSON，再调 FormatTool 格式化，再调 ValidateTool 校验。这有两个问题：
>
> 第一，Agent（LLM）被迫理解数据处理流水线。它不该知道'调完 MCP 还要调 Format'——这是工程层面的细节，不应该占用 Agent 的推理步骤。
>
> 第二，LLM 上下文被挤占。MCP 返回的原始 JSON 可能上千字符，塞进 Planner Agent 的上下文中，和规划任务争夺 LLM 的注意力。
>
> 我们的 Wrapper 内部完成了 MCP 调用→格式化→校验三步。Format 和 Validate 是纯 Python 字符串处理——不调 LLM，不消耗 token，确定性输出。Agent 只调 amap_search 一个工具，拿到干净的结构化文本。"

**面试官可能追问：** "为什么不把 Format 也写成 MCP Server？"

> "MCP 适合有进程边界的场景——调外部 API、访问数据库。Format 是纯计算逻辑，写成 MCP Server 需要多一层进程间通信开销（JSON-RPC 序列化/反序列化），反而变慢了。我们的原则是：外部数据走 MCP，内部逻辑走本地。"

---

### 钩子 3: 记忆权重系统（Phase 6）

**你主动说：**

> "记忆模块不是简单的存/取。我们设计了五因子权重公式，包括频率加成和基于 IQR 的异常检测。这意味着用户的长期偏好会自动浮上来，偶然行为会被自动降权。"

**埋的钩子：** "五因子"、"IQR 异常检测"、"偶然行为降权"

**面试官大概率追问：** "异常检测怎么做的？能举个例子吗？"

**你的回答（已准备/重点展示）：**

> "举一个真实设计的案例——Alex。
>
> Alex 是一个经济型消费者，5 次出行都选了 300-500 元的经济型酒店。第 6 次他陪老板出差，选了一个 1500+ 元的豪华酒店。
>
> 传统记忆方案的问题：豪华酒店这条新记忆和旧记忆权重相同，会'污染'画像——系统开始以为 Alex 喜欢豪华酒店了。
>
> 我们的做法：对价格标签做统计分布分析。Alex 的 5 个历史价格中值都是 400，IQR 极窄。豪华酒店的价格中值 1750 远超 Q3 + 2×IQR 的上限——被检测为统计异常值。自动施加 outlier_penalty = 0.3，最终权重是经济型偏好的 1/5。
>
> 这意味着 Alex 的画像保持为'经济型'，偶然的豪华酒店不会永久改变偏好。只有这个行为反复出现（比如连续 3 次豪华酒店），统计学上不再异常，它才会进入画像。"

**面试官可能追问：** "五因子具体是什么？"

> "最终权重 = 领域权重 × 时间衰减 × 交互修正 × 频率加成 × 异常惩罚。
>
> 领域权重是系统预设——景点偏好比天气备注重要（2x vs 1x）。时间衰减用指数函数，约 14 天半衰。交互修正是用户反馈——主动修改的记忆权重高于被动观察的。频率加成让反复出现的行为获得更高置信度。异常惩罚就是我们刚讲的 IQR 方法。"

---

### 钩子 4: 架构层级（跨 Phase）

**你主动说：**

> "整个系统我们按 5 层架构设计。最底层是裸 LLM 调用，往上是 Agent 内 ReAct 循环，再往上是框架封装，再上是图编排，最上层是多智能体编排。每层有独立的职责和错误处理策略。"

**埋的钩子：** "5 层架构"、"每层独立的错误处理"

**面试官大概率追问：** "每层具体怎么分工的？"

**你的回答（已准备）：**

> "第 1 层是 HelloAgentsLLM——纯 API 封装，只管发 HTTP 请求拿回复。
>
> 第 2 层是 ReAct 循环——Agent 内部 Thought→Action→Observation 的决策循环。Error-as-Observation 在这一层：工具调用失败不抛异常，而是把错误文本返回给 Agent，让 Agent 自己决定重试还是降级。
>
> 第 3 层是 HelloAgents 框架——SimpleAgent、Tool、ToolRegistry。这一层把 LLM + Prompt + 工具注册封装成可复用的 Agent 抽象。
>
> 第 4 层是 LangGraph StateGraph——声明式图编排。Conditional Routing 在这一层：Edge 根据 State 中的 status 决定下一跳。Checkpoint 也在这一层：每步自动快照。
>
> 第 5 层是我们项目的 TripPlanner——5 个 Node 的具体编排逻辑，4 个 Agent + 记忆模块的图结构。
>
> 面试中最容易混淆的是第 2 层和第 4 层——它们都涉及错误处理，但第 2 层是 Agent 内部'调用失败了要不要重试'，第 4 层是'这个节点失败了下一跳去哪'。两层独立，各司其职。"

---

### 钩子 5: 数据流设计（Phase 5 + 3）

**你主动说：**

> "我们的 API 层和业务层完全解耦——FastAPI 只管 HTTP 序列化，Agent 系统只管业务逻辑。换编排引擎只需要改一行代码。"

**埋的钩子：** "完全解耦"、"只改一行代码"

**面试官大概率追问：** "怎么做到只改一行的？"

> "API 层和 Agent 层之间通过 Pydantic 模型约定接口。我们的 TripRequest 和 TripPlan 是纯数据模型，不包含任何编排逻辑。
>
> Phase 2 时，API 里调的是 `planner.plan_trip(city, days, prefs)`——顺序编排。
>
> Phase 3 改成 `graph.invoke(initial_state)`——LangGraph 编排。API 层只改了调用方式，路由、校验、CORS 配置全不用动。
>
> Phase 6 加记忆模块时，只是在 graph 里加了一个 memory_node 和一条 edge。API 层同样不需要改——因为 user_profile 字段本来就在 State 定义里，LangGraph 自动管理流转。"

---

### 钩子 6: 工程化（Phase 1 + 5）

**你主动说：**

> "项目从零搭建——venv 虚拟环境、pydantic-settings 配置管理、单例模式管理 MCPTool 和 LLM 连接。FastAPI 的 Swagger UI 自动生成交互式 API 文档，Pydantic 做请求参数的自动类型校验。"

**面试官可能追问：** "Pydantic 校验怎么工作的？"

> "比如 TripRequest 的 days 字段定义为 `int = Field(ge=1, le=14)`。如果有人发 `{"days": 0}`，FastAPI 不经业务代码直接返回 422——类型和范围校验都自动完成。不需要手写任何 `if days < 1` 的判断。"

---

## 三、演示脚本（5 分钟）

### 第一步：架构图（30 秒）

打开 ARCHITECTURE.md，展示图 7（5 层架构）。

> "这是我们的 5 层架构。我从最底层简单讲一下每层做什么——"

### 第二步：代码结构（30 秒）

```bash
tree backend/app -L 2
```

> "这是项目结构。agents/ 是 4 个 Agent，graph/ 是 LangGraph 编排，tools/ 是本地工具，memory/ 是记忆模块。"

### 第三步：Live Demo（3 分钟）

```bash
cd backend && source venv/bin/activate && python run.py
```

浏览器打开 http://localhost:8000/docs

1. 点 POST /api/trip → Try it out
2. 输入 `{"city": "北京", "days": 3, "preferences": ["历史文化"]}`
3. 展示返回的 JSON——城市、天数、景点、天气、预算

> "这个请求背后执行了 5 个 LangGraph Node——景点搜索、天气查询、酒店推荐、记忆加载、行程规划。每个 Node 的执行结果自动保存为 Checkpoint。"

### 第四步：异常恢复演示（1 分钟，如果有时间）

> "如果我模拟高德 API 不可用——"（展示 FallbackTool 生成的降级方案）

---

## 四、面试官按类型问的问题速答

### 如果面试官问"为什么选这些技术"

| 技术 | 你的回答核心 |
|------|------------|
| LangGraph | 声明式图编排 + Checkpoint + Conditional Routing，手写 while 也能串联但缺这三样 |
| MCP | 标准化工具协议，amap-mcp-server 一行 uvx 启动，16 个工具自动发现 |
| FastAPI | Pydantic 自动校验 + Swagger 自动生成，零样板代码 |
| DeepSeek | 已有 Key，性价比高 |

### 如果面试官问"你遇到什么难点"

1. **MCP 和 LLM 上下文窗口的冲突** → 引出 AmapToolWrapper
2. **用户画像被偶然行为污染** → 引出 Alex 案例 + IQR 异常检测
3. **MCPTool 返回的 JSON 带前缀无法直接解析** → 引出 `_extract_json_from_mcp_result()` 正则修复

### 如果面试官问"如果再给你一周，做什么"

1. **Conditional Edge 完善**：目前是 linear graph，加入真正的降级路由
2. **用户画像用向量检索**：当前是关键词匹配，升级为 embedding + 向量相似度
3. **多用户支持**：当前单用户记忆，加入用户隔离

---

## 五、常见陷阱问题

### 陷阱 1: "你这个不就是调 API 吗，AI 含量在哪？"

**不要回答** "我们用了 LangGraph 编排..."——这没回答 AI 含量的问题。

**正确回答：**

> "AI 含量在两个层面。第一，每个 Agent 内部的 ReAct 循环是 AI 自主决策——LLM 在每轮决定要不要调工具、调哪个工具、调完结果够不够。这不是写死的 if/else。
>
> 第二，Planner Agent 的推理是 AI 的核心——它拿到景点、天气、酒店三份数据后，需要理解它们之间的时空关系（景点之间的距离、天气对行程的影响），然后生成有逻辑的日程安排。这不是模板填充，是语义理解和推理。"

### 陷阱 2: "你用了 LangGraph，和 LangChain 什么关系？"

> "LangGraph 是 LangChain 生态里的图编排框架，但它不依赖 LangChain——可以独立使用。我们的 Agent 框架用的是 HelloAgents，不是 LangChain Agent。两者的协作方式是：HelloAgents 管 Agent 封装和工具调用（第 3 层），LangGraph 管多 Agent 编排和状态管理（第 4 层）。各取所长。"

### 陷阱 3: "记忆模块为什么不用向量数据库？"

> "当前阶段的需求是用户偏好画像——'不吃辣'、'预算 300-500'、'喜欢地铁'。这些是离散标签，不是语义检索问题。关键词匹配 + 统计加权足够。向量数据库更适合'相似记忆检索'场景——比如 '用户之前去杭州时喜欢什么类型的景点'。那是后续迭代方向，当前版本不需要。"

---

## 六、一句话总结（电梯演讲）

> "我做了一个多智能体旅行规划系统。4 个 Agent 通过 LangGraph 图编排，MCP 协议调高德地图 API。亮点是双层容错机制——图级条件路由和 Agent 级 Error-as-Observation 独立工作——以及基于 IQR 异常检测的记忆系统，保证用户的长期画像不被偶然行为破坏。"
