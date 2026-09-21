"""行程画板交互与局域自愈引擎 (Itinerary Canvas Mutation & Local 2-Opt Self-Healing)

设计原则:
1. Human-in-the-Loop: 尊重用户拖拽调序与跨天分配的主观意志。
2. 局域 2-Opt 自愈 (<30ms): 当用户触发智能顺路或跨天调序时，消除局部交叉绕路，毫秒级收敛最优时序。
3. 动态属性自愈重算:
   - 重新计算逐站之间实际通行距离 (Haversine × 绕路系数) 与通行时间。
   - 重新根据真实作息 (晨光早游 08:30 vs 自然醒慢行 10:00) 弹性生成到离时间。
   - 重新核算当日门票总额、日通行距离、体温舒适度步数提示。
   - 重新对齐当日日期的 5A 景区实名预约时效评估 (Reservation Policy Guard)。
   - 统一透传高清实景图片 (resolve_poi_image)。
"""
from __future__ import annotations

import logging
from typing import Any

from .poi_images import resolve_poi_image
from .reservation_policy import evaluate_poi_reservation
from .route_solver import (
    _haversine_km,
    _travel_minutes,
    _two_opt,
    _greedy_nearest,
    estimate_visit_minutes,
    _min_to_str,
)

logger = logging.getLogger(__name__)


def mutate_itinerary_plan(
    plan: dict[str, Any],
    mutated_days: list[dict[str, Any]],
    mode: str = "recalc",  # "recalc" (保留拖拽顺序并重排时间距离) | "2opt" (对改动天执行 2-Opt TSP 空间最优解)
    target_day_index: int | None = None,
    planning_date: str = "",
) -> dict[str, Any]:
    """对行程分日进行重排与局部自愈重算"""
    if not plan:
        return {}

    updated_plan = dict(plan)
    lifestyle = updated_plan.get("lifestyle_profile") or {}
    is_morning = bool(lifestyle.get("morning_person", False))
    walking_limit_km = float(lifestyle.get("daily_walking_limit_km", 8.0) or 8.0)
    base_start_h = 8 if is_morning else 10
    base_start_m = 30

    new_days = []
    for day_data in mutated_days:
        d = dict(day_data)
        d_idx = d.get("day_index", 0)
        day_date = d.get("date", "")
        attractions = list(d.get("attractions") or [])

        # 若是 2-Opt 模式，且作用于所有天或指定 target_day_index
        should_2opt = (mode == "2opt") and (target_day_index is None or target_day_index == d_idx)
        if should_2opt and len(attractions) >= 3:
            # 运行 2-Opt TSP 局域自愈
            order = _greedy_nearest(attractions, start=d.get("hotel"))
            order = _two_opt(attractions, order)
            attractions = [attractions[i] for i in order]

        # 重新排定时间、通行距离与时序
        cur_min = base_start_h * 60 + base_start_m
        prev_poi = d.get("hotel")  # 首站若有酒店则从酒店出发算首站距离，否则首站为 0
        total_dist_km = 0.0
        total_ticket = 0.0
        recalculated_attrs = []

        for seq_idx, attr in enumerate(attractions):
            a = dict(attr)
            p_name = a.get("name", "精选名胜")

            # 确保拥有高清实景图
            if not a.get("image_url"):
                a["image_url"] = resolve_poi_image(p_name, category=a.get("category", ""))

            # 坐标补充
            if "lng" not in a and "location" in a and isinstance(a["location"], dict):
                a["lng"] = a["location"].get("longitude")
                a["lat"] = a["location"].get("latitude")

            # 计算通行时间与距离
            travel_min = 0
            dist_km = 0.0
            if prev_poi and prev_poi.get("lng") and prev_poi.get("lat") and a.get("lng") and a.get("lat"):
                travel_min = _travel_minutes(prev_poi, a)
                dist_km = round(
                    _haversine_km(
                        float(prev_poi["lng"]), float(prev_poi["lat"]),
                        float(a["lng"]), float(a["lat"])
                    ), 1
                )
                total_dist_km += dist_km
            elif seq_idx == 0:
                dist_km = 0.0

            cur_min += travel_min

            # 午休餐饮自适应调整
            if seq_idx == 1 and cur_min < 13 * 60:
                # 适度为午餐预留时间
                cur_min = max(cur_min, 13 * 60 + 30)

            visit_dur = a.get("visit_minutes") or estimate_visit_minutes(a)
            a["visit_minutes"] = visit_dur
            a["arrive_time"] = _min_to_str(cur_min)
            a["depart_time"] = _min_to_str(cur_min + visit_dur)
            a["distance_km"] = dist_km
            cur_min += visit_dur

            # 门票累计
            p_price = float(a.get("price") or a.get("ticket_price") or 0.0)
            a["price"] = p_price
            a["ticket_price"] = p_price
            total_ticket += p_price

            # 5A 景区实名预约策略实时复核 (Reservation Policy Guard)
            r_alert = evaluate_poi_reservation(p_name, visit_date=day_date, planning_date=planning_date)
            if r_alert:
                a["reservation_alert"] = r_alert
            else:
                a.pop("reservation_alert", None)

            prev_poi = a
            recalculated_attrs.append(a)

        d["attractions"] = recalculated_attrs
        d["total_ticket"] = round(total_ticket, 2)

        # 更新遥测与步数关怀提示
        telemetry = dict(d.get("telemetry") or {})
        telemetry["total_distance_km"] = round(total_dist_km, 1)
        telemetry["walking_limit_km"] = walking_limit_km
        is_exceeded = total_dist_km > walking_limit_km
        telemetry["is_walking_exceeded"] = is_exceeded

        if is_exceeded:
            telemetry["pacing_hint"] = (
                f"今日预计通行约 {round(total_dist_km, 1)}km，超出设定的舒适步数({walking_limit_km}km)，建议打车或乘坐轨道交通"
            )
        else:
            telemetry["pacing_hint"] = (
                f"今日通行约 {round(total_dist_km, 1)}km，在舒适步数({walking_limit_km}km)范围内，节奏轻松舒适"
            )

        d["telemetry"] = telemetry
        new_days.append(d)

    updated_plan["days"] = new_days
    # 版本递增
    curr_version = updated_plan.get("version_id", 1)
    if isinstance(curr_version, (int, float)):
        updated_plan["version_id"] = int(curr_version) + 1
    else:
        updated_plan["version_id"] = 2

    return updated_plan
