"""LangGraph State 定义"""
from typing import TypedDict, Annotated
from operator import add


class TripPlannerState(TypedDict, total=False):
    # ── 输入 ──
    user_id: str
    budget_total: int | None
    day_start_hour: int
    day_end_hour: int
    origin: str
    city: str
    days: int
    start_date: str
    date_list: list[str]
    transport_mode: str
    preferences: list[str]

    # ── 城际交通 ──
    intercity_distance_km: float
    intercity_duration_h: float
    intercity_cost: int
    distance_category: str

    # ── 结构化候选（确定性节点产出，字段化传递）──
    attraction_candidates: list      # [PoiCandidate.model_dump(), ...]
    hotel_candidates: list           # [HotelCandidate.model_dump(), ...]

    # ── 文本摘要（planner prompt 用，本地生成）──
    attraction_data: str
    weather_data: str
    hotel_data: str

    # ── 空间数据（attraction_node 产出）──
    # 注: v3 已删 center_*/urban_* 质心字段——酒店选址改用目标函数（minimax），
    #     质心离群敏感且无业务语义（2026-08-21）
    attraction_coords: list          # [{name, lng, lat}, ...]
    excursion_pois: list             # [{name, dist_km}, ...] 远郊一日游标记

    # ── v3 分日并发（2026-08-21）──
    day_clusters: list               # [{"day_index", "kind", "pois": [...]}, ...] 聚类分配结果
    plan_days: Annotated[list, add]  # 各 day_node 并行产出的单天计划（reducer 聚合）
    day_pois: list                   # 当前 day_node 的簇 POI（Send payload 注入）
    day_kind: str                    # 当前 day_node 的天类型: normal/excursion/leisure
    day_date: str                    # 当前 day_node 的日期（Send payload 注入）
    hotel_selected: dict             # 本地选定的全程酒店（merge_node 填充用）

    # ── 重试计数器 ──
    planner_retry_count: int         # Planner 自回环计数
    planner_last_error: str          # 上一轮解析失败原因（重试 prompt 用，硬伤重试时清空）

    # ── 状态标记 ──
    attraction_status: str
    weather_status: str
    hotel_status: str

    # ── Planner 回环控制 ──
    planner_route: str               # "done" / "retry_planner"

    # ── 最终输出 ──
    final_plan: dict

    # Annotated[list, add] = LangGraph 自动 append 而非 overwrite
    error_log: Annotated[list[str], add]

    # ── 记忆注入 ──
    user_profile: dict
