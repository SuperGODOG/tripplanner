# Phase 2: 4 Agent 定义与独立调通

**目标**：定义 4 个 SimpleAgent（景点/天气/酒店/规划），各配 Prompt，共享 MCPTool，逐个独立验证。

**前置条件**：Phase 1 通过（MCP 能调通高德 API）

**预计时间**：3-4 天 | **代码量**：~250 行

---

## 2.1 设计思路

```
┌──────────────────────────────────────────────────┐
│                 LLM Service（单例）                │
│            HelloAgentsLLM(DeepSeek)               │
└──────────┬──────────┬──────────┬─────────────────┘
           │          │          │
    ┌──────▼───┐ ┌───▼────┐ ┌──▼──────┐ ┌──────────┐
    │ 景点Agent │ │天气Agent│ │酒店Agent│ │规划Agent  │
    │ SimpleAgt │ │SimpleAg│ │SimpleAg │ │SimpleAg  │
    │  + MCP   │ │ + MCP  │ │ + MCP  │ │ (无工具)  │
    └──────────┘ └────────┘ └────────┘ └──────────┘
           │          │          │
           └──────────┴──────────┘
                      │
            ┌─────────▼─────────┐
            │  共享 MCPTool      │
            │  (只建一次连接)     │
            └───────────────────┘
```

**关键设计决策**：4 个 Agent 共用一个 MCPTool 实例。
- 每个 MCPTool 启动一个 amap-mcp-server 子进程（约 500ms 握手）
- 共用避免重复建连，节省启动时间和系统资源
- HelloAgents 框架在每次调用时带 session_id 区分来源

---

## 2.2 LLM 服务

创建 `backend/app/services/llm_service.py`：

```python
"""LLM 服务"""
from hello_agents import HelloAgentsLLM
from ..config import get_settings

_llm: HelloAgentsLLM | None = None


def get_llm() -> HelloAgentsLLM:
    """获取 LLM 实例（单例）"""
    global _llm

    if _llm is None:
        settings = get_settings()
        _llm = HelloAgentsLLM(
            api_key=settings.llm_api_key,
            model=settings.llm_model_id,
            base_url=settings.llm_base_url,
        )

    return _llm
```

---

## 2.3 4 个 Agent 的 Prompt 设计

### Agent 1: 景点搜索

```
你是景点搜索专家。根据城市和用户偏好搜索合适的景点。

必须使用工具搜索景点，不要自己编造信息。

工具调用格式:
[TOOL_CALL:amap_maps_text_search:keywords=景点关键词,city=城市名]

示例:
用户: "搜索北京的历史文化景点"
回复: [TOOL_CALL:amap_maps_text_search:keywords=历史文化,city=北京]
```

### Agent 2: 天气查询

```
你是天气查询专家。查询指定城市的天气信息。

必须使用工具查询天气，不要自己编造天气信息。

工具调用格式:
[TOOL_CALL:amap_maps_weather:city=城市名]

示例:
用户: "查询北京天气"
回复: [TOOL_CALL:amap_maps_weather:city=北京]
```

### Agent 3: 酒店推荐

```
你是酒店推荐专家。根据城市和景点位置推荐合适的酒店。

必须使用工具搜索酒店，不要自己编造酒店信息。

工具调用格式:
[TOOL_CALL:amap_maps_text_search:keywords=酒店,city=城市名]

示例:
用户: "搜索北京的酒店"
回复: [TOOL_CALL:amap_maps_text_search:keywords=酒店,city=北京]
```

### Agent 4: 行程规划

```
你是行程规划专家。根据景点信息、天气信息、酒店信息，生成详细的旅行计划。

请严格按照以下 JSON 格式返回:
{
  "city": "城市名",
  "start_date": "YYYY-MM-DD",
  "end_date": "YYYY-MM-DD",
  "days": [
    {
      "date": "YYYY-MM-DD",
      "day_index": 0,
      "description": "第1天概述",
      "transportation": "交通方式",
      "accommodation": "住宿类型",
      "attractions": [
        {
          "name": "景点名",
          "address": "地址",
          "location": {"longitude": 116.39, "latitude": 39.91},
          "visit_duration": 120,
          "description": "景点描述",
          "ticket_price": 60
        }
      ],
      "meals": [
        {"type": "breakfast", "name": "早餐", "estimated_cost": 30},
        {"type": "lunch", "name": "午餐", "estimated_cost": 50},
        {"type": "dinner", "name": "晚餐", "estimated_cost": 80}
      ]
    }
  ],
  "weather_info": [...],
  "overall_suggestions": "总体建议",
  "budget": {"total": 2000}
}

重要:
1. 每天安排 2-3 个景点
2. 每天必须包含早中晚三餐
3. 温度必须是纯数字（不要带 °C）
4. 必须包含预算信息
```

---

## 2.4 Agent 系统实现

创建 `backend/app/agents/trip_planner_agent.py`：

```python
"""多智能体旅行规划系统"""
import json
from typing import Dict, Any
from hello_agents import SimpleAgent
from hello_agents.tools import MCPTool
from ..services.llm_service import get_llm
from ..services.amap_service import get_amap_mcp_tool
from ..config import get_settings

# ============ Agent Prompts ============

ATTRACTION_AGENT_PROMPT = """你是景点搜索专家..."""  # 见 2.3
WEATHER_AGENT_PROMPT = """你是天气查询专家..."""
HOTEL_AGENT_PROMPT = """你是酒店推荐专家..."""
PLANNER_AGENT_PROMPT = """你是行程规划专家..."""


class MultiAgentTripPlanner:
    """多智能体旅行规划系统"""

    def __init__(self):
        print("🔄 初始化多智能体系统...")

        self.llm = get_llm()

        # 共享 MCPTool（只建一次）
        self.amap_tool = get_amap_mcp_tool()

        # Agent 1: 景点搜索
        self.attraction_agent = SimpleAgent(
            name="景点搜索专家",
            llm=self.llm,
            system_prompt=ATTRACTION_AGENT_PROMPT
        )
        self.attraction_agent.add_tool(self.amap_tool)

        # Agent 2: 天气查询
        self.weather_agent = SimpleAgent(
            name="天气查询专家",
            llm=self.llm,
            system_prompt=WEATHER_AGENT_PROMPT
        )
        self.weather_agent.add_tool(self.amap_tool)

        # Agent 3: 酒店推荐
        self.hotel_agent = SimpleAgent(
            name="酒店推荐专家",
            llm=self.llm,
            system_prompt=HOTEL_AGENT_PROMPT
        )
        self.hotel_agent.add_tool(self.amap_tool)

        # Agent 4: 行程规划（不需要工具）
        self.planner_agent = SimpleAgent(
            name="行程规划专家",
            llm=self.llm,
            system_prompt=PLANNER_AGENT_PROMPT
        )

        print("✅ 多智能体系统初始化完成")

    def plan_trip(self, city: str, days: int, preferences: list[str] = None) -> dict:
        """生成旅行计划（Phase 2 用顺序调用验证，Phase 3 改为 LangGraph）"""
        print(f"\n🚀 开始规划: {city}, {days}天")

        # Step 1: 景点搜索
        print("📍 Step 1: 搜索景点...")
        attraction_query = f"请搜索{city}的景点。\n[TOOL_CALL:amap_maps_text_search:keywords=景点,city={city}]"
        attraction_result = self.attraction_agent.run(attraction_query)

        # Step 2: 天气查询
        print("🌤  Step 2: 查询天气...")
        weather_query = f"请查询{city}的天气。\n[TOOL_CALL:amap_maps_weather:city={city}]"
        weather_result = self.weather_agent.run(weather_query)

        # Step 3: 酒店搜索
        print("🏨 Step 3: 搜索酒店...")
        hotel_query = f"请搜索{city}的酒店。\n[TOOL_CALL:amap_maps_text_search:keywords=酒店,city={city}]"
        hotel_result = self.hotel_agent.run(hotel_query)

        # Step 4: 行程规划
        print("📋 Step 4: 生成行程...")
        planner_query = f"""请根据以下信息生成{city}的{days}天旅行计划:

景点信息:
{attraction_result}

天气信息:
{weather_result}

酒店信息:
{hotel_result}

偏好: {', '.join(preferences) if preferences else '无'}
"""
        plan_result = self.planner_agent.run(planner_query)

        # 解析 JSON
        return self._parse_plan(plan_result)

    def _parse_plan(self, response: str) -> dict:
        """从 Agent 响应中提取 JSON"""
        # 找 JSON 块
        if "```json" in response:
            start = response.find("```json") + 7
            end = response.find("```", start)
            return json.loads(response[start:end])
        elif "{" in response and "}" in response:
            start = response.find("{")
            end = response.rfind("}") + 1
            return json.loads(response[start:end])
        raise ValueError("响应中未找到 JSON")


# 全局单例
_planner: MultiAgentTripPlanner | None = None


def get_planner() -> MultiAgentTripPlanner:
    global _planner
    if _planner is None:
        _planner = MultiAgentTripPlanner()
    return _planner
```

---

## 2.5 验证脚本

创建 `backend/test_agents.py`：

```python
"""Phase 2 验证：逐个 Agent 独立调通"""
import sys
sys.path.insert(0, ".")

from app.agents.trip_planner_agent import get_planner

def test_plan_trip():
    planner = get_planner()
    result = planner.plan_trip(
        city="北京",
        days=3,
        preferences=["历史文化", "美食"]
    )

    print(f"\n城市: {result.get('city')}")
    print(f"天数: {len(result.get('days', []))}")
    print(f"预算: {result.get('budget', {}).get('total')}")

    for day in result.get('days', []):
        print(f"\n  {day['date']}: {day['description']}")
        for attr in day.get('attractions', []):
            print(f"    🏛 {attr['name']}")

    return True

if __name__ == "__main__":
    try:
        test_plan_trip()
        print("\n🎉 Phase 2 验证通过！")
    except Exception as e:
        print(f"\n❌ 失败: {e}")
```

---

## 2.6 验证标准

```bash
cd backend
source venv/bin/activate
python test_agents.py
```

- [ ] 景点 Agent 成功搜索并返回景点数据
- [ ] 天气 Agent 成功查询并返回天气数据
- [ ] 酒店 Agent 成功搜索并返回酒店数据
- [ ] 规划 Agent 成功整合前三者输出完整 JSON
- [ ] JSON 包含 city, days, attractions, meals, budget

---

## 2.7 当前架构的问题（Phase 3 要解决）

Phase 2 的 `plan_trip()` 方法是**硬编码的顺序调用**：

```python
attraction_result = self.attraction_agent.run(...)
weather_result = self.weather_agent.run(...)
hotel_result = self.hotel_agent.run(...)
plan_result = self.planner_agent.run(...)
```

问题：
1. 如果景点 Agent 失败，没有降级逻辑（直接抛异常）
2. 状态无法持久化（中断后无法恢复）
3. 流程不可视化

Phase 3 用 LangGraph 解决这些问题。
