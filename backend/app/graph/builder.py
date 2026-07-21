"""LangGraph 图构建

Phase 3 核心概念 #3: Graph + Edge + Conditional Routing

图结构（4 Node: 天气已移至 API 层）:
  START → attraction → hotel → memory → planner → [conditional]
                                            ↙     ↓      ↘
                              retry_planner  retry_hotel  done
                              (硬伤重生成)   (离群重算)    END

conditional edge:
  planner 执行后，_validate_and_refine() 写入 state.planner_route:
  - "retry_planner" → 自回环重新生成（最多 3 次）
  - "retry_hotel"    → 回酒店用新中心重搜
  - "done" → END

Phase 3 核心概念 #4: Checkpoint

  graph.compile() 默认启用 Checkpoint。
  每次 graph.invoke(state) 时传入 thread_id，
  LangGraph 在每步 Node 执行后自动保存 State 快照。

  中断后重试: 相同 thread_id → 从上次断点继续，不重新跑已完成的 Node。
"""
from langgraph.graph import StateGraph, END
from .state import TripPlannerState
from .nodes import attraction_node, hotel_node, memory_node, planner_node


def _route_planner(state: TripPlannerState) -> str:
    """Planner 后 conditional edge 路由函数"""
    route = state.get("planner_route", "done")
    print(f"🔀 [Planner 路由] → {route}")
    return route


def build_trip_graph() -> StateGraph:
    """
    构建 TripPlanner LangGraph。

    图结构（4 Node）:
    ┌──────────┐
    │  START   │
    └────┬─────┘
         │
    ┌────▼─────┐
    │ attraction│
    └────┬─────┘
         │
    ┌────▼─────┐
    │   hotel   │
    └────┬─────┘
         │
    ┌────▼─────┐
    │  memory   │
    └────┬─────┘
         │
    ┌────▼─────┐
    │  planner  │──conditional──→ retry_planner / retry_hotel / done
    └──────────┘
    """

    # 1. 创建 StateGraph——核心对象，管理所有 Node 和 Edge
    graph = StateGraph(TripPlannerState)

    # 2. 注册 Node（4 Node: 天气已移至 API 层）
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

    # 5. Conditional edge: planner → retry_planner / retry_hotel / done
    graph.add_conditional_edges(
        "planner",
        _route_planner,
        {
            "retry_planner": "planner",     # 硬伤 → 自回环重生成
            "retry_hotel": "hotel",         # 离群 → 回酒店用新中心重搜
            "done": END,
        }
    )

    # 6. 编译——生成可执行的图，默认启用 Checkpoint
    return graph.compile()
# 全局单例
_trip_graph = None


def get_trip_graph():
    """获取编译后的图实例（单例）"""
    global _trip_graph
    if _trip_graph is None:
        _trip_graph = build_trip_graph()
    return _trip_graph
