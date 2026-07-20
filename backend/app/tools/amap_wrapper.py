"""高德 MCP 工具包装器

设计原则：
- Agent 只看到 ONE tool（amap_search），调一次拿到干净结果
- 内部自动完成三个步骤：MCP 调用 → 格式化 → 校验
- Format 和 Validate 是纯 Python 字符串处理，不消耗 LLM token

为什么不用独立 Tool？
  如果 FormatTool 和 ValidateTool 是独立 Tool，Agent 需要:
    Agent → 调 MCPTool → 读原始 JSON
         → 调 FormatTool → 读格式化文本
         → 调 ValidateTool → 读校验结果
  浪费 3 轮 ReAct，且 Agent 被迫理解数据处理流水线。

  Wrapper 模式:
    Agent → 调 AmapToolWrapper → 拿到干净文本（一次调用）
"""
import json
from typing import Any
from hello_agents.tools import Tool, ToolParameter
from ..services.amap_service import get_amap_mcp_tool


class AmapToolWrapper(Tool):
    """
    包装 MCPTool。

    Agent 视角: 一个名为 amap_search 的工具，输入 city + type，输出干净的文本结果。
    内部: MCP 调用 → 格式化 → 校验，三步一气呵成。
    """

    def __init__(self):
        super().__init__(
            name="amap_search",
            description="搜索景点/酒店/天气。输入 city 和 type（attraction/hotel/weather）",
        )
        self._mcp = get_amap_mcp_tool()

    def get_parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter(name="city", type="string", description="城市名", required=True),
            ToolParameter(name="type", type="string", description="attraction / hotel / weather", required=True),
            ToolParameter(name="keywords", type="string", description="额外关键词（仅 attraction/hotel）", required=False),
        ]

    # ================================================================
    # 公共入口：Agent 只调这个方法
    # ================================================================

    def run(self, parameters: dict) -> str:
        city = parameters["city"]
        search_type = parameters["type"]
        keywords = parameters.get("keywords", "")

        # ── 第 1 层: MCP 调用（远程） ──
        raw = self._call_mcp(city, search_type, keywords)

        # ── 第 2 层: 格式化（本地，纯 Python） ──
        formatted = self._format(raw, search_type)

        # ── 第 3 层: 校验 + 默认值（本地，纯 Python） ──
        validated = self._validate(formatted, search_type, city)

        return validated

    # ================================================================
    # 第 1 层: MCP 调用
    # ================================================================

    def _call_mcp(self, city: str, search_type: str, keywords: str) -> Any:
        """调用原始 MCP 工具"""
        if search_type == "weather":
            return self._mcp.run({
                "action": "call_tool",
                "tool_name": "maps_weather",
                "arguments": {"city": city},
            })

        kw = keywords or search_type
        return self._mcp.run({
            "action": "call_tool",
            "tool_name": "maps_text_search",
            "arguments": {"keywords": kw, "city": city, "citylimit": "true"},
        })

    def _extract_json_from_mcp_result(self, raw_str: str) -> Any:
        """从 MCPTool 返回的带前缀字符串中提取 JSON。

        MCPTool.run() 返回格式: "工具 'xxx' 执行结果:\\n{json}"
        本方法剥离前缀并解析 JSON。
        """
        # Try stripping MCP wrapper prefix: 工具 'toolname' 执行结果:\n
        import re
        m = re.match(r"工具\s+'[^']*'\s+执行结果:\s*\n", raw_str)
        if m:
            json_str = raw_str[m.end():]
            try:
                return json.loads(json_str)
            except json.JSONDecodeError:
                pass
        return None

    # ================================================================
    # 第 2 层: 格式化（纯 Python，不调 LLM）
    # ================================================================

    def _format(self, raw: Any, search_type: str) -> str:
        """
        原始 JSON → 干净的结构化文本。

        为什么不用 LLM 格式化？
        - LLM 格式化消耗 token，挤占 Agent 的上下文窗口
        - LLM 可能误解 JSON 结构，产生幻觉
        - 纯 Python 格式化是确定性的，100% 可控
        """
        raw_str = str(raw)
        try:
            data = json.loads(raw_str)
        except json.JSONDecodeError:
            # MCPTool.run() wraps result with "工具 'xxx' 执行结果:\n" prefix,
            # strip it and retry parsing
            data = self._extract_json_from_mcp_result(raw_str)

        if data is None:
            return raw_str

        if search_type == "weather":
            return self._format_weather(data)
        else:
            return self._format_poi(data, search_type)

    def _format_weather(self, data: dict) -> str:
        """天气 JSON → 可读文本"""
        lines = ["【天气信息】"]

        forecasts = data.get("forecasts", []) if isinstance(data, dict) else []
        if not forecasts and isinstance(data, list):
            forecasts = data

        for f in forecasts[:7]:
            if isinstance(f, dict):
                date = f.get("date", "未知")
                day_w = f.get("dayweather", "?")
                night_w = f.get("nightweather", "?")
                day_t = f.get("daytemp", "?")
                night_t = f.get("nighttemp", "?")
                wind = f.get("daywind", "?")
                lines.append(f"- {date}: {day_w}转{night_w}, {day_t}°C~{night_t}°C, {wind}风")
            else:
                lines.append(f"- {f}")

        return "\n".join(lines) if len(lines) > 1 else str(data)

    def _format_poi(self, data: dict, search_type: str) -> str:
        """POI 搜索结果 JSON → 可读文本"""
        label = "景点" if search_type == "attraction" else "酒店"
        lines = [f"【{label}搜索结果】"]

        pois = data.get("pois", []) if isinstance(data, dict) else []
        if not pois:
            return f"未找到{label}"

        for i, poi in enumerate(pois[:10], 1):
            name = poi.get("name", "未知")
            address = poi.get("address", "")
            district = poi.get("adname", "")

            parts = [f"{i}. {name}"]
            if district:
                parts.append(f"[{district}]")
            if address:
                parts.append(address)
            lines.append(" | ".join(parts))

        return "\n".join(lines)

    # ================================================================
    # 第 3 层: 校验（纯 Python）
    # ================================================================

    def _validate(self, formatted: str, search_type: str, city: str) -> str:
        """
        检查结果完整性，补默认值。

        校验规则：
        - 天气：至少有一条预报
        - 景点/酒店：至少有一个 POI 结果
        - 如果不满足 → 返回带标注的降级信息（而非抛异常）
        """
        content_lines = [l for l in formatted.split("\n") if l.strip() and not l.startswith("【")]

        if search_type == "weather" and len(content_lines) == 0:
            return (
                f"【天气信息】\n"
                f"- {city}: 天气数据暂不可用\n"
                f"  建议：春秋季带外套，夏季注意防晒，冬季穿厚外套"
            )

        if search_type in ("attraction", "hotel") and len(content_lines) == 0:
            return (
                f"【{search_type}搜索结果】\n"
                f"- {city}: 暂无数据，请在到达{city}后咨询当地旅游信息中心"
            )

        return formatted
