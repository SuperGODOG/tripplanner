# TripPlanner 实施计划

> 基于修正版方案书 v2
> 总代码量：~1400 行 | 工期：3 周 | 7 个 Phase

## Phase 清单

| Phase | 文件 | 内容 | 代码量 | 周 |
|-------|------|------|--------|-----|
| 1 | Phase1-环境与MCP.md | venv + 依赖 + amap-mcp-server 调通 | ~200 行 | 1 |
| 2 | Phase2-Agent定义.md | 4 个 SimpleAgent + 共享 MCPTool | ~250 行 | 1 |
| 3 | Phase3-LangGraph编排.md | StateGraph + Node + Edge + Conditional Routing | ~200 行 | 2 |
| 4 | Phase4-本地Tool.md | AmapToolWrapper(Format+Validate) + FallbackTool | ~250 行 | 2 |
| 5 | Phase5-FastAPI.md | API 层 + 模型 + 端到端联调 | ~200 行 | 3 |
| 6 | Phase6-记忆模块.md | 用户画像：领域分类→权重赋分→去重 | ~200 行 | 3 |
| 7 | Phase7-面试文档.md | 面试文档 + 架构图完善 | ~100 行 | 3 |

## 依赖关系

```
Phase 1 (环境+MCP) ──→ Phase 2 (Agent) ──→ Phase 3 (LangGraph)
                                                    │
                          ┌─────────────────────────┘
                          ↓
                    Phase 4 (本地Tool)
                          │
                    ┌─────┴─────┐
                    ↓           ↓
             Phase 5 (API)  Phase 6 (记忆)
                    │           │
                    └─────┬─────┘
                          ↓
                    Phase 7 (文档)
```

## 执行原则

1. **每个 Phase 必须独立可验证**——Phase 结束时有明确的"跑通"标准
2. **先跑通再优化**——先用最简单实现跑通，再重构
3. **参考实现是兜底**——遇到阻塞时回到 `chapter13/helloagents-trip-planner/` 看能不能直接用
4. **Phase 1-5 是核心路径**，Phase 6-7 是加分项
