"""旅行业务领域不变式断言器 (Travel Domain Invariants)

提供运行态不变式裁决能力：
将原本隐藏在图节点深处的业务规则提取为透明、可自解释的领域契约。
在 Agent 主循环执行过程中即时评估，若破坏不变式则产出结构化违规清单，指导模型即时自愈。
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class TravelInvariants:
    """旅行规划核心领域不变式"""

    @staticmethod
    def verify_plan(plan: dict[str, Any], budget_limit: float | None = None) -> list[str]:
        """全面审计行程版本，返回违规列表 (空列表表示完全合规)"""
        violations: list[str] = []
        days = plan.get("days", [])
        if not days:
            violations.append("行程不能为空：未包含任何有效天数计划")
            return violations

        total_cost = 0.0

        for d_idx, day in enumerate(days):
            day_num = day.get("day_number", d_idx + 1)
            attrs = day.get("attractions", [])

            # 不变式 1: 每日景点数下限
            if len(attrs) < 1:
                violations.append(f"第 {day_num} 天景点数不足：必须至少规划 1 处游览地点")

            # 不变式 2: 景点池纯洁性 (严禁餐饮/商场/网咖商业项目混入景点)
            for a in attrs:
                name = str(a.get("name", "") or "")
                tcode = str(a.get("typecode", "") or "")
                cat = str(a.get("category", "") or "")

                if tcode.startswith(("05", "07", "0803", "12", "15")):
                    violations.append(f"第 {day_num} 天景点池污染：【{name}】为商业/服务设施，不得作为旅游名胜")
                if any(bad in name for bad in ("火锅", "烤肉", "饭店", "餐厅", "牛肉", "烤鱼", "专卖店", "工厂店")):
                    violations.append(f"第 {day_num} 天景点池污染：【{name}】包含餐饮/商铺关键字，违背人文自然名胜原则")

                price = float(a.get("price") or a.get("ticket_price") or 0.0)
                total_cost += price

            # 不变式 3: 住宿与选址必须存在
            hotel = day.get("hotel") or {}
            if not hotel or not hotel.get("name"):
                violations.append(f"第 {day_num} 天缺少推荐住宿：必须提供 Minimax 最优选址酒店")
            else:
                hotel_price = float(hotel.get("price_per_night") or hotel.get("price") or 400.0)
                total_cost += hotel_price

            # 不变式 4: 三餐完整性
            meals = day.get("meals") or []
            if len(meals) < 3:
                violations.append(f"第 {day_num} 天餐饮不全：必须完整覆盖早、中、晚三餐 (当前仅 {len(meals)} 餐)")

        # 不变式 5: 预算上限硬约束
        if budget_limit and budget_limit > 0:
            if total_cost > budget_limit * 1.05:  # 允许 5% 浮动
                violations.append(f"总预算超标：当前总花费约 ¥{int(total_cost)}，超出设定上限 ¥{int(budget_limit)}")

        return violations
