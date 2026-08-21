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
from .nodes import (attraction_node, hotel_node, memory_node,
                    day_node, merge_node, _fan_out)


def build_trip_graph(checkpointer=None):
    """
    构建 TripPlanner LangGraph。

    图结构（v3 分日并发，Send API 动态 fan-out）:
              ┌──────────┐
              │  START   │
              └────┬─────┘
        ┌─────────┴──────────┐   ← fan-out
    ┌───▼──────┐          ┌──▼───────┐
    │ attraction│          │  memory  │  (纯本地读, 与 attraction 并行)
    └────┬─────┘          └──────────┘
         │
    ┌────▼─────┐
    │   hotel   │  (本地选定全程酒店)
    └────┬─────┘
         │  _fan_out: Send("day_node", {day_index, day_pois, ...}) × N
    ┌────▼───────────────┐
    │ day_node × N（并行）│  (聚类互斥 + 本地路径求解 + 单天文案 LLM)
    └────┬───────────────┘
         │  reducer 聚合 plan_days（Send 汇聚只触发 1 次，实测确认）
    ┌────▼─────┐
    │ merge_node│  (天气解析/酒店/三餐/预算/校验 → final_plan)
    └────┬─────┘
         ▼
        END

    memory_node 与 attraction_node 并行安全（各自写不同字段）:
      - attraction_node 写 candidates/center_*/coords/excursion/day_clusters
      - memory_node    写 user_profile
    共同 error_log 由 Annotated[list, add] reducer 自动合并。

    Send 语义（2026-08-21 实测，LangGraph 1.2.9）:
      - day_node 分支的 state 只含 Send payload——共享上下文必须显式注入（_fan_out 已做）
      - 多分支汇聚到 merge_node 只触发 1 次（与跨 superstep fan-in 双触发不同）
      - 景点互斥由聚类分配保证（数据层），LLM 不做全局去重

    checkpointer: 默认 SqliteSaver（持久化）；测试可注入 InMemorySaver。
    """

    # 1. 创建 StateGraph——核心对象，管理所有 Node 和 Edge
    graph = StateGraph(TripPlannerState)

    # 2. 注册 Node（5 个: attraction/hotel/memory 确定性 + day_node/merge_node）
    graph.add_node("attraction", attraction_node)
    graph.add_node("hotel", hotel_node)
    graph.add_node("memory", memory_node)
    graph.add_node("day_node", day_node)
    graph.add_node("merge_node", merge_node)

    # 3. 入口 fan-out: START 同时指向 attraction 和 memory → 并行执行
    graph.add_edge(START, "attraction")
    graph.add_edge(START, "memory")

    # 4. 主链路: attraction → hotel → 动态分日
    graph.add_edge("attraction", "hotel")
    graph.add_conditional_edges("hotel", _fan_out, ["day_node"])

    # 5. 汇聚: day_node × N → merge_node（Send 汇聚，实测只触发 1 次）
    graph.add_edge("day_node", "merge_node")
    graph.add_edge("merge_node", END)

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
    """创建当前请求独享的图和 SQLite 连接，避免跨请求共享事务状态。

    ⚠️ 2026-08-21: 本函数创建的 sqlite 连接从不关闭（每请求累积一个 fd）。
    trip.py 已改用 open_trip_graph()（显式返回 conn 供 finally 关闭）；
    本函数仅保留给根目录旧验证脚本（test_graph.py / test_memory_integration.py）使用。
    """
    return build_trip_graph()


def open_trip_graph():
    """创建当前请求独享的图和 SQLite 连接，返回 (graph, conn)。

    调用方必须在 finally 中 conn.close()——每请求新建连接但从不关闭
    会累积 fd 泄漏（2026-08-21 修复）。隔离语义与 get_trip_graph 一致：
    连接、图实例均每请求新建，不跨请求共享事务状态。
    """
    _project_root = os.path.abspath(os.path.join(
        os.path.dirname(__file__), "..", "..", ".."))
    data_dir = os.path.join(_project_root, "data")
    os.makedirs(data_dir, exist_ok=True)

    db_path = os.path.join(data_dir, "checkpoints.db")
    conn = sqlite3.connect(db_path, check_same_thread=False, timeout=30)
    return build_trip_graph(SqliteSaver(conn)), conn
