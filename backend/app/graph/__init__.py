"""[LEGACY ARCHIVED FACADE] LangGraph 历史工作流兼容门面

架构声明 (Architecture Notice):
本项目生产调度核心已全面升级为纯原生 Sovereign Harness 自主循环架构 (app.harness)。
原本基于 LangGraph StateGraph 的图状态机 (builder.py, nodes.py, session_graph.py) 已正式退役解耦，
当前目录仅保留作为历史底层算法测试桩与 Monkeypatch 兼容 Facade，业务运行时 100% 由 Sovereign Harness 独占驱动。
"""
