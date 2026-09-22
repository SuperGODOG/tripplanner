# Interview Design Map — SuperGODOG__tripplanner

> 由 repo_fuse 自动生成（面试题库 × 本仓库设计映射）。用于把本项目的设计决策与面试高频设计主题对齐。

## 项目技术画像

- 框架/技术栈：Vue、MCP
- 文件规模：50 个源文件
- 与面试题库命中 23 个设计主题

## 设计主题 ↔ 仓库实现映射

| 面试设计主题 | 仓库中的实现/证据 | 对应题库位置 |
|---|---|---|
| ReAct 与 Agent 工作流范式 | <内容命中> | 见题库「ReAct 与 Agent 工作流范式」概念笔记 |
| MCP | backend/test_mcp.py | 见题库「MCP」概念笔记 |
| 容错限流与高可用 | <内容命中> | 见题库「容错限流与高可用」概念笔记 |
| LangGraph 与图编排 | backend/app/graph/nodes.py, backend/app/graph/state.py | 见题库「LangGraph 与图编排」概念笔记 |
| Tool Calling 与 Function Calling | <内容命中> | 见题库「Tool Calling 与 Function Calling」概念笔记 |
| Prompt Engineering | <内容命中> | 见题库「Prompt Engineering」概念笔记 |
| RAG 与知识库 | <内容命中> | 见题库「RAG 与知识库」概念笔记 |
| Agent 记忆机制 | backend/test_memory.py, backend/test_memory_integration.py, backend/app/memory/models.py | 见题库「Agent 记忆机制」概念笔记 |
| AI Coding Agent | <内容命中> | 见题库「AI Coding Agent」概念笔记 |
| 上下文管理与压缩 | <内容命中> | 见题库「上下文管理与压缩」概念笔记 |
| Multi-Agent 多智能体协作 | <内容命中> | 见题库「Multi-Agent 多智能体协作」概念笔记 |
| 算法与 LeetCode | <内容命中> | 见题库「算法与 LeetCode」概念笔记 |
| 存储选型与状态持久化 | <内容命中> | 见题库「存储选型与状态持久化」概念笔记 |
| Badcase 闭环与数据飞轮 | <内容命中> | 见题库「Badcase 闭环与数据飞轮」概念笔记 |
| 评测体系与 Benchmark | <内容命中> | 见题库「评测体系与 Benchmark」概念笔记 |
| Query 改写 | <内容命中> | 见题库「Query 改写」概念笔记 |

## 建议的面试切入点

- 本仓库最能体现设计深度的模块（按命中概念与证据文件定位，建议对照《项目内作答》准备）
- 每个主题准备"框架给的 vs 我设计的"对照（如用 LangGraph 则强调图结构与状态设计的自有决策）

---
生成时间：由 repo_fuse 生成，随题库/仓库变化可重跑更新。
