"""多智能体旅行规划系统

Phase 2: 4 个 SimpleAgent + 共享 MCPTool + 顺序编排
Phase 3: 迁移到 LangGraph StateGraph
"""
import json
from hello_agents import SimpleAgent
from ..services.llm_service import get_llm
from ..services.amap_service import get_amap_mcp_tool


# ============================================================
# Agent Prompts
# ============================================================
# 每个 Agent 的 system_prompt 定义了它的角色、可用工具、输出格式。
# [TOOL_CALL:tool_name:params] 是 HelloAgents 的工具调用语法。
# Agent（LLM）在 ReAct 循环中输出这个格式 → 框架解析 → 调工具 → 返回结果。

ATTRACTION_AGENT_PROMPT = """你是景点搜索专家。你的任务是根据城市和用户偏好搜索合适的景点。

**重要提示:**
你必须使用工具来搜索景点！不要自己编造景点信息！

**工具调用格式:**
使用 maps_text_search 工具时，必须严格按照以下格式:
`[TOOL_CALL:amap_maps_text_search:keywords=景点关键词,city=城市名]`

**示例:**
用户: "搜索北京的历史文化景点"
你的回复: [TOOL_CALL:amap_maps_text_search:keywords=历史文化,city=北京]

用户: "搜索上海的公园"
你的回复: [TOOL_CALL:amap_maps_text_search:keywords=公园,city=上海]

**注意:**
1. 必须使用工具，不要直接回答
2. 格式必须完全正确，包括方括号和冒号
3. 参数用逗号分隔
"""

WEATHER_AGENT_PROMPT = """你是天气查询专家。你的任务是查询指定城市的天气信息。

**重要提示:**
你必须使用工具来查询天气！不要自己编造天气信息！

**工具调用格式:**
使用 maps_weather 工具时，必须严格按照以下格式:
`[TOOL_CALL:amap_maps_weather:city=城市名]`

**示例:**
用户: "查询北京天气"
你的回复: [TOOL_CALL:amap_maps_weather:city=北京]

用户: "上海的天气怎么样"
你的回复: [TOOL_CALL:amap_maps_weather:city=上海]

**注意:**
1. 必须使用工具，不要直接回答
2. 格式必须完全正确，包括方括号和冒号
"""

HOTEL_AGENT_PROMPT = """你是酒店推荐专家。你的任务是根据城市和景点位置推荐合适的酒店。

**重要提示:**
你必须使用工具来搜索酒店！不要自己编造酒店信息！

**工具调用格式:**
使用 maps_text_search 工具搜索酒店时，必须严格按照以下格式:
`[TOOL_CALL:amap_maps_text_search:keywords=酒店,city=城市名]`

**示例:**
用户: "搜索北京的酒店"
你的回复: [TOOL_CALL:amap_maps_text_search:keywords=酒店,city=北京]

**注意:**
1. 必须使用工具，不要直接回答
2. 格式必须完全正确，包括方括号和冒号
3. 关键词使用"酒店"或"宾馆"
"""

PLANNER_AGENT_PROMPT = """你是行程规划专家。你的任务是根据景点信息、天气信息、酒店信息，生成详细的旅行计划。

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
6. 每天必须包含早中晚三餐
7. 提供实用的旅行建议
8. 必须包含预算信息（含酒店费用）
"""


# ============================================================
# MultiAgentTripPlanner
# ============================================================

class MultiAgentTripPlanner:
    """
    多智能体旅行规划系统。

    架构:
    ┌─────────────┐  ┌───────────┐  ┌───────────┐  ┌───────────┐
    │ Attraction  │  │  Weather   │  │   Hotel    │  │  Planner  │
    │   Agent     │  │   Agent    │  │   Agent    │  │   Agent   │
    │ + MCPTool   │  │ + MCPTool  │  │ + MCPTool  │  │ (无工具)  │
    └─────────────┘  └───────────┘  └───────────┘  └───────────┘
           │               │               │
           └───────────────┴───────────────┘
                           │
                 ┌─────────▼─────────┐
                 │  共享 MCPTool      │
                 │  (一个实例)        │
                 └───────────────────┘

    4 个 Agent 共用一个 MCPTool 实例:
    - 每个 MCPTool = 一个 amap-mcp-server 子进程 (~500ms 握手)
    - 共享避免重复建连，节省启动时间
    - HelloAgents 框架自动带 session_id 区分调用来源
    """

    def __init__(self):
        print("🔄 初始化多智能体旅行规划系统...")

        self.llm = get_llm()

        # 共享 MCPTool（只建一次连接）
        print("  - 创建共享 MCP 工具...")
        self.amap_tool = get_amap_mcp_tool()

        # Agent 1: 景点搜索
        print("  - 创建景点搜索 Agent...")
        self.attraction_agent = SimpleAgent(
            name="景点搜索专家",
            llm=self.llm,
            system_prompt=ATTRACTION_AGENT_PROMPT,
        )
        self.attraction_agent.add_tool(self.amap_tool)

        # Agent 2: 天气查询
        print("  - 创建天气查询 Agent...")
        self.weather_agent = SimpleAgent(
            name="天气查询专家",
            llm=self.llm,
            system_prompt=WEATHER_AGENT_PROMPT,
        )
        self.weather_agent.add_tool(self.amap_tool)

        # Agent 3: 酒店推荐
        print("  - 创建酒店推荐 Agent...")
        self.hotel_agent = SimpleAgent(
            name="酒店推荐专家",
            llm=self.llm,
            system_prompt=HOTEL_AGENT_PROMPT,
        )
        self.hotel_agent.add_tool(self.amap_tool)

        # Agent 4: 行程规划（不需要工具——纯 LLM 推理）
        print("  - 创建行程规划 Agent...")
        self.planner_agent = SimpleAgent(
            name="行程规划专家",
            llm=self.llm,
            system_prompt=PLANNER_AGENT_PROMPT,
        )
        # 注意：planner_agent 不添加任何工具！

        print(f"✅ 多智能体系统初始化完成")
        print(f"   景点 Agent: {len(self.attraction_agent.list_tools())} 个工具")
        print(f"   天气 Agent: {len(self.weather_agent.list_tools())} 个工具")
        print(f"   酒店 Agent: {len(self.hotel_agent.list_tools())} 个工具")
        print(f"   规划 Agent: {len(self.planner_agent.list_tools())} 个工具（无工具，纯推理）")

    # ============================================================
    # Phase 2: 顺序编排（Phase 3 将替换为 LangGraph）
    # ============================================================

    def plan_trip(self, city: str, days: int, preferences: list[str] = None) -> dict:
        """
        使用 4 个 Agent 协作生成旅行计划。

        当前实现（Phase 2）: 硬编码顺序调用
        Phase 3 改为: LangGraph StateGraph + conditional edge
        """
        if preferences is None:
            preferences = []

        print(f"\n{'='*60}")
        print(f"🚀 开始多智能体协作规划旅行")
        print(f"   目的地: {city}")
        print(f"   天数: {days}天")
        print(f"   偏好: {', '.join(preferences) if preferences else '无'}")
        print(f"{'='*60}\n")

        # ── Step 1: 景点搜索 ──
        print("📍 Step 1/4: 景点搜索 Agent 工作中...")
        attraction_query = (
            f"请搜索{city}的景点。\n"
            f"[TOOL_CALL:amap_maps_text_search:keywords=景点,city={city}]"
        )
        attraction_result = self.attraction_agent.run(attraction_query)

        # ── Step 2: 天气查询 ──
        print("🌤  Step 2/4: 天气查询 Agent 工作中...")
        weather_query = (
            f"请查询{city}的天气信息。\n"
            f"[TOOL_CALL:amap_maps_weather:city={city}]"
        )
        weather_result = self.weather_agent.run(weather_query)

        # ── Step 3: 酒店搜索 ──
        print("🏨 Step 3/4: 酒店推荐 Agent 工作中...")
        hotel_query = (
            f"请搜索{city}的酒店。\n"
            f"[TOOL_CALL:amap_maps_text_search:keywords=酒店,city={city}]"
        )
        hotel_result = self.hotel_agent.run(hotel_query)

        # ── Step 4: 行程规划 ──
        print("📋 Step 4/4: 行程规划 Agent 工作中...")
        planner_query = f"""请根据以下信息生成{city}的{days}天旅行计划:

**景点信息:**
{attraction_result}

**天气信息:**
{weather_result}

**酒店信息:**
{hotel_result}

**用户偏好:** {', '.join(preferences) if preferences else '无'}
"""
        planner_result = self.planner_agent.run(planner_query)

        # 解析 JSON
        plan = self._parse_plan(planner_result)

        return plan

    # ============================================================
    # 辅助方法
    # ============================================================

    def _parse_plan(self, response: str) -> dict:
        """从 Agent 响应中提取 JSON 结构"""
        if "```json" in response:
            start = response.find("```json") + 7
            end = response.find("```", start)
            return json.loads(response[start:end].strip())
        elif "```" in response and "{" in response:
            start = response.find("```") + 3
            end = response.find("```", start)
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
    """
    获取 MultiAgentTripPlanner 单例。

    单例保证:
    - MCPTool 只启动一次（避免重复建子进程）
    - 4 个 Agent 只创建一次
    - 所有 API 请求复用同一个实例
    """
    global _planner
    if _planner is None:
        _planner = MultiAgentTripPlanner()
    return _planner
