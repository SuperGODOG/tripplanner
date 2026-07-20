"""LangGraph State 定义"""
from typing import TypedDict, Annotated
from operator import add


class TripPlannerState(TypedDict, total=False):
    # ── 输入 ──
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

    # ── 各 Agent 输出 ──
    attraction_data: str
    weather_data: str
    hotel_data: str

    # ── 空间计算（attraction_node 产出）──
    center_lng: float             # 景点群物理中心经度
    center_lat: float             # 景点群物理中心纬度
    attraction_coords: list       # [{name, lng, lat}, ...]

    # ── 状态标记 ──
    attraction_status: str
    weather_status: str
    hotel_status: str

    # ── Planner 回环控制 ──
    planner_route: str                 # "done" / "retry_planner" / "retry_hotel"
    planner_retry_count: int           # Planner 重试计数（最多 3 次）

    # ── 最终输出 ──
    final_plan: dict

    # Annotated[list, add] = LangGraph 自动 append 而非 overwrite
    error_log: Annotated[list[str], add]

    # ── 记忆注入 ──
    user_profile: dict
