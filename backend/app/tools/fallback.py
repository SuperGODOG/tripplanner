"""降级工具——所有数据源都失败时的兜底方案

设计原则：
  FallbackTool 是"最后的保险丝"。
  正常流程：Agent 1-3 调 MCP → Planner Agent 整合
  降级流程：三个全失败 → FallbackTool 生成兜底行程

  它不依赖任何外部服务——纯本地生成。
"""
import json
from hello_agents.tools import Tool, ToolParameter


class FallbackTool(Tool):
    """当正常流程无法完成时，生成降级旅行计划"""

    def __init__(self):
        super().__init__(
            name="generate_fallback_plan",
            description="生成降级旅行计划（API 不可用时的兜底方案）",
        )

    def get_parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter(name="city", type="string", required=True),
            ToolParameter(name="days", type="integer", required=True),
            ToolParameter(name="reason", type="string", required=False),
        ]

    def run(self, parameters: dict) -> str:
        city = parameters["city"]
        days = int(parameters["days"])
        reason = parameters.get("reason", "部分服务暂时不可用")

        plan = {
            "city": city,
            "status": "fallback",
            "reason": reason,
            "days": [],
            "overall_suggestions": (
                f"由于{reason}，生成了{days}天的{city}降级行程。"
                f"建议到达{city}后咨询当地旅游信息中心获取实时推荐。"
            ),
            "budget": {"total": 0, "note": "降级方案，无精确预算"},
        }

        for i in range(days):
            plan["days"].append({
                "date": f"第{i+1}天",
                "day_index": i,
                "description": f"第{i+1}天：探索{city}（建议到达后获取实时信息）",
                "attractions": [
                    {
                        "name": f"{city}推荐景点",
                        "description": "请到达后查看实时推荐",
                        "visit_duration": 180,
                    }
                ],
                "meals": [
                    {"type": "breakfast", "name": "当地早餐"},
                    {"type": "lunch", "name": "当地午餐"},
                    {"type": "dinner", "name": "当地晚餐"},
                ],
            })

        return json.dumps(plan, ensure_ascii=False, indent=2)
