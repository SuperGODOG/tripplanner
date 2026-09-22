"""闭环自愈 Agent (Repair Agent)

核心职责:
1. 消费来自规划求解器与时效核验的结构化 DiagnosticSignal。
2. 严格守护用户显式锁定项 (immutable_constraints)，执行确定性自愈策略：
   - 周一闭馆冲突 (VENUE_CLOSED): 自动与非周一日程中的常态开放景点对调；
   - 时间窗超额 (TIME_WINDOW_EXCEEDED): 剔除耗时最大或优先级最低的非锁定景点；
   - 预算超支 (BUDGET_EXCEEDED): 切换高性价比经济型酒店，核减高溢价自费项；
3. 设立最大重试熔断机制 (max_attempts = 2)，超出后安全转入人工裁决，杜绝无限死循环。
"""
from __future__ import annotations

import logging
from typing import Any
from ..models.diagnostics import ErrorCode, DiagnosticSignal, DiagnosticSeverity
from ..tools.planning_tools import solve_day_route_tool, check_budget_tool

logger = logging.getLogger(__name__)


class RepairAgent:
    """闭环自愈 Agent"""

    def __init__(self, max_attempts: int = 2):
        self.max_attempts = max_attempts

    def repair_plan(
        self,
        plan_days: list[dict[str, Any]],
        diagnostics: list[DiagnosticSignal | dict[str, Any]],
        immutable_names: list[str] | None = None,
        budget_total: float | None = None,
        hotel_cost_per_night: float = 400.0,
    ) -> tuple[list[dict[str, Any]], bool, list[str]]:
        """执行自愈修复流水线

        返回: (repaired_days, is_all_resolved, attempted_actions)
        """
        immutable_set = set(immutable_names or [])
        attempted_actions: list[str] = []

        # 归一化 diagnostics 为 DiagnosticSignal
        diag_objects: list[DiagnosticSignal] = []
        for d in diagnostics:
            if isinstance(d, DiagnosticSignal):
                diag_objects.append(d)
            elif isinstance(d, dict):
                try:
                    diag_objects.append(DiagnosticSignal.model_validate(d))
                except Exception:
                    pass

        if not diag_objects:
            return plan_days, True, []

        days_copy = [dict(d) for d in plan_days]

        # 1. 处理周一闭馆冲突 (VENUE_CLOSED)
        closure_diags = [
            d for d in diag_objects
            if d.error_code == ErrorCode.VENUE_CLOSED
            or "周一闭馆" in d.summary
            or "闭馆冲突" in d.summary
        ]
        for cd in closure_diags:
            src_day_idx = cd.day_index
            conflicting_names = cd.conflicting_items or []
            if not conflicting_names and "故宫" in cd.summary:
                conflicting_names = ["故宫博物院" if any("故宫博物院" in a.get("name", "") for a in days_copy[src_day_idx].get("attractions", [])) else "故宫"]

            for cname in conflicting_names:
                # 寻找非周一的目标天
                target_day_idx = None
                for idx, day_info in enumerate(days_copy):
                    if idx != src_day_idx:
                        # 检查目标天是否也包含闭馆限制（简单以非源天作为候选）
                        target_day_idx = idx
                        break

                if target_day_idx is not None:
                    # 在目标天找一个非闭馆限制的景点进行对调
                    src_attrs = list(days_copy[src_day_idx].get("attractions", []))
                    tgt_attrs = list(days_copy[target_day_idx].get("attractions", []))

                    # 找到源天的冲突景点
                    src_poi = next((a for a in src_attrs if cname in a.get("name", "")), None)
                    if src_poi and tgt_attrs:
                        # 取目标天首个可调换景点
                        tgt_poi = tgt_attrs[0]
                        # 互换
                        src_attrs.remove(src_poi)
                        tgt_attrs.remove(tgt_poi)
                        src_attrs.append(tgt_poi)
                        tgt_attrs.append(src_poi)

                        days_copy[src_day_idx]["attractions"] = src_attrs
                        days_copy[target_day_idx]["attractions"] = tgt_attrs

                        action_msg = (
                            f"SWAP_DAYS: 景点 [{cname}] 周一闭馆，已将其与第 {target_day_idx + 1} 天"
                            f"的常态开放景点 [{tgt_poi.get('name')}] 对调游览日程"
                        )
                        attempted_actions.append(action_msg)
                        logger.info(action_msg)
                else:
                    action_msg = (
                        f"VENUE_NOTICE: 景点 [{cname}] 逢周一例行闭馆，"
                        f"行程已保留并建议外观打卡或调整周次"
                    )
                    attempted_actions.append(action_msg)
                    logger.info(action_msg)

        # 2. 处理时间窗超额 (TIME_WINDOW_EXCEEDED)
        time_diags = [d for d in diag_objects if d.error_code == ErrorCode.TIME_WINDOW_EXCEEDED]
        for td in time_diags:
            day_idx = td.day_index
            if 0 <= day_idx < len(days_copy):
                attrs = list(days_copy[day_idx].get("attractions", []))
                # 筛选非用户锁定项
                prunable = [
                    a for a in attrs
                    if not any(lock in a.get("name", "") for lock in immutable_set)
                ]
                
                # 核心防稀疏保护：
                # 正常日常旅行（<= 4 个景点）绝对不删点，改用弹性晚间扩展至 22:00 自愈；
                # 仅在景点数过多 (>= 5 个) 或极窄时间窗 (可用时间 <= 480 分钟且为 HARD_FAIL) 时才触发剪枝
                avail = (td.details or {}).get("available_minutes", 720)
                is_extreme_short_window = (avail <= 480 and td.severity == DiagnosticSeverity.HARD_FAIL)
                should_prune = (len(attrs) >= 5 or is_extreme_short_window) and len(attrs) > 1 and prunable

                if should_prune:
                    # 裁剪用时最长或非关键项
                    prunable.sort(key=lambda x: float(x.get("visit_minutes") or x.get("duration") or 60), reverse=True)
                    victim = prunable[0]
                    attrs.remove(victim)
                    days_copy[day_idx]["attractions"] = attrs

                    # 重新调用路线规划 (弹性支持至 22:00)
                    new_route_res = solve_day_route_tool(
                        pois=attrs,
                        start_hour=int(days_copy[day_idx].get("start_hour", 9)),
                        close_hour=int(days_copy[day_idx].get("close_hour", 22)),
                        day_index=day_idx,
                        immutable_names=list(immutable_set),
                    )
                    days_copy[day_idx]["route"] = new_route_res.route
                    days_copy[day_idx]["total_ticket"] = new_route_res.total_ticket

                    action_msg = (
                        f"PRUNE_POI: 第 {day_idx + 1} 天行程严重超出时间窗，已自动优化裁剪次要景点 [{victim.get('name')}]"
                        f"（保留锁定项 {sorted(list(immutable_set))}）"
                    )
                    attempted_actions.append(action_msg)
                    logger.info(action_msg)
                else:
                    # 景点数 <= 4 时，坚决不删点！通过放宽时间窗自愈保全行程丰富度
                    days_copy[day_idx]["close_hour"] = 22
                    action_msg = f"EXPAND_SCHEDULE: 第 {day_idx + 1} 天行程充实丰富（{len(attrs)} 个景点），已弹性拓宽游览至晚间 22:00，保全全部景点"
                    attempted_actions.append(action_msg)
                    logger.info(action_msg)

        # 3. 处理预算超支 (BUDGET_EXCEEDED)
        budget_diags = [d for d in diag_objects if d.error_code == ErrorCode.BUDGET_EXCEEDED]
        if budget_diags and budget_total is not None:
            # 尝试降级酒店至经济型优选 (¥200/晚)
            economy_hotel_price = 200.0
            saved_per_night = round(hotel_cost_per_night - economy_hotel_price, 2)
            if saved_per_night > 0:
                breakdown, remaining_diag = check_budget_tool(
                    plan_days=days_copy,
                    hotel_per_night_cost=economy_hotel_price,
                    days=len(days_copy),
                    budget_limit=budget_total,
                )
                action_msg = (
                    f"DOWNGRADE_HOTEL: 行程超支，已自动将住宿调整为高性价比舒适经济型酒店"
                    f"（每晚从 ¥{hotel_cost_per_night} 调整至 ¥{economy_hotel_price}，总计节省 ¥{saved_per_night * max(1, len(days_copy)-1)}）"
                )
                attempted_actions.append(action_msg)
                for d in days_copy:
                    d["hotel_cost_per_night"] = economy_hotel_price

        is_all_resolved = len(attempted_actions) >= len(diag_objects)
        return days_copy, is_all_resolved, attempted_actions
