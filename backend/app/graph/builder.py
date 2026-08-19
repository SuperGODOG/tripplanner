"""LangGraph 图构建

Phase 3 核心概念 #3: Graph + Edge + Conditional Routing

图结构（4 Node: 天气已移至 API 层，attraction/hotel 为确定性检索节点）:
  START → attraction → hotel → memory → planner → [conditional]
                                            ↙      ↘
                              retry_planner         done
                              (硬伤重生成)           END

conditional edge:
  planner 执行后，_validate_and_refine() 写入 state.planner_route:
  - "retry_planner" → 自回环重新生成（最多 3 次）
  - "done" → END

2026-08 重构: retry_hotel 回环已删除——离群检测不再触发酒店重搜，
远郊景点由 attraction_node 标记 excursion（一日游），酒店选址用市区质心。

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


def build_trip_graph(checkpointer=None):
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
         └─────────┬────────────┘   ← 都汇入 planner（经 state 共享，无 join 边）
              ┌────▼─────┐
              │  planner  │──conditional──→ retry_planner / done
              └──────────┘

    memory_node 与 attraction_node 并行安全（各自写不同字段）：
      - attraction_node 写 candidates/center_*/coords/excursion
      - memory_node    写 user_profile
    共同 error_log 由 Annotated[list, add] reducer 自动合并。

    注意（2026-08 实测）: LangGraph 1.2.9 对跨 superstep 的 fan-in 是
    "每条入边各触发一次"，不是 join——planner 若同时挂 hotel→planner 与
    memory→planner 两条边会被触发两次（LLM 调用双倍）。
    因此 memory 结果经共享 state 传递（planner 读 state["user_profile"]），
    planner 只保留 hotel 单入边。memory 为本地 SQLite 读（ms 级），
    必然先于 attraction→hotel 的 MCP 网络调用（秒级）完成。

    checkpointer: 默认 SqliteSaver（持久化）；测试可注入 InMemorySaver。
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
    #   memory     → (state 共享)     (并行分支：结果经 state 写入，无 join 边)
    #   注意: 不添加 memory → planner 边——LangGraph 1.2.9 跨 superstep fan-in
    #   每条入边触发一次节点，会导致 planner 执行两次（详见模块 docstring）。
    graph.add_edge("attraction", "hotel")
    graph.add_edge("hotel", "planner")

    # 5. Conditional edge: planner → retry_planner / done
    graph.add_conditional_edges(
        "planner",
        _route_planner,
        {
            "retry_planner": "planner",     # 硬伤 → 自回环重生成
            "done": END,
        }
    )

    # 6. 编译——生成可执行的图，使用 SQLite 持久化 Checkpoint（测试可注入内存版）
    if checkpointer is None:
        # builder.py 在 backend/app/graph/ 下，上溯 3 层到项目根，然后 data/
        _project_root = os.path.abspath(os.path.join(
            os.path.dirname(__file__), "..", "..", ".."))
        data_dir = os.path.join(_project_root, "data")
        os.makedirs(data_dir, exist_ok=True)

        # SQLite 连接：check_same_thread=False 因为 LangGraph 在不同线程读写 checkpoint
        db_path = os.path.join(data_dir, "checkpoints.db")
        conn = sqlite3.connect(db_path, check_same_thread=False, timeout=30)
        checkpointer = SqliteSaver(conn)

    return graph.compile(checkpointer=checkpointer)
def get_trip_graph():
    """创建当前请求独享的图和 SQLite 连接，避免跨请求共享事务状态。"""
    return build_trip_graph()
