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

    # ── 空间计算（attraction_node 产出）──
    center_lng: float                # 全部候选质心经度
    center_lat: float                # 全部候选质心纬度
    urban_lng: float                 # 市区质心经度（去远郊，酒店选址用）
    urban_lat: float                 # 市区质心纬度
    attraction_coords: list          # [{name, lng, lat}, ...]
    excursion_pois: list             # [{name, dist_km}, ...] 远郊一日游标记

    # ── 重试计数器 ──
    planner_retry_count: int         # Planner 自回环计数

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
