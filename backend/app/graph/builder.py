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

Phase 3 核心概念 #4: Checkpoint（SQLite 持久化）

  使用 SqliteSaver 将 checkpoint 持久化到 data/checkpoints.db。
  每次 graph.invoke(state) 时传入 thread_id，
  LangGraph 在每步 Node 执行后自动保存 State 快照到 SQLite。

  中断后重试: 相同 thread_id → 从上次断点继续，不重新跑已完成的 Node。
  相比默认的内存 Checkpoint: SQLite 持久化可在进程重启后恢复。
"""
import os
import sqlite3
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.sqlite import SqliteSaver
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

    图结构（4 Node, memory ∥ attraction fan-out）:
              ┌──────────┐
              │  START   │
              └────┬─────┘
        ┌─────────┴──────────┐   ← fan-out
    ┌───▼──────┐          ┌──▼───────┐
    │ attraction│          │  memory  │  (纯本地读, 与 attraction 并行)
    └────┬─────┘          └─────┬────┘
         │                      │
    ┌────▼─────┐                │
    │   hotel   │               │
    └────┬─────┘                │
         └─────────┬────────────┘   ← join (planner 等两者)
              ┌────▼─────┐
              │  planner  │──conditional──→ retry_planner / retry_hotel / done
              └──────────┘

    memory_node 无外部依赖（只读 memory.json），且不读 state 任何字段，
    与 attraction_node 并行安全。写入字段无冲突：
      - attraction_node 写 attraction_data/status/center_*/coords
      - memory_node    写 user_profile
    共同 error_log 由 Annotated[list, add] reducer 自动合并。
    """

    # 1. 创建 StateGraph——核心对象，管理所有 Node 和 Edge
    graph = StateGraph(TripPlannerState)

    # 2. 注册 Node（4 Node: 天气已移至 API 层）
    graph.add_node("attraction", attraction_node)
    graph.add_node("hotel", hotel_node)
    graph.add_node("memory", memory_node)
    graph.add_node("planner", planner_node)

    # 3. 入口 fan-out: START 同时指向 attraction 和 memory → 并行执行
    graph.add_edge(START, "attraction")
    graph.add_edge(START, "memory")

    # 4. Edge:
    #   attraction → hotel → planner  (主链路)
    #   memory     → planner          (旁路 join: planner 有两个入边，等两者都到达)
    graph.add_edge("attraction", "hotel")
    graph.add_edge("hotel", "planner")
    graph.add_edge("memory", "planner")

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

    # 6. 编译——生成可执行的图，使用 SQLite 持久化 Checkpoint
    # builder.py 在 backend/app/graph/ 下，上溯 4 层到项目根，然后 data/
    _project_root = os.path.abspath(os.path.join(
        os.path.dirname(__file__), "..", "..", "..", ".."))
    data_dir = os.path.join(_project_root, "data")
    os.makedirs(data_dir, exist_ok=True)

    # SQLite 连接：check_same_thread=False 因为 LangGraph 在不同线程读写 checkpoint
    db_path = os.path.join(data_dir, "checkpoints.db")
    conn = sqlite3.connect(db_path, check_same_thread=False)
    checkpointer = SqliteSaver(conn)

    return graph.compile(checkpointer=checkpointer)
# 全局单例
_trip_graph = None


def get_trip_graph():
    """获取编译后的图实例（单例）"""
    global _trip_graph
    if _trip_graph is None:
        _trip_graph = build_trip_graph()
    return _trip_graph
