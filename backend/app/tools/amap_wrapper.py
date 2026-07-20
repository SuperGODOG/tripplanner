"""高德 MCP 工具包装器

设计原则：
- Agent 只看到 ONE tool（amap_search），调一次拿到干净结果
- 内部自动完成: MCP 调用 → 坐标增强 → 格式化 → 校验
- POI 类查询自动并发调 maps_geo 为每个结果补坐标
- 天气类查询跳过坐标增强

Wrapper 内部路径:
  params["type"]=="attraction"→ MCP → geo 增强 → format → validate
  params["type"]=="hotel"     → MCP → geo 增强 → format → validate
  params["type"]=="weather"   → MCP → format → validate（跳过 geo）
  params["type"]=="around"    → 新路径: maps_around（周边搜索，自带坐标）
"""
import json, re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from hello_agents.tools import Tool, ToolParameter
from ..services.amap_service import get_amap_mcp_tool


class AmapToolWrapper(Tool):

    def __init__(self):
        super().__init__(
            name="amap_search",
            description="搜索景点/酒店/天气。输入 city 和 type（attraction/hotel/weather/around）",
        )
        self._mcp = get_amap_mcp_tool()
        self._executor = ThreadPoolExecutor(max_workers=5)

    def get_parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter(name="city", type="string", description="城市名", required=True),
            ToolParameter(name="type", type="string",
                          description="attraction / hotel / weather / around", required=True),
            ToolParameter(name="keywords", type="string", description="额外关键词", required=False),
            ToolParameter(name="center", type="string",
                          description="周边搜索中心坐标 lng,lat（仅 type=around 时使用）", required=False),
            ToolParameter(name="radius", type="string",
                          description="周边搜索半径（米），仅 type=around 时使用，默认 5000", required=False),
        ]

    # ================================================================
    # 公共入口
    # ================================================================

    def run(self, parameters: dict) -> str:
        city = parameters["city"]
        stype = parameters["type"]
        kw = parameters.get("keywords", "")
        center = parameters.get("center", "")
        radius = parameters.get("radius", "")

        # ── 第 1 层: MCP 调用 ──
        raw = self._call_mcp(city, stype, kw, center, radius)

        # ── 第 1.5 层: 坐标增强（仅 POI 类，条件触发）──
        if stype in ("attraction", "hotel"):
            raw = self._enrich_pois_with_coords(raw)

        # ── 第 2 层: 格式化 ──
        formatted = self._format(raw, stype)

        # ── 第 3 层: 校验 ──
        return self._validate(formatted, stype, city)

    # ================================================================
    # 第 1 层: MCP 调用
    # ================================================================

    def _call_mcp(self, city: str, stype: str, kw: str, center: str, radius: str = "") -> Any:
        if stype == "weather":
            return self._mcp.run({
                "action": "call_tool", "tool_name": "maps_weather",
                "arguments": {"city": city},
            })
        if stype == "around" and center:
            return self._mcp.run({
                "action": "call_tool", "tool_name": "maps_around",
                "arguments": {"location": center, "keywords": kw or "酒店", "radius": radius or "5000"},
            })
        return self._mcp.run({
            "action": "call_tool", "tool_name": "maps_text_search",
            "arguments": {"keywords": kw or stype, "city": city, "citylimit": "true"},
        })

    # ================================================================
    # 第 1.5 层: 坐标增强
    # ================================================================

    def _enrich_pois_with_coords(self, raw: Any) -> dict:
        """对 POI 列表中的每个结果并发调 maps_geo，注入经纬度"""
        data = self._extract_json(raw)
        if not data:
            return raw

        pois = data.get("pois", []) if isinstance(data, dict) else []
        if not pois:
            return data

        def geo_poi(poi):
            addr = poi.get("address", "") or poi.get("name", "")
            try:
                r = self._mcp.run({
                    "action": "call_tool", "tool_name": "maps_geo",
                    "arguments": {"address": addr},
                })
                m = re.search(r'"location"\s*:\s*"([\d.]+),([\d.]+)"', str(r))
                if m:
                    poi["_lng"] = float(m.group(1))
                    poi["_lat"] = float(m.group(2))
            except Exception:
                pass
            return poi

        futures = [self._executor.submit(geo_poi, p) for p in pois[:10]]
        for f in as_completed(futures):
            f.result()

        return data

    # ================================================================
    # 第 2 层: 格式化
    # ================================================================

    def _format(self, raw: Any, stype: str) -> str:
        data = self._extract_json(raw)
        if data is None:
            return str(raw)
        if stype == "weather":
            return self._format_weather(data)
        return self._format_poi(data, stype)

    def _format_weather(self, data: dict) -> str:
        lines = ["【天气信息】"]
        forecasts = data.get("forecasts", []) if isinstance(data, dict) else []
        if not forecasts and isinstance(data, list):
            forecasts = data
        for f in forecasts[:7]:
            if isinstance(f, dict):
                date = f.get("date", "未知")
                dw = f.get("dayweather", "?")
                nw = f.get("nightweather", "?")
                dt = f.get("daytemp", "?")
                nt = f.get("nighttemp", "?")
                w = f.get("daywind", "?")
                lines.append(f"- {date}: {dw}转{nw}, {dt}°C~{nt}°C, {w}风")
            else:
                lines.append(f"- {f}")
        return "\n".join(lines) if len(lines) > 1 else str(data)

    def _format_poi(self, data: dict, stype: str) -> str:
        label = "景点" if stype == "attraction" else ("酒店" if stype == "hotel" else "结果")
        lines = [f"【{label}搜索结果】"]
        pois = data.get("pois", []) if isinstance(data, dict) else []
        if not pois:
            return f"未找到{label}"

        for i, poi in enumerate(pois[:10], 1):
            parts = [f"{i}. {poi.get('name', '未知')}"]
            if poi.get("adname"):
                parts.append(f"[{poi['adname']}]")
            if poi.get("address"):
                parts.append(poi["address"])
            if poi.get("_lng") and poi.get("_lat"):
                parts.append(f"📍({poi['_lng']},{poi['_lat']})")
            elif poi.get("location"):
                parts.append(f"📍({poi['location']})")
            lines.append(" | ".join(parts))

        return "\n".join(lines)

    # ================================================================
    # 第 3 层: 校验
    # ================================================================

    def _validate(self, formatted: str, stype: str, city: str) -> str:
        lines = [l for l in formatted.split("\n") if l.strip() and not l.startswith("【")]
        if stype == "weather" and not lines:
            return f"【天气信息】\n- {city}: 天气数据暂不可用\n  建议：春秋季带外套，夏季注意防晒，冬季穿厚外套"
        if stype in ("attraction", "hotel", "around") and not lines:
            return f"【{stype}搜索结果】\n- {city}: 暂无数据，请到达后咨询当地旅游信息中心"
        return formatted

    # ================================================================
    # 工具方法
    # ================================================================

    def _extract_json(self, raw: Any) -> dict | None:
        if isinstance(raw, dict):
            return raw
        s = str(raw)
        try:
            return json.loads(s)
        except json.JSONDecodeError:
            m = re.match(r"工具\s+'[^']*'\s+执行结果:\s*\n", s)
            if m:
                try:
                    return json.loads(s[m.end():])
                except json.JSONDecodeError:
                    pass
        return None
