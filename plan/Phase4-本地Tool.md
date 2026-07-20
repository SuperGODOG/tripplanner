# Phase 4: 本地 Tool 与错误恢复

**目标**：实现 Format/Validate 逻辑（以 Wrapper 形式包装 MCPTool，而非独立 Tool），实现 FallbackTool，加入 conditional edge。

**前置条件**：Phase 3 通过（LangGraph 能编排 4 个 Agent）

**预计时间**：3-4 天 | **代码量**：~250 行

---

## 4.1 为什么用 Wrapper 而非独立 Tool？

回顾之前讨论的结论：FormatTool 和 ValidateTool 不应该作为独立 Tool 暴露给 Agent。原因：

```
❌ 错误做法（原方案）：
Agent → MCPTool → FormatTool → ValidateTool → Agent
Agent 需要知道调完 MCP 还要调 Format 再调 Validate
→ 浪费 LLM 推理轮次
→ Agent 被迫理解数据处理流水线

✅ 正确做法（Wrapper）：
Agent → AmapToolWrapper
              │
              ├─ 内部调 MCPTool
              ├─ 内部格式化
              └─ 内部校验
              → 返回干净结果
Agent 只看到一个 Tool，调一次拿到干净数据
```

---

## 4.2 AmapToolWrapper 实现

创建 `backend/app/tools/amap_wrapper.py`：

```python
"""高德 MCP 工具包装器——内部完成 MCP 调用 + 格式化 + 校验"""
import json
from typing import Any
from hello_agents.tools import Tool, ToolParameter
from ..services.amap_service import get_amap_mcp_tool


class AmapToolWrapper(Tool):
    """
    包装 MCPTool，Agent 只看到这一个工具。

    内部流程:
    1. 调用 MCPTool（amap-mcp-server）
    2. 格式化：提取关键字段，去噪，输出干净文本
    3. 校验：检查必填字段，补默认值
    4. 返回结构化文本

    为什么继承 Tool 而非 MCPTool？
    - MCPTool 是远程工具（启动子进程、JSON-RPC 通信）
    - Wrapper 是本地工具（Agent 进程内执行），只是内部调用了 MCPTool
    - 继承 Tool 让 Agent 看到的是普通本地 Tool
    """

    def __init__(self):
        super().__init__(
            name="amap_search",
            description="搜索景点/酒店/天气。输入 city 和 type（attraction/hotel/weather）",
        )
        self._mcp = get_amap_mcp_tool()

    def get_parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter(
                name="city",
                type="string",
                description="城市名",
                required=True,
            ),
            ToolParameter(
                name="type",
                type="string",
                description="搜索类型：attraction / hotel / weather",
                required=True,
            ),
            ToolParameter(
                name="keywords",
                type="string",
                description="额外关键词（仅 attraction 和 hotel 有效）",
                required=False,
            ),
        ]

    def run(self, parameters: dict) -> str:
        city = parameters["city"]
        search_type = parameters["type"]
        keywords = parameters.get("keywords", "")

        # Step 1: 调 MCP
        raw = self._call_mcp(city, search_type, keywords)

        # Step 2: 格式化
        formatted = self._format(raw, search_type)

        # Step 3: 校验 + 补默认值
        validated = self._validate(formatted, search_type, city)

        return validated

    # ===== 内部方法 =====

    def _call_mcp(self, city: str, search_type: str, keywords: str) -> Any:
        """调用原始 MCP 工具"""
        if search_type == "weather":
            return self._mcp.run({
                "action": "call_tool",
                "tool_name": "maps_weather",
                "arguments": {"city": city},
            })

        # attraction 和 hotel 都用 maps_text_search
        kw = keywords or search_type
        return self._mcp.run({
            "action": "call_tool",
            "tool_name": "maps_text_search",
            "arguments": {
                "keywords": kw,
                "city": city,
                "citylimit": "true",
            },
        })

    def _format(self, raw: Any, search_type: str) -> str:
        """
        格式化：MCP 返回的原始 JSON → 干净的结构化文本。

        不依赖 LLM——纯文本处理。
        提取关键字段，去噪（无用的 metadata），统一输出格式。
        """
        try:
            data = json.loads(str(raw))
        except json.JSONDecodeError:
            return str(raw)  # 无法解析则返回原文

        if search_type == "weather":
            return self._format_weather(data)
        else:
            return self._format_poi(data)

    def _format_weather(self, data: dict) -> str:
        """格式化天气数据"""
        lines = ["【天气信息】"]

        # amap-mcp-server 返回结构可能是 list 或 dict
        forecasts = data.get("forecasts", []) if isinstance(data, dict) else []
        if not forecasts and isinstance(data, list):
            forecasts = data

        for f in forecasts[:7]:  # 最多 7 天
            if isinstance(f, dict):
                date = f.get("date", "未知")
                day_weather = f.get("dayweather", "未知")
                night_weather = f.get("nightweather", "未知")
                day_temp = f.get("daytemp", "?")
                night_temp = f.get("nighttemp", "?")
                wind = f.get("daywind", "未知")
                lines.append(
                    f"- {date}: {day_weather}转{night_weather}, "
                    f"{day_temp}°C/{night_temp}°C, {wind}"
                )
            else:
                lines.append(f"- {f}")

        return "\n".join(lines) if len(lines) > 1 else str(data)

    def _format_poi(self, data: dict) -> str:
        """格式化 POI 搜索结果"""
        lines = ["【搜索结果】"]

        pois = data.get("pois", []) if isinstance(data, dict) else []
        if not pois:
            return f"未找到相关结果\n原始数据: {str(data)[:500]}"

        for poi in pois[:10]:  # 最多 10 条
            name = poi.get("name", "未知")
            address = poi.get("address", "")
            biz_type = poi.get("type", "")
            # adname 是行政区名
            district = poi.get("adname", "")

            line = f"- {name}"
            if address:
                line += f" | {address}"
            if district:
                line += f" | {district}"
            if biz_type:
                line += f" | {biz_type}"
            lines.append(line)

        return "\n".join(lines)

    def _validate(self, formatted: str, search_type: str, city: str) -> str:
        """
        校验：检查结果完整性，补默认值。

        - 如果有结果：直接返回格式化文本
        - 如果无结果（空或只有表头）：返回带标注的降级信息
        """
        # 检查是否为空结果
        content_lines = [l for l in formatted.split("\n") if l.strip()]

        if search_type == "weather" and len(content_lines) <= 1:
            return (
                f"【天气信息】\n"
                f"- {city}: 天气数据暂不可用，请根据季节准备衣物\n"
                f"  建议：春秋季带外套，夏季带防晒，冬季带厚外套"
            )

        if search_type in ("attraction", "hotel") and len(content_lines) <= 1:
            return (
                f"【搜索结果】\n"
                f"- {city}: 未找到相关{search_type}信息\n"
                f"  建议：尝试其他关键词或检查城市名拼写"
            )

        return formatted
```

---

## 4.3 修改 Agent 使用 Wrapper

修改 `backend/app/agents/trip_planner_agent.py` 的 `__init__`：

```python
# Phase 2 的写法（直接加 MCPTool）：
# self.attraction_agent.add_tool(self.amap_tool)

# Phase 4 的写法（加 Wrapper）：
from ..tools.amap_wrapper import AmapToolWrapper

self.amap_wrapper = AmapToolWrapper()

self.attraction_agent.add_tool(self.amap_wrapper)
self.weather_agent.add_tool(self.amap_wrapper)
self.hotel_agent.add_tool(self.amap_wrapper)
# planner_agent 依然不需要工具
```

同时修改 Agent Prompt，因为工具名变了：

```python
# 旧 Prompt: [TOOL_CALL:amap_maps_text_search:keywords=景点,city=北京]
# 新 Prompt: [TOOL_CALL:amap_search:type=attraction,city=北京,keywords=历史文化]

ATTRACTION_AGENT_PROMPT = """...
工具调用格式:
[TOOL_CALL:amap_search:type=attraction,city=城市名,keywords=景点关键词]
"""
```

---

## 4.4 FallbackTool 实现

创建 `backend/app/tools/fallback.py`：

```python
"""降级工具——所有 Agent 失败时生成降级模板"""
from hello_agents.tools import Tool, ToolParameter


class FallbackTool(Tool):
    """当正常流程无法完成时，生成降级行程"""

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
        days = parameters["days"]
        reason = parameters.get("reason", "部分服务暂时不可用")

        plan = {
            "city": city,
            "status": "fallback",
            "reason": reason,
            "days": [],
            "overall_suggestions": (
                f"由于{reason}，生成了{day}天的{city}降级行程。"
                f"建议到达{city}后咨询当地旅游信息中心获取实时推荐。"
            ),
        }

        for i in range(days):
            plan["days"].append({
                "date": f"第{i+1}天",
                "day_index": i,
                "description": f"第{i+1}天：探索{city}（建议咨询当地信息中心）",
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

        import json
        return json.dumps(plan, ensure_ascii=False, indent=2)
```

---

## 4.5 加入 Conditional Edge

修改 `backend/app/graph/builder.py`，加入真正的条件路由：

```python
def build_trip_graph() -> StateGraph:
    graph = StateGraph(TripPlannerState)

    graph.add_node("attraction", attraction_node)
    graph.add_node("weather", weather_node)
    graph.add_node("hotel", hotel_node)
    graph.add_node("planner", planner_node)
    # 新增：降级节点
    graph.add_node("fallback", fallback_node)

    graph.set_entry_point("attraction")

    # 景点 → 天气（无论成功失败都继续）
    graph.add_edge("attraction", "weather")
    # 天气 → 酒店
    graph.add_edge("weather", "hotel")

    # 酒店 → 决策：去规划还是去降级？
    graph.add_conditional_edges(
        "hotel",
        route_after_hotel,
        {
            "planner": "planner",
            "fallback": "fallback",
        },
    )

    graph.add_edge("planner", END)
    graph.add_edge("fallback", END)

    return graph.compile()


def route_after_hotel(state: TripPlannerState) -> str:
    """
    决策逻辑：如果三个数据源全失败 → 降级，否则正常规划。
    """
    failures = 0
    if state.get("attraction_status") == "failed":
        failures += 1
    if state.get("weather_status") == "failed":
        failures += 1
    if state.get("hotel_status") == "failed":
        failures += 1

    if failures == 3:
        return "fallback"
    return "planner"


def fallback_node(state: TripPlannerState) -> dict:
    """降级节点：所有数据源都失败时生成兜底方案"""
    from ..tools.fallback import FallbackTool

    tool = FallbackTool()
    result = tool.run({
        "city": state["city"],
        "days": state["days"],
        "reason": "外部服务全部不可用",
    })

    import json
    return {"final_plan": json.loads(result)}
```

---

## 4.6 验证

```bash
cd backend
source venv/bin/activate
python test_graph.py
```

**Phase 4 通过标准**：
- [ ] AmapToolWrapper 替代原始 MCPTool，Agent 仍能正常工作
- [ ] 格式化输出是干净的文本（非原始 JSON）
- [ ] 校验逻辑在无结果时给出降级信息
- [ ] 三个数据源全失败时，fallback_node 生成兜底方案
- [ ] conditional edge 正确路由

---

## 4.7 架构回顾：为什么是 3 层工具？

Phase 4 完成后的完整工具层次：

```
┌─────────────────────────────────────────────────┐
│              Agent 看到的                        │
│         AmapToolWrapper（一个 Tool）              │
│         FallbackTool（一个 Tool）                 │
│         调一次，拿到干净结果                       │
├─────────────────────────────────────────────────┤
│              Wrapper 内部                        │
│  ① MCP 调用（远程，amap-mcp-server 子进程）       │
│  ② Format（本地，纯 Python 字符串处理）            │
│  ③ Validate（本地，完整性检查 + 默认值）           │
├─────────────────────────────────────────────────┤
│              amap-mcp-server                     │
│  高德地图 API（HTTP 调用）                        │
└─────────────────────────────────────────────────┘
```

Agent 只看到顶层。内部的 Format 和 Validate 是**确定的 Python 代码**，不消耗 LLM token，不占用上下文窗口。

如果面试官问"为什么不把 Format 写成 MCP Server"：答"MCP 适合外部服务调用，Format 是纯计算逻辑，本地执行更轻——不需要进程间通信开销。"
