# TripPlanner 面试自我介绍与项目全景

> 面向 Agent 方向面试的项目讲解稿。面试官问"介绍一下你的项目"时，按这份稿子讲 5-10 分钟。追问的深入回答见 `docs/interview/qa.md`。
>
> **本文合并自：**
> - `项目详细介绍.md`（19 道题为框架的全景介绍，主叙事骨架）
> - `PROJECT.md` 一、项目总览段（技术栈与分层）
> - `项目方案书-修正版.md` 二、面试引导策略 / 七、面试应答模板（三层递进的钩子设计）
> - `plan/Phase7-面试文档.md` 6 个钩子（按 Phase 排列）
> - `面试问答.md` 项目介绍与自我介绍钩子（30 秒版）
>
> 基于 preview 分支代码实际（2026-07-26），所有设计决策均有代码对应。

---

## 一、30 秒电梯稿（面向不同面试官切换）

### 开场版（通用）

> "我做了一个多智能体旅行规划系统。你输入目的地和天数，自动排好完整行程——哪天去哪、怎么去、下雨要不要调整。不需要打开四个 App 手动拼凑。
>
> 越用越懂你：你选五次经济型酒店之后，不会因为偶尔陪老板住一次五星级就忘了你其实爱省钱。
>
> 核心假设是用户愿意为'省时间 + 更懂我'付费，下一步想验证这个。"

这段埋了四个钩子，每个后面都有对应回答：越用越懂你 → 五因子记忆，自动排好完整行程 → 编排容错，不需要手动拼凑 → Wrapper 设计，下雨要不要调整 → 多源数据整合。

### 技术面版（面试官是架构师/技术主管）

> "我们有三层竞争壁垒——
>
> 第一层，五因子记忆系统让偶然行为不污染长期偏好：五次经济型之后，一次奢华酒店不会改写画像。
>
> 第二层，双轨异常检测覆盖数值型和分类型数据：价格走 IQR 统计分布，饮食/交通走频率比，两套逻辑适用边界不同。
>
> 第三层，FallbackTool 做三级降级保障：任何一个数据源挂了都有兜底输出，用户始终能看到一份完整的行程。
>
> Wrapper 不是封装，是 token 成本优化——MCP 原始输出 800 字，我们格式化成 300 字传给 LLM，单个 Agent 调用省 60% token。"

### 产品面版（PM / 非技术主管）

直接用开场版即可，强调用户价值和核心假设，引导对方追问"怎么做到越用越懂你"和"为什么愿意付费"。

---

## 二、项目定位：面向谁、解决什么问题

TripPlanner 是一个多智能体旅行规划系统。目标用户分两类：B 端中小旅行社需要自动化行程编排引擎来提效，C 端高频差旅用户需要跨平台多源数据自动整合和个性化偏好记忆。

**解决的核心问题**：传统旅行规划需要用户手动在携程、天气 App、Booking 之间切换拼凑信息——查景点、看天气、比酒店、算交通，四步下来至少要开四个 App。TripPlanner 把四个步骤封装进一条请求：输入城市和天数，后端四个 Agent 自动完成景点搜索、天气查询、酒店推荐、行程规划，输出一份完整的结构化行程 JSON。

**与携程等 OTA 平台的本质区别**：携程是货架——告诉你有什么可选的；TripPlanner 是规划师——帮你排顺序、做决策。携程的目标是卖票，TripPlanner 的目标是做决策辅助。这不是替代关系，是补充关系：用户先在 TripPlanner 确定行程框架，再去携程完成预订。

**产品差异化**：跨会话记忆是最核心的壁垒。用户在 TripPlanner 上使用五次经济型酒店之后，系统不会因为某一次陪老板住了五星级就忘了他其实爱省钱——五因子权重公式让长期偏好浮上来，双轨异常检测让偶然行为沉下去。这是携程"每次搜索从零开始"做不到的。

---

## 三、一句话技术总览

4 个 Node 的 LangGraph 图编排 + MCP 协议调高德地图 + API 层天气/城际交通预处理 + 双轨异常检测画像，零人工介入完成"输入城市→输出个性化多城行程"。

### 技术栈

| 组件 | 选型 | 定位 |
|------|------|------|
| 编排引擎 | LangGraph StateGraph | 第 4-5 层：图编排 + 多智能体 |
| Agent 框架 | HelloAgents SimpleAgent | 第 3 层：ReAct 循环封装 |
| 工具协议 | MCP (amap-mcp-server) | 远程工具标准化，16 个高德工具 |
| LLM | DeepSeek (via HelloAgentsLLM) | 第 1 层：裸 API 调用 |
| Web 框架 | FastAPI + Pydantic | REST API + 类型校验 |
| 记忆 | 自定义五因子权重模块 | 用户画像持久化 |
| 前端 | Vue 3 单文件 | 6 维度标签 + 降级面板 + 画像雷达图 |

### 架构分层（6 层）

```
第 6 层  API 层预处理       ← 天气 _fetch_weather() + 城际交通 _compute_intercity() + 日期 _compute_dates()
第 5 层  多智能体编排       ← TripPlanner LangGraph（4 Node，仅市内数据 + Conditional Edge）
第 4 层  图编排框架         ← LangGraph StateGraph（Node/Edge/Conditional/Checkpoint）
第 3 层  框架封装           ← HelloAgents SimpleAgent/ToolRegistry
第 2 层  Agent 内循环       ← ReAct（Error-as-Observation 在此层）
第 1 层  裸 LLM 调用        ← HelloAgentsLLM.invoke()
```

---

## 四、主业务流程：一次请求的完整旅程

### 前端交互

用户打开 Vue 3 单页应用，填写：

- 目的地城市（如"成都"）
- 出发城市（如"上海"）
- 出行天数（如 3 天）
- 出行方式（高铁/飞机/自驾）
- 偏好标签（多维度可选）：景点类型（自然风光/历史文化）、饮食口味（不吃辣/爱吃辣）、交通方式（地铁优先/打车优先）、行程节奏（紧凑高效/悠闲慢游）、住宿档次（经济型/舒适型/豪华型）、预算范围

前端默认日期根据浏览器本地时区自动填充当天日期（之前踩过 UTC 时区的坑，已改用 `getFullYear/getMonth/getDate` 取本地时间）。

提交后，进度条从 0% 逐步推进到 70%（4 步 × 4 秒定时器动画），同时显示流动文案："搜索景点中 → 搜索酒店中 → 加载画像中 → 生成行程中"。POST 请求完成后直接跳到 100% 渲染结果。

### API 层预处理

后端 FastAPI 收到 POST 请求。在进入 LangGraph 图编排之前，先做三项不消耗 LLM token 的确定性计算：

- **日期计算**：纯 Python，根据 `start_date` 和 `days` 算出每天的日期列表。不需要 LLM 参与——这是小学数学。
- **天气查询**：直接调高德 `maps_weather` API，拿到目的地未来一周的天气预报。失败时写通用降级文本（"春秋季带外套，夏季防晒，冬季穿厚外套"）——不抛异常，不阻断后续流程。
- **城际交通计算**：调 `maps_geo` 分别拿到出发城市和目的地城市的中心坐标，算直线距离；根据距离自动判断推荐交通方式（<300km 高铁，≥300km 高铁为主、>1200km 可选飞机）；静态字典估算时间和费用（高铁 300km/h 0.5 元/km，飞机 800km/h 0.8 元/km）；失败时用静态字典 `_FALLBACK_DISTANCES` 兜底。

三项结果打包进 State：`date_list`, `weather_data`, `intercity_distance_km`, `intercity_duration_h`, `intercity_cost`, `transport_mode`。

**并发优化（2026-07-26 落地）**：`_fetch_weather` 与 `_compute_intercity` 是两条独立任务（不依赖彼此的输出），用 `ThreadPoolExecutor` 同时提交，预处理耗时从 `t1 + t2` 变成 `max(t1, t2)`；`_compute_intercity` 内部的 origin/destination 两次 `maps_geo` 也并行提交，省一次 MCP round-trip（~200-500ms）。无需应用层锁——`MCPTool.run()` 每次调用内部新建独立 event loop + MCPClient 连接，无共享 mutable state。

### LangGraph 四节点流水线

图结构（`START → [attraction, memory] → hotel → planner → [conditional: retry_planner / retry_hotel / done] → END`）体现了 fan-out / join 拓扑：`memory` 是纯本地 JSON 读，与 `attraction` 的 LLM+MCP 长任务并行不阻塞；`planner` 自动等 `hotel` 和 `memory` 都到达。

每个 Node 在 LangGraph 中是一个 Python 函数，签名是 `(state) -> partial_dict`。Node 执行完毕后，LangGraph 自动将 `partial_dict` merge 进全局 State，下游 Node 直接读取。这就是图编排和传统函数调用的核心区别：Node 之间零耦合——加、减、改 Node 不破坏上下游。

**为什么选择 multi-agent 而非普通后端工作流？** 因为四个环节需要不同的 prompt 模板和不同的工具链。景点 Agent 需要 `maps_around` 搜景点 + `maps_geo` 补坐标，酒店 Agent 需要根据景点质心动态切换搜索策略（有质心走 `maps_around` 周边搜索，无质心退化为 `maps_text_search` 全城搜索），Planner 是纯推理不需要工具。传统 if-else 工作流无法处理"搜到景点后根据空间分布自适应调整酒店搜索中心"这种需要上下文理解的动态编排。

#### Node 1: 景点搜索（attraction_node）

Agent 拿到系统 prompt + 用户 prompt，进入 ReAct 循环：

```
Thought: 需要先拿到城市中心坐标
Action: 调 amap_search(city=成都, type=attraction, keywords=景点)
Observation: Wrapper 内部: maps_geo(成都) → 中心坐标(104.07,30.67)
             → maps_around(center, radius=20000) → 20 个景点 POI
             → ThreadPool 并发 maps_geo 给每个 POI 补 lng/lat
             → Format: 原始 800 字 → 300 字干净文本
             → Validate: 至少有一个 POI
Result: 【景点搜索结果】
        1. 宽窄巷子 | 青羊区 | (104.058,30.672)
        2. 锦里古街 | 武侯区 | (104.047,30.648)
        ...
```

Node 函数拿到 Agent 返回的文本后，本地正则提取所有 `(lng,lat)` 坐标，计算景点群地理质心：

```python
clng = sum(p["lng"] for p in coords) / len(coords)
clat = sum(p["lat"] for p in coords) / len(coords)
```

质心写入 State 的 `center_lng` 和 `center_lat`，景点坐标列表写入 `attraction_coords`。Agent 全文写入 `attraction_data`——Planner 需要原文做语义理解，也需要坐标做空间校验。

**ReAct 实践细节**：每个 Agent 的 ReAct 循环是 HelloAgents SimpleAgent 框架提供的，但 prompt 设计是我们自己写的。要点是：在 prompt 里明确告诉 Agent 每一步应该产生 Thought 再 Action，Observation 是工具返回结果，最终输出 Final Answer。景点 Agent 的典型 ReAct 轨迹是 2-3 轮：第一轮 Thought→调 maps_geo 拿中心，第二轮 Thought→调 maps_around 搜景点，第三轮整合输出。ToT（思维树）在这个项目中没有使用——流水线式任务天然是串行依赖，分支探索没有收益，反而增加 token 消耗和不确定性。

#### Node 2: 酒店推荐（hotel_node）

酒店的搜索策略由上游数据决定：

- **有景点质心**：`maps_around(center_lng, center_lat, radius=5000)`，在景点群周边 5 公里范围内搜酒店
- **无质心**（景点搜索失败或质心计算失败）：退化为 `maps_text_search(city, keywords=酒店)` 全城搜索
- **有 center_override**（Planner 离群检测后重新计算了质心）：用新质心再次 `maps_around`

同样走 Wrapper 的并发 geo 增强 + Format + Validate 流水线。

#### Node 3: 记忆加载（memory_node）

纯本地 IO，不调 LLM。从 `data/memory.json`（或 SQLite）读取用户画像。核心数据结构：

```python
{
  "user_id": "default",
  "trip_count": 7,
  "tags": {
    "住宿:经济型": {"weight": 0.92, "count": 6},
    "饮食:不吃辣": {"weight": 0.88, "count": 5},
    "交通:地铁优先": {"weight": 0.75, "count": 4},
    ...
  }
}
```

`trip_count >= 5` 时画像生效——前端显示完整画像面板。不够 5 次时画像为空，Planner 不注入任何偏好约束，纯按默认逻辑生成行程。这个阈值的目的是避免小样本误判：两次出行选经济型不代表用户"偏好经济型"，可能只是碰巧。

**为什么 memory 是独立 Node？** 不是因为读取 JSON 文件需要独立节点（这确实是过度设计）。保留独立节点是为了后续多用户场景下的架构灵活性——独立节点可以独立演进，后续换成向量检索、加 Redis 缓存、接消息队列异步更新，都不需要改 Planner Node 的代码。

#### Node 4: 行程规划（planner_node）

Planner 是**无工具纯推理 Agent**——它唯一的职责是把上游四个数据源整合成一份可执行的行程。

Prompt 设计是关键。不是简单的"请规划一个行程"，而是结构化注入：

```
【城市】成都 【日期】2026-07-21 至 2026-07-23 【天数】3

【景点】
1. 宽窄巷子 | (104.058,30.672)
2. 锦里古街 | (104.047,30.648)
3. 文殊院 | (104.071,30.682)

【可选酒店】{hotel_data}

【天气】
07-21: 多云转阴 32°C~25°C
07-22: 阵雨 28°C~23°C
07-23: 多云 30°C~24°C

【城际交通】高铁 1936km 约7h ¥968

【用户画像】（trip_count=7 时注入）
- 住宿偏好: 经济型
- 饮食习惯: 不吃辣
- 交通方式: 地铁优先
⚠️ 用户偏好经济型，预算控制 < 500 元/天
⚠️ 用户不吃辣，避免川菜馆

【输出格式】
{
  "city": "", "start_date": "", "days": [
    {"date": "", "attractions": [{"name":"","description":""}],
     "hotel": {"name":"","address":""},"meals":[...]}
  ],
  "budget": {"total":0,"total_attractions":0,"total_hotels":0,"total_meals":0,"total_transportation":0},
  "weather_info": [...], "overall_suggestions": ""
}
```

画像指令注入是区分"信息告诉 LLM"和"约束指令强加 LLM"的关键。前端面板"标签"仅作为信息展示，真正影响输出的是 prompt 里强制约束的那一段——这是产品设计决策：用户偏好应该影响输出，但用户应该能看到系统在哪用了他的偏好。

### 校验与回环

Planner 生成后不直接返回。先过本地校验函数 `_validate_and_refine()`。这里体现了"让 LLM 负责创造性输出，让规则引擎负责正确性检查"的核心原则——LLM 擅长生成行程，但不擅长判断自己生成的对不对。校验分三层：

| 检测类型 | 检查内容 | 判定 | 动作 |
|---------|---------|------|------|
| **硬伤** | 每天景点 < 2 个 | 结构性错误 | `retry_planner` 自回环重新生成，最多 3 次 |
| **硬伤** | 预算超用户偏好 30% | 违反用户约束 | `retry_planner` |
| **硬伤** | 缺少必填字段（hotel, attractions 等） | JSON 结构不完整 | `retry_planner` |
| **软伤** | 酒店到最远景点直线距离 > 10km | 合理性存疑 | 写 `error_log`，不阻断 |
| **软伤** | 暴雨天安排了户外景点 | 天气冲突 | 写 `error_log`，不阻断 |
| **离群** | 某景点到质心 > `mean + 1.5σ` | 空间分布异常 | 排除该景点 → 重算质心 → `retry_hotel`，≤2 次 |
| **离群** | 某景点到质心 > 80km（硬上限） | 物理上不能作为城市景点 | 直接排除 → `retry_hotel` |

**离群检测算法选择：为什么用标准差法 + 80km 硬上限？**

固定阈值（如 10km）无法适用于不同规模城市——北京城区跨度 50km，成都城区跨度 15km。标准差法自适应城市分布：北京 sigma 大，阈值自动放宽；成都 sigma 小，阈值自动收紧。`OUTLIER_SIGMA = 1.5` 而非 2 是因为小样本场景（n ≤ 15 个景点）下，1.5σ 更敏感——宁多标再校验，也不要漏检导致酒店跑到城郊。

80km 硬上限是兜底——标准差法在极端场景下会失效：如果高德返回了整个重庆市域（8 万 km²）的 POI，sigma 会被两峰之间距离撑得非常大，阈值过宽导致真正的离群点漏检。80km 是物理判断：任何景点距离质心超过 80 公里，就不是"城市一日游"能覆盖的范围了。后续可换 MAD（Median Absolute Deviation）或 DBSCAN 聚类做更稳健的离群检测。

**重试上限防止死循环**：`MAX_RETRY = 3`（Planner 自回环）和 `MAX_HOTEL_RETRY = 2`（酒店回环）是之前在测试中踩出的经验——没有上限时，重庆场景下离群检测反复触发，Planner 无限回到酒店 Node，最终进程 OOM 被系统杀掉。

**错误信息全链路累积**：`error_log` 使用 `Annotated[list[str], add]` 声明，LangGraph 自动累积而非覆盖。每个 Node 都可以往 error_log 里追加，Planner 校验也能追加。最终所有 warnings 在前端降级面板透明展示——这是产品决策：比起悄悄降级假装一切正常，告诉用户"天气数据暂时不可用，用了通用穿衣建议"更能建立信任感。

---

## 五、记忆系统：跨会话持续学习

记忆是 TripPlanner 最核心的技术壁垒——不是"存了用户喜欢什么"，而是"区分用户真正喜欢什么和偶然做了什么"。

### 五因子权重公式

`final_weight = domain_weight × time_decay × interaction × frequency_boost × outlier_penalty`

- **domain_weight**：领域先验，不同类型的偏好有不同的稳定度。"住宿档次"天然比"景点类型"更稳定（人不会频繁换酒店档次，但经常换景点口味）
- **time_decay**：指数衰减 `e^(-λt)`，确保最近的行为权重更高
- **interaction**：操作类型修正。"选了酒店并确认预订" vs "只是点了看看"，交互深度不同
- **frequency_boost**：高频行为加乘，连续 5 次经济型 → 高置信度 → 权重提升
- **outlier_penalty**：异常行为惩罚，乘法公式确保单次异常可以压倒性地被压制（penalty=0.3 直接让这次行为的权重砍掉 70%），加法做不到

**为什么是乘法不是加权求和？** 加权求和 `Σwi·fi` 的优势是可解释、每个因子独立贡献、不会因单个因子极端归零。乘法的优势是"一票否决"语义——异常惩罚能彻底压住偶然行为。在这个场景下，我们更在意"不让偶然行为污染长期偏好"而非"每个因子的贡献都可独立解释"。面试时可补充：本质是一个对数线性模型 `log weight = Σ log f_i`，等价于对每个因子做 additive smoothing。

### 双轨异常检测

| 检测器 | 适用数据 | 方法 | 示例 |
|--------|---------|------|------|
| IQR 检测器 | 数值型：酒店价格、预算、距离 | Q1 - 1.5×IQR 和 Q3 + 1.5×IQR 为离群 | 5 次酒店均价 200-300 元，突然一次 2000 元 → outlier_penalty = 0.3 |
| 频率比检测器 | 分类型：饮食、交通、住宿档次 | 新标签频次 < 众数频次 × 30% → 标记异常 | 5 次"不吃辣"后 1 次"爱吃辣" → penalty = 0.3 |

**两轨独立，各管各的维度。** IQR 不碰分类型数据（"不吃辣"没法算四分位数），频率比不碰数值型数据（价格分布不能只看频次）。互不干扰，互不矛盾。

### 渐进构建

`trip_count < 5` 时画像不生效——前端显示"正在构建画像 X/5"，Planner 不加任何偏好约束。这是产品思维而非技术需要：技术上 1 次出行就够打标签，但 1 次数据量太小，误判概率高。宁可慢一点准一点，也不要快速出错误画像然后让用户觉得系统不懂他。

### 记忆去重

之前踩过一个坑：设置 `interrupt` 修复的验证过程中发现，如果请求因网络超时重试，`memory.add()` 会被重复调用，导致同一条"目的地: 北京"被写入多次。修复方案：`add()` 方法在写入前对比最近一条 entry 的 `action` 和 `context` 字段，完全相同则直接返回已有对象，跳过写入。三行代码解决幂等性问题。

---

## 六、容错设计：全链路不崩溃

容错不是某一块代码，而是贯穿整个系统从 API 入口到前端渲染的体系。设计原则：每一层都在自己的范围内处理异常，处理不了的才上浮。

### 三层降级

| 层级 | 位置 | 策略 | 示例 |
|------|------|------|------|
| L1 数据源级 | API 层 `_fetch_weather()` `_compute_intercity()` | 元数据自动切换 | 天气 API 挂了 → 返回通用穿衣建议文本；城际 API 挂了 → 静态字典兜底 |
| L2 Agent 级 | 每个 Node 的 `try/except` | Error-as-Observation | 景点搜索失败 → 写 `attraction_status: "failed"` + `error_log` → 下游打印 warning 但继续执行 |
| L3 全链路 Fallback | `FallbackTool` | 本地模板兜底 | 三个 Agent 全挂 → 返回一个包含通用提示的行程 JSON——"请到达成都后咨询当地旅游中心" |

### Interrupt 六大防护

| 能力 | 实现位置 | 价值 |
|------|---------|------|
| thread_id 断点续传 | `trip.py` graph.invoke(state, config) | 相同请求重试时跳过已完成的 Node |
| LLM 指数退避 | `trip_planner_agent.py` _run_agent_with_retry() | DeepSeek 429 限流时 1s→2s→4s 自动重试 |
| MCP 超时 | `amap_wrapper.py` _mcp_run_with_timeout(10s) | 高德 API 卡住时 10s 后返回空数据，不阻塞 |
| 记忆去重 | `memory/manager.py` add() | 中断重试不会产生重复记忆记录 |
| SSE 取消传播 | `trip.py` cancel_event | 用户关闭页面后后台线程感知取消 |
| SQLite Checkpoint | `builder.py` SqliteSaver | 进程重启后从最后一个成功 Node 恢复 |

六项改动总量 ~200 行，零删除已有代码，不破坏任何 Node 逻辑。

设计原则：**先防崩溃（thread_id + SqliteSaver），再省资源（cancel 传播 + retry 退避），最后去噪音（记忆去重）**。三步递进，都是纯增量。

### Conditional Edge 重试上限

```
planner_node → 校验
  ├─ 硬伤 → retry_planner (≤3次) → planner_node
  ├─ 离群 → retry_hotel (≤2次) → hotel_node
  └─ 通过 → done → END
```

重试耗尽后强制 `done`——不再循环，带上所有 warning 输出。防止死锁，防止资源浪费。

### 并发优化（2026-07-26 新增）

三处独立任务从串行改并行，无需应用层锁——`MCPTool.run()` 每次调用内部新建独立 event loop + MCPClient 连接，无共享 mutable state；`error_log` 由 `Annotated[list[str], add]` reducer 合并。

- **API 预处理并行**（`app/api/trip.py`）：`_compute_intercity` ∥ `_fetch_weather` 用 `ThreadPoolExecutor` 同时提交；`/api/trip` 与 `/api/trip/stream` 两个端点一致改造
- **maps_geo 双查并行**（`app/api/trip.py`）：`_compute_intercity` 内 origin/destination 地理编码同时提交，节省一次 MCP round-trip
- **LangGraph 拓扑 fan-out**（`app/graph/builder.py`）：`START → [attraction, memory]` 并行入口 + planner 双入边 join。memory 是纯本地 JSON 读，与 attraction 的 LLM+MCP 长任务并行不阻塞；planner 自动等 hotel + memory 都到达

端到端验证（上海→杭州 2 天）：`graph.invoke` 76.6s，final_plan 完整，`user_profile 加载: True` 直接证明 memory 边执行到位。

---

## 七、系统边界：什么放哪、为什么不放别处

### API 层 vs 图内 Node

| 放 API 层（预处理） | 放图内（Agent 编排） |
|-------------------|---------------------|
| **日期计算**：纯 Python 算日期列表 | **景点搜索**：需要语义判断"搜索半径""偏好关键词" |
| **天气查询**：单次 API 调用，纯数据拉取 | **酒店推荐**：需要根据景点质心动态选搜索策略 |
| **城际交通**：静态字典 + 距离运算 | **行程规划**：多源数据整合 + 输出生成 |
| **坐标增强**：并发 maps_geo 补经纬度（Wrapper 内） | **记忆加载**：IO 但独立节点，保留扩展性 |

**核心原则：确定性工程计算放 API 层，需要 LLM 语义理解或 Agent 决策的才进图。**

天气是纯查询——不需要 Checkpoint、不需要 Agent 推理、不需要 LLM。失败时直接在 API 层写降级文本，不消耗 ReAct 轮次，不等 LLM 超时。城际交通同理——经纬度→距离→推荐交通方式，纯算术，不需要"理解"。

坐标增强放在 Wrapper 内而非 Node 内或 API 层，是因为它是 Agent 产出的自然延伸——景点搜到地址后需要补坐标，这不是"额外的预处理"，是"搜索结果的数据增强"。放 Wrapper 内部，Agent 无感知，Node 逻辑干净。

### Wrapper 模式的架构价值

Wrapper 不是简单的封装，是一个**架构决策**：

1. **Token 成本优化**：MCP 原始返回是 800 字的嵌套 JSON，Format 层纯 Python 提取关键字段（name, address, location）压缩到 300 字再传给 LLM——每次工具调用省 60% token。如果 4 个 Agent 各调 2-3 次工具，单次请求省数千 token
2. **确定性处理**：Format 和 Validate 是纯 Python，不走 LLM。不需要 Agent 理解 JSON 结构——降低幻觉风险
3. **条件路由**：同一个 `amap_search` 工具名，内部根据 `type` 参数走不同路径（attraction→geo+around, hotel→geo+around, weather→直接返回, around→直接 around）

---

## 八、关键设计决策与踩坑记录

### 决策 1：离群检测从固定倍数改为标准差法

**初始设计**：`distance > avg_distance * 2.0` → 标记离群。

**问题**：北京景点平均距离 30km，×2 就是 60km 阈值，八达岭（70km）刚好漏过。成都平均距离 5km，×2 就是 10km，基本标记不到任何东西。用同一套规则在不同城市效果完全不同。

**最终方案**：`mean + 1.5 * sigma` + 80km 硬上限。自适应城市规模，极端场景有兜底。

### 决策 2：天气从图内 Node 移到 API 层

**初始设计**：天气是一个独立的 LangGraph Node，在景点和酒店之间执行。

**问题**：天气只需要城市名，不依赖任何 Agent 数据，也不需要 Checkpoint。作为一个图 Node 过度设计——多了一次 State 读写、多了一个 Checkpoint 快照、多了一份 LLM prompt 复杂度。

**移后效果**：图从 5 Node 精简到 4 Node。天气在 API 层失败时直接降级，不等 LLM。

### 决策 3：前端动画用定时器模拟而非 SSE 流式

**初始设计**：SSE（Server-Sent Events）从后端逐 Node 推送进度事件到前端，实现真实进度。

**问题**：uvicorn 单线程模型下 SSE 连接和同步 graph.invoke() 有竞态——曲线请求时 SSE 端点返回"Invalid HTTP request"。调试时间成本高。

**最终方案**：POST 轮询 + 定时器模拟进度（4 步 × 4 秒）。虽然没有真实进度，但可靠性高、代码简单、效果接近。面试时主动提这个取舍——比假装 SSE 一直好用更诚实。

### 踩坑 1：Wrapper 写了但 Agent 没接入

Wrapper 的坐标增强功能写了一个月，测试发现 `center_lng` 永远是 `None`。排查发现 Agent 注册的是原始 MCPTool 而不是 Wrapper——Agent 直接调 MCP 拿原始 JSON，根本没有触发 geo 增强。一行 import 修复，教训是组件多了之后集成测试不能省。

### 踩坑 2：离群检测死循环

重庆场景下，景点分散在 8 万平方公里的市域范围内。离群检测每次找到同一个离群点，中心每次都算到同一个值，Planner 无限回到酒店 Node。加了 `MAX_HOTEL_RETRY = 2` 上限才终止。如果没有重试上限，这会在生产环境造成资源泄漏。

---

## 九、面试引导策略（三层递进，主动埋钩子）

不被动等提问，主动埋钩子引导面试官往你准备最充分的方向问。每次介绍一个技术点时，主动说的内容中故意留一个"为什么"——面试官追问这个"为什么"时，恰好进入你的主场。

```
第一层：抛概念（你主动说）        → 面试官好奇，追问"为什么"
第二层：展开细节（你准备好的回答）  → 面试官认可，追问更深
第三层：工程取舍（你的 trade-off） → 面试官看到你的判断力
```

### 6 个核心钩子（按 Phase 排列）

#### 钩子 1: LangGraph 编排

**你主动说**：

> "我们的 4 个 Agent 是通过 LangGraph StateGraph 编排的——每个 Agent 是一个图节点，通过 Edge 定义流转顺序。LangGraph 的 Conditional Routing 和 Checkpoint 机制让我们在节点失败时自动降级，中断后还能从断点恢复。"

**埋的钩子**："Conditional Routing"、"Checkpoint"、"从断点恢复"。面试官大概率追问"为什么用 LangGraph 不用手写 ReAct？"——详细回答见 qa.md。

#### 钩子 2: MCP + 本地 Tool

**你主动说**：

> "工具链分两层——MCP 协议调高德地图，本地 Tool 做数据格式化和校验。但设计上和常见的做法不同：我们没有把 FormatTool 和 ValidateTool 注册为独立 Tool，而是通过 AmapToolWrapper 包装——Agent 只看到一个 Tool，调一次拿到干净结果。"

**埋的钩子**："不是独立 Tool"、"Wrapper 包装"、"调一次拿到干净结果"。追问方向是"为什么不写成独立 Tool？"和"为什么不把 Format 也写成 MCP Server？"。

#### 钩子 3: 记忆权重系统

**你主动说**：

> "记忆模块不是简单的存/取。我们设计了五因子权重公式，包括频率加成和基于 IQR 的异常检测。这意味着用户的长期偏好会自动浮上来，偶然行为会被自动降权。"

**埋的钩子**："五因子"、"IQR 异常检测"、"偶然行为降权"。追问"能举个例子吗？"→ Alex 案例。

#### 钩子 4: 架构层级

**你主动说**：

> "整个系统我们按 6 层架构设计（含 API 预处理层）。最底层是裸 LLM 调用，往上是 Agent 内 ReAct 循环，再往上是框架封装，再上是图编排，再上是多智能体编排，最顶层是 API 预处理。每层有独立的职责和错误处理策略。"

**埋的钩子**："6 层架构"、"每层独立的错误处理"。追问"图级 Conditional Routing 和 Agent 级 Error-as-Observation 的区别"是这个方向的核心。

#### 钩子 5: 数据流设计

**你主动说**：

> "我们的 API 层和业务层完全解耦——FastAPI 只管 HTTP 序列化和确定性预处理，Agent 系统只管业务逻辑。换编排引擎只需要改一行代码——`graph.invoke(initial_state)` 换成任何等价接口即可。"

**埋的钩子**："完全解耦"、"只改一行代码"。

#### 钩子 6: 工程化

**你主动说**：

> "项目从零搭建——venv 虚拟环境、pydantic-settings 配置管理、单例模式管理 MCPTool 和 LLM 连接。FastAPI 的 Swagger UI 自动生成交互式 API 文档，Pydantic 做请求参数的自动类型校验。"

追问"Pydantic 校验怎么工作的？"→ 举 TripRequest 的 days 字段 `int = Field(ge=1, le=14)` 的例子。

### 常见陷阱问题的应答（面试官试探性提问）

**陷阱 1**："你这个不就是调 API 吗，AI 含量在哪？"

**不要回答** "我们用了 LangGraph 编排..."——这没回答 AI 含量的问题。

**正确回答**：

> "AI 含量在两个层面。第一，每个 Agent 内部的 ReAct 循环是 AI 自主决策——LLM 在每轮决定要不要调工具、调哪个工具、调完结果够不够。这不是写死的 if/else。
>
> 第二，Planner Agent 的推理是 AI 的核心——它拿到景点、天气、酒店三份数据后，需要理解它们之间的时空关系（景点之间的距离、天气对行程的影响），然后生成有逻辑的日程安排。这不是模板填充，是语义理解和推理。"

**陷阱 2**："你用了 LangGraph，和 LangChain 什么关系？"

> "LangGraph 是 LangChain 生态里的图编排框架，但它不依赖 LangChain——可以独立使用。我们的 Agent 框架用的是 HelloAgents，不是 LangChain Agent。两者的协作方式是：HelloAgents 管 Agent 封装和工具调用（第 3 层），LangGraph 管多 Agent 编排和状态管理（第 4 层）。各取所长。"

**陷阱 3**："记忆模块为什么不用向量数据库？"

> "当前阶段的需求是用户偏好画像——'不吃辣'、'预算 300-500'、'喜欢地铁'。这些是离散标签，不是语义检索问题。关键词匹配 + 统计加权足够。向量数据库更适合'相似记忆检索'场景——比如'用户之前去杭州时喜欢什么类型的景点'。那是后续迭代方向，当前版本不需要。"

### 一句话总结（电梯演讲收尾）

> "多智能体旅行规划系统，4 个 Agent 通过 LangGraph 图编排，MCP 协议调高德地图 API。亮点是双层容错机制——图级条件路由和 Agent 级 Error-as-Observation 独立工作——以及基于 IQR + 频率比双轨异常检测的记忆系统，保证用户的长期画像不被偶然行为破坏。"

---

## 十、可观测性与监控

当前项目的可观测性是粗粒度的——`error_log` 累积 + 前端降级面板。生产级需要以下维度：

**通用指标（RED）：**
- Rate：QPS、每分钟请求量
- Errors：HTTP 5xx、LLM 调用失败率、MCP 超时率
- Duration：P50/P95/P99 端到端延迟、每个 Node 的耗时分布

**AI 特有指标：**
- Token 消耗：每次请求的 total tokens、每个 Agent 的 token 分布
- ReAct 轮次：每个 Agent 走了几轮 Thought→Action→Observation
- LLM 成功率：一次请求可能包含 4-6 次 LLM 调用，任一失败需记录
- 降级触发率：L1/L2/L3 各层级的降级频次
- 重试分布：Planner 自回环次数分布、酒店回环次数分布

**实现路径**：先在 Node 的 `_emit` 回调里加耗时记录，再接到 Prometheus Counter/Histogram。不追求一步到位，按"先看清瓶颈、再针对性优化"渐进推进。

---

## 十一、持续学习：不依赖频繁重训

Agent 的持续学习不是模型微调，而是**记忆更新**。每次行程生成后：

1. 用户确认的行程中的偏好标签（景点类型、酒店档次、饮食）通过 `classifier.extract_tags()` 提取
2. `memory.add()` 更新五因子权重
3. 下次出行时 Planner prompt 注入新画像

**安全优化闭环：**
- 离线评估：每次记忆更新后，用历史请求跑回归测试，对比输出质量
- 在线 A/B：新老画像权重做 A/B，看用户采纳率
- 回滚机制：如果新画像导致输出变差，回滚到上一次 checkpoint

**为什么不做模型微调**：反馈延迟太长（数天）、灾难性遗忘、成本不可控（每月成百上千用户更新完全不可行）、安全风险（恶意输入进入权重）。模型是"推理引擎"，记忆是"用户手册"——引擎不变，手册持续更新。

---

## 十二、未来规划

### 已预留但未实现

- **Agent 反馈环**：Planner → Hotel 的 `retry_hotel` conditional edge 已打通，后续可改为"Planner 发现酒店不匹配 → 重新搜更匹配的酒店"而非当前简单的离群触发
- **多用户支持**：State 的 `thread_id` 已配置，换 `SqliteSaver` 为 PostgreSQL 即可多线程隔离
- **RAG 知识库**：游记攻略作为 Planner 的额外参考上下文，BM25 初筛 + 向量语义检索

### 性能优化

- **LLM 并行化**：景点和酒店可改为均以城市中心为基准并行搜索，各自独立返回结果后再做空间校验——景点质心离酒店区太远则触发 retry_hotel 用新质心重搜。整体从串行变 fork-join-validate，减少端到端延迟
- **Redis 缓存**：热点城市的 POI 和天气数据缓存，减少 MCP 调用

### 算法升级

- **DBSCAN 聚类**：替代标准差法做选址，天然支持多簇（老城区+新城区双峰分布）
- **Embedding 画像**：标签匹配升级为向量语义检索——"爱吃清淡的"和"不吃辣"语义相近但关键词不匹配

### 产品化

- **实时行程调整**：暴雨 → 自动把户外景点替换为室内备选
- **多人协作**：三人出行，偏好冲突怎么消解
- **A/B 评测**：四层评估体系（L1 Schema 自动 → L2 约束检查 → L3 LLM-as-Judge → L4 人工标注）
- **消息队列**：非关键路径（记忆更新、统计日志）放入消息队列异步处理

### 行业趋势把握

保持对以下方向的技术敏感度（五层信息漏斗：Twitter/arXiv/GitHub/Discord/动手复现）：

- LangGraph v1.0 Functional API 和新的 `Command` 原语
- MCP 协议从工具注册扩展到资源注册（Jan 2025）
- Google A2A（Agent-to-Agent）协议的标准化进展
- 多 Agent 的评估基准：GAIA、SWE-bench Multi-Agent 等

---

## 十三、5 分钟演示脚本（Live Demo）

### 第一步：架构图（30 秒）

打开 ARCHITECTURE.md，展示 6 层架构图。

> "这是我们的 6 层架构。我从最底层简单讲一下每层做什么——"

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

> "这个请求背后执行了 4 个 LangGraph Node——景点搜索、酒店推荐、记忆加载、行程规划。每个 Node 的执行结果自动保存为 Checkpoint。"

### 第四步：异常恢复演示（1 分钟，如果有时间）

> "如果我模拟高德 API 不可用——"（展示 FallbackTool 生成的降级方案）
