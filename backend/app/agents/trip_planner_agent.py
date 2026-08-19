"""行程规划 Agent — 图内唯一 LLM 节点

架构（2026-08 重构）:
  attraction/hotel 已改为确定性检索节点（AmapToolWrapper.search_pois 直连），
  不再经过 LLM 转发。本文件只保留 Planner Agent：
  - 输入: 结构化候选生成的文本（景点/酒店/天气/偏好/预算/时间槽）
  - 输出: 完整行程 JSON（_parse_plan 容错解析）
  - 三餐: 由 nodes._enrich_meals 用真实美食 POI 填充，LLM 不编餐厅
"""
import json
from hello_agents import SimpleAgent
from ..services.llm_service import get_llm, retry_with_backoff


# ============================================================
# Planner Prompt
# ============================================================

PLANNER_AGENT_PROMPT = """你是行程规划专家。你的任务是根据系统提供的景点信息、天气信息、酒店信息，生成详细的旅行计划。

请严格按照以下 JSON 格式返回旅行计划:
```json
{
  "city": "城市名称",
  "start_date": "YYYY-MM-DD",
  "end_date": "YYYY-MM-DD",
  "days": [
    {
      "date": "YYYY-MM-DD",
      "day_index": 0,
      "description": "第1天行程概述",
      "transportation": "交通方式",
      "accommodation": "住宿类型",
      "hotel": {
        "name": "推荐酒店名称",
        "address": "酒店地址",
        "location": {"longitude": 116.397128, "latitude": 39.916527},
        "price_range": "300-500元",
        "rating": "4.5",
        "distance": "距离景点2公里",
        "type": "经济型酒店",
        "estimated_cost": 400
      },
      "attractions": [
        {
          "name": "景点名称",
          "address": "详细地址",
          "location": {"longitude": 116.397128, "latitude": 39.916527},
          "visit_duration": 120,
          "description": "景点详细描述",
          "category": "景点类别",
          "ticket_price": 60
        }
      ],
      "meals": [
        {"type": "breakfast", "name": "早餐推荐", "description": "早餐描述", "estimated_cost": 30},
        {"type": "lunch", "name": "午餐推荐", "description": "午餐描述", "estimated_cost": 50},
        {"type": "dinner", "name": "晚餐推荐", "description": "晚餐描述", "estimated_cost": 80}
      ]
    }
  ],
  "weather_info": [
    {
      "date": "YYYY-MM-DD",
      "day_weather": "晴",
      "night_weather": "多云",
      "day_temp": 25,
      "night_temp": 15,
      "wind_direction": "南风",
      "wind_power": "1-3级"
    }
  ],
  "overall_suggestions": "总体建议",
  "budget": {
    "total_attractions": 180,
    "total_hotels": 1200,
    "total_meals": 480,
    "total_transportation": 200,
    "total": 2060
  }
}
```

**重要提示:**
1. weather_info 数组必须包含每一天的天气信息
2. 温度必须是纯数字（不要带°C等单位）
3. 每天安排2-3个景点
4. 每天必须推荐一个具体酒店（从酒店信息中选择，含名称/地址/价格/评分）
5. 考虑景点之间的距离和游览时间
6. 每天必须包含早中晚三餐，但**不要编造餐厅名称**：meals 数组留空或只写类型，系统会用当天景点周边 500m 的真实餐厅填充
7. 提供实用的旅行建议
8. 必须包含预算信息（含酒店费用）
9. 景点名称必须从提供的景点信息中选择，不得凭空捏造；标记【远郊】的景点应安排为单独一日游（早出晚归，当天只去该方向景点）
"""


# ============================================================
# Planner 单例封装
# ============================================================

class MultiAgentTripPlanner:
    """行程规划器 — 图内唯一 LLM 节点。

    架构（2026-08 重构后）:
    ┌────────────────┐   ┌────────────────┐
    │ attraction_node │   │   memory_node  │  确定性节点（直连 MCP，无 LLM）
    │  搜索+去重+质心  │   │   租户记忆读取   │
    └───────┬────────┘   └───────┬────────┘
            │ hotel_node         │        确定性节点（中心周边酒店）
            └─────────┬──────────┘
                 ┌────▼─────┐
                 │ planner  │── 唯一 LLM 调用（SimpleAgent，无工具）
                 └──────────┘
    """

    def __init__(self):
        print("🔄 初始化行程规划器...")
        self.llm = get_llm()
        self.planner_agent = SimpleAgent(
            name="行程规划专家",
            llm=self.llm,
            system_prompt=PLANNER_AGENT_PROMPT,
        )
        print("✅ 行程规划器初始化完成（planner_agent，无工具，纯推理）")

    def _run_agent_with_retry(self, agent, prompt: str, max_retries=3) -> str:
        """带指数退避重试的 agent.run() 包装，处理 LLM API 临时故障。"""
        return retry_with_backoff(
            lambda: agent.run(prompt),
            max_retries=max_retries,
        )

    # ============================================================
    # 解析
    # ============================================================

    def _parse_plan(self, response: str) -> dict:
        """从 Agent 响应中提取 JSON 结构（容错：缺起始围栏/多余文本）。"""
        if "```json" in response:
            start = response.find("```json") + 7
            end = response.find("```", start)
            if end == -1:
                raise ValueError("JSON 代码围栏未闭合")
            return json.loads(response[start:end].strip())
        elif "```" in response and "{" in response:
            start = response.find("```") + 3
            end = response.find("```", start)
            if end == -1:
                raise ValueError("JSON 代码围栏未闭合")
            return json.loads(response[start:end].strip())
        elif "{" in response and "}" in response:
            start = response.find("{")
            end = response.rfind("}") + 1
            return json.loads(response[start:end])
        else:
            raise ValueError(f"无法从响应中提取 JSON，响应内容: {response[:500]}...")


# ============================================================
# 全局单例
# ============================================================

_planner: MultiAgentTripPlanner | None = None


def get_planner() -> MultiAgentTripPlanner:
    """获取 MultiAgentTripPlanner 单例（planner_agent + LLM 只初始化一次）。"""
    global _planner
    if _planner is None:
        _planner = MultiAgentTripPlanner()
    return _planner
