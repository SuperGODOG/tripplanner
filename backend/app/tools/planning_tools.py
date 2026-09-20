"""确定性规划工具集 (Planning Tools)

将底层无副作用确定性算法（路线求解、空间聚类、预算核算）封装为强类型工具。
支持输出丰富诊断信号，为后续 Planning Agent 与 Repair Agent 赋能。
"""
from __future__ import annotations

from typing import Any
from ..services.clustering import cluster_pois_by_day
from ..services.route_solver import solve_day_route_with_diagnostics
from ..models.diagnostics import (
    RouteSolverResult,
    DiagnosticSignal,
    ErrorCode,
    DiagnosticSeverity,
)
from .cache_decorator import cached_tool_result, make_route_cache_key


@cached_tool_result("solve_day_route", key_builder=make_route_cache_key, ttl=86400)
def solve_day_route_tool(
    pois: list[dict[str, Any]],
    start_hour: int = 9,
    close_hour: int = 20,
    start_hotel: dict[str, Any] | None = None,
    day_index: int = 0,
    immutable_names: list[str] | None = None,
) -> RouteSolverResult:
    """日内最优路径求解工具

    执行贪心最近邻 + 2-opt + 时间窗校验。
    若超时则输出详细 DiagnosticSignal。
    """
    hotel_start = None
    if start_hotel and start_hotel.get("lng") is not None and start_hotel.get("lat") is not None:
        hotel_start = {"lng": float(start_hotel["lng"]), "lat": float(start_hotel["lat"])}

    return solve_day_route_with_diagnostics(
        pois=pois,
        start_hour=start_hour,
        close_hour=close_hour,
        start=hotel_start,
        day_index=day_index,
        immutable_names=immutable_names,
    )


def cluster_pois_tool(
    pois: list[dict[str, Any]],
    days: int,
    excursions: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """空间 K-Means 聚类工具

    将 POI 候选池依据空间几何聚类划分为互斥的分日簇。
    """
    if not pois or days <= 0:
        return []
    return cluster_pois_by_day(pois=pois, days=days, excursion_pois=excursions)


def check_budget_tool(
    plan_days: list[dict[str, Any]],
    hotel_per_night_cost: float,
    days: int,
    intercity_cost: float = 0.0,
    budget_limit: float | None = None,
    day_index: int = 0,
) -> tuple[dict[str, Any], DiagnosticSignal | None]:
    """行程预算核算与超支诊断工具

    核算门票、住宿、餐饮（每人每天150元基准）与城际交通大开销。
    若超出用户预算上限，输出带有费用明细与建议动作的 DiagnosticSignal。
    """
    ticket_total = 0.0
    for day in plan_days:
        for attr in day.get("attractions", []):
            ticket_total += float(attr.get("ticket_price") or attr.get("price") or 0.0)

    hotel_nights = max(1, days - 1) if days > 1 else 1
    hotel_total = round(float(hotel_per_night_cost) * hotel_nights, 2)
    meals_total = round(150.0 * days, 2)
    intercity_total = round(float(intercity_cost), 2)

    total_cost = round(ticket_total + hotel_total + meals_total + intercity_total, 2)

    breakdown = {
        "ticket_cost": ticket_total,
        "hotel_cost": hotel_total,
        "meals_cost": meals_total,
        "intercity_cost": intercity_total,
        "total_cost": total_cost,
        "budget_limit": budget_limit,
    }

    if budget_limit is not None and total_cost > budget_limit:
        overrun = round(total_cost - budget_limit, 2)
        diag = DiagnosticSignal(
            error_code=ErrorCode.BUDGET_EXCEEDED,
            day_index=day_index,
            severity=DiagnosticSeverity.HARD_FAIL,
            summary=f"预估总开销 ¥{total_cost} 超出预算上限 ¥{budget_limit}（超额 ¥{overrun}）",
            details={
                "budget_limit": budget_limit,
                "total_cost": total_cost,
                "overrun_amount": overrun,
                "breakdown": breakdown,
            },
            conflicting_items=[],
            immutable_constraints=[],
            attempted_actions=[],
            actionable_suggestions=["SWAP_HOTEL_TO_ECONOMY", "REDUCE_PAID_ATTRACTIONS"],
        )
        return breakdown, diag

    return breakdown, None
