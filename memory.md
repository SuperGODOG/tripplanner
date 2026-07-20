# 重要记忆汇总

> 可用于跨会话追踪复用

---

## 一、个人信息

| 项目 | 内容 |
|------|------|
| 姓名 |  (caoruixin) |
| 目标 | 找 Agent 方向实习（含央国企） |
| 学习风格 | 先跑起来 → 看源码 → 查文档（三步法） |
| 语言偏好 | 中文（简体），课件 A4 打印优化 |
| API Key | 有 DeepSeek API Key、Tavily API Key |
| 高德地图 API Key | 需要申请（TripPlanner 用） |

---

## 二、项目管理

### 项目路径

| 项目 | 根目录 |
|------|--------|
| TripPlanner | `/home/caoruixin/projects/tripplanner` |
| SkillForge | 方案书在 `hello-agents/.teaching/lessons/skillforge/` |
| hello-agents 教学 | `/home/caoruixin/projects/hello-agents` |

### TripPlanner 开发状态

- 计划书：`tripplanner/plan/IMPLEMENTATION_PLAN.md`
- Phase 详情：`tripplanner/plan/Phase1~8-*.md`
- 架构图：`tripplanner/ARCHITECTURE.md`
- 项目方案书：`tripplanner/TripPlanner-项目方案书.docx`
- 参考实现：`hello-agents/code/chapter13/helloagents-trip-planner/`

### SkillForge 开发状态

- 方案书：`hello-agents/.teaching/lessons/skillforge/SkillForge-项目方案书.docx`
- 架构图：`hello-agents/.teaching/lessons/skillforge/ARCHITECTURE.md`

---

## 三、学习路线图（已全部完成）

```
Lesson 1 — Ch7 框架入门（LLM + Agent + 工具）
Lesson 2 — ReAct Agent 实现原理（循环引擎/正则/Error as Observation）
Lesson 3 — LangGraph 图编排（State/Node/Edge/Checkpoint）
Lesson 4 — Ch4 三种范式手写对比（ReAct / Reflection / Plan-and-Solve）
Lesson 5 — Ch8 记忆系统 + RAG（MemoryTool / RAGTool）
Lesson 6 — Ch10 通信协议（MCP / A2A / ANP）
Lesson 7 — Ch13 全栈旅行助手
```

### 面试题

- 面试题文档：`hello-agents/.teaching/lessons/interview-questions.html`

---

## 四、项目面试引导策略

两个项目互补，覆盖不同方向：

```
TripPlanner（旅行助手）         SkillForge（元 Agent 系统）
━━━━━━━━━━━━━━━━━━━━         ━━━━━━━━━━━━━━━━━━━━
LangGraph 图编排              Skill 体系（渐进式披露）
MCP 协议集成                  Agent 评估方法论
多 Agent 流水线               Meta Agent 闭环
Error-as-Observation         棘轮机制（只进不退）
自定义记忆模块                三层路由（规则/embedding/LLM）
```

面试官问 MCP → 讲 TripPlanner
面试官问 Skill/评估 → 讲 SkillForge
面试官问框架对比 → 两个项目都能展开

---

## 五、Agent 6 层架构

```
第 6 层: 元 Agent / Skill 体系    ← SkillForge
第 5 层: 多智能体编排              ← TripPlanner (LangGraph)
第 4 层: 图编排框架                ← LangGraph
第 3 层: 框架封装                  ← HelloAgents (SimpleAgent/ToolRegistry)
第 2 层: 手写循环                  ← Ch4 ReAct (while + prompt + 正则)
第 1 层: 裸 LLM 调用              ← HelloAgentsLLM.invoke()
```

---

## 六、技术栈

| 技术 | 用途 | 状态 |
|------|------|------|
| hello-agents | Agent 框架 | ✅ 已学 |
| LangGraph | 图编排 | ✅ 已学概念，项目会用 |
| MCP 协议 | 工具标准化 | ✅ 已学 |
| FastAPI | 后端 Web | ⏳ 项目将用到 |
| DeepSeek | LLM | ✅ 有 Key |
| Tavily | 搜索 API | ✅ 有 Key |
| 高德地图 API | 位置服务 | ❌ 需申请 Key |
| Qdrant | 向量数据库 | ⏳ Ch8 RAG 用 |
| uv | Python 包管理器 | ❌ Phase 1 需安装 |

---

## 七、教学相关

### 课件位置

```
hello-agents/.teaching/lessons/
├── 0001-first-agent-run.html
├── 0002-react-agent.html
├── 0003-langgraph.html
├── 0004-paradigms-comparison.html
├── 0005-memory-rag.html
├── 0006-protocols.html
├── 0007-trip-planner.html
├── agent-architecture-layers.html
└── interview-questions.html
```

### 教学 CSS（A4 打印优化）

文件：`hello-agents/.teaching/assets/lesson.css`
- 10pt 字号，line-height 1.7，15mm 边距
- h2 每节分页
- 适合 A4 打印输出

### 学习记录

```
hello-agents/.teaching/learning-records/
├── 0001-lesson1-complete.md
├── 0002-lesson2-complete.md
├── 0003-lesson3-exercise-insights.md
├── 0004-paradigms-understanding.md
├── 0005-lesson3-design-insights.md
├── 0006-react-exercise-insights.md
├── 0007-lesson3-langgraph.md
├── 0008-lesson3-complete.md
└── 0009-all-lessons-complete.md
```

---

## 八、框架修改记录

hello-agents 框架被修改过的文件：

| 文件 | 修改内容 | 影响 |
|------|---------|------|
| `llm.py` (`_resolve_credentials()`) | `.env` 加载路径加上 `Path.cwd()/.env` 兜底 | 所有项目不用额外配置 |
| 补丁说明 | `hello-agents/patch-note-001.md` | 记录修改，恢复时用 |

---

