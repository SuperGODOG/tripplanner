"""LangGraph 图构建

Phase 3 核心概念 #3: Graph + Edge + Conditional Routing

图结构:
  START → attraction → hotel → memory → planner → END
                ↓          ↓         ↓
              每个 Node 返回 status，决定下游行为
              (Phase 3 先做 linear，conditional edge 在 Phase 4 基础上加)

Phase 3 核心概念 #4: Checkpoint

  graph.compile() 默认启用 Checkpoint。
  每次 graph.invoke(state) 时传入 thread_id，
  LangGraph 在每步 Node 执行后自动保存 State 快照。
  
  中断后重试: 相同 thread_id → 从上次断点继续，不重新跑已完成的 Node。
"""
from langgraph.graph import StateGraph, END
from .state import TripPlannerState
from .nodes import attraction_node, hotel_node, memory_node, planner_node


def build_trip_graph() -> StateGraph:
    """
    构建 TripPlanner LangGraph。

    图结构:
    ┌──────────┐
    │  START   │
    └────┬─────┘
         │
    ┌────▼─────┐
    │ attraction│──成功/失败──→
    └────┬─────┘
         │
    ┌────▼─────┐
    │   hotel   │──成功/失败──→
    └────┬─────┘
         │
    ┌────▼─────┐
    │  memory   │
    └────┬─────┘
         │
    ┌────▼─────┐
    │  planner  │  ← 读 state 中的 status，
    └────┬─────┘     自己决定降级策略
         │
    ┌────▼─────┐
    │   END    │
    └──────────┘
    """

    # 1. 创建 StateGraph——核心对象，管理所有 Node 和 Edge
    graph = StateGraph(TripPlannerState)

    # 2. 注册 Node
    graph.add_node("attraction", attraction_node)
    graph.add_node("hotel", hotel_node)
    graph.add_node("memory", memory_node)
    graph.add_node("planner", planner_node)

    # 3. 设定入口
    graph.set_entry_point("attraction")

    # 4. Edge: attraction → hotel → memory → planner
    graph.add_edge("attraction", "hotel")
    graph.add_edge("hotel", "memory")       # 酒店 → 记忆加载
    graph.add_edge("memory", "planner")     # 记忆 → 规划（画像已注入 State）
    graph.add_edge("planner", END)

    # 5. 编译——生成可执行的图，默认启用 Checkpoint
    return graph.compile()


# 全局单例
_trip_graph = None


def get_trip_graph():
    """获取编译后的图实例（单例）"""
    global _trip_graph
    if _trip_graph is None:
        _trip_graph = build_trip_graph()
    return _trip_graph
