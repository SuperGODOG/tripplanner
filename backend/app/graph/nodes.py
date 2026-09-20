"""LangGraph Node 函数 — 确定性检索节点 + v3 分日并发（Send API）架构 Facade

重构说明:
- 剥离高德地图检索、Minimax 酒店选址与三餐富化至独立工具集 app.tools.search_tools
- 接入确定性规划工具集 app.tools.planning_tools（K-Means 聚类、路径求解与指纹缓存）
- 保持所有节点与模块级函数签名完全不变，兼容现有 60+ 单元测试与 Monkeypatch 注入
"""
from __future__ import annotations

import re
from typing import Any
from langgraph.types import Send

from .state import TripPlannerState
from .context import event_sink_from_config
from ..agents.trip_planner_agent import get_planner
from ..tools.amap_wrapper import AmapToolWrapper
from ..services.amap_service import geo_cached
from ..services.clustering import LEISURE, EXCURSION
from ..services.route_solver import format_plan
from ..tools.planning_tools import cluster_pois_tool, solve_day_route_tool
from ..tools.search_tools import (
    haversine_km,
    format_attractions_prompt_text,
    format_hotels_prompt_text,
    search_attractions_tool,
    categorize_excursions,
    select_hotel_minimax,
    search_hotel_minimax_tool,
    enrich_meals_tool,
)


def _emit(config: dict | None, node: str, status: str, data: dict | None = None) -> None:
    sink = event_sink_from_config(config)
    if sink:
        sink.emit(node, status, data)


# ── 常量 ──
MAX_RETRY = 3                # Planner 自回环最大次数（硬伤重生成）
EXCURSION_KM = 80            # >80km → 远郊一日游标记（业务语义，非删除）
MAX_HOTEL_DIST_KM = 10       # 酒店到最远景点距离阈值（软伤）
BUDGET_OVER_PCT = 0.3        # 预算超用户偏好 30%（硬伤）


# ── 确定性检索单例（保留供测试 monkeypatch 依赖）──
_amap_wrapper: AmapToolWrapper | None = None


def _get_amap_wrapper() -> AmapToolWrapper:
    global _amap_wrapper
    if _amap_wrapper is None:
        _amap_wrapper = AmapToolWrapper()
    return _amap_wrapper


# ================================================================
# 工具函数（保持模块级暴露以兼容现有单元测试 monkeypatch）
# ================================================================

def _city_center(city: str) -> tuple[str, str] | None:
    """maps_geo 本地调用获取城市中心坐标（不经过 LLM）。

    经 geo_cached 缓存加速。保持函数名以供测试 monkeypatch 依赖。
    """
    coord = geo_cached(city)
    if coord:
        return str(coord[0]), str(coord[1])
    return None


def _haversine_km(lng1: float, lat1: float, lng2: float, lat2: float) -> float:
    """两点间 Haversine 直线距离 (km)"""
    return haversine_km(lng1, lat1, lng2, lat2)


def _format_candidates(cands: list, excursions: list | None = None) -> str:
    """结构化候选 → planner prompt 文本"""
    return format_attractions_prompt_text(cands, excursions)


def _format_hotels(cands: list) -> str:
    """酒店候选 → planner prompt 文本"""
    return format_hotels_prompt_text(cands)


# ================================================================
# Node 1: 景点检索（确定性，多偏好并行召回）
# ================================================================

def attraction_node(state: TripPlannerState, config: dict | None = None) -> dict:
    _emit(config, "attraction", "start")
    city = state["city"]
    prefs = state.get("preferences", []) or []
    try:
        wrapper = _get_amap_wrapper()
        center = _city_center(city)

        candidates = search_attractions_tool(
            city=city,
            preferences=prefs,
            user_id=state.get("user_id", ""),
            amap_wrapper=wrapper,
            city_center=center,
        )

        coords, excursions, urban_cands = categorize_excursions(
            candidates,
            center=center,
            excursion_km=EXCURSION_KM,
        )

        text = _format_candidates(candidates, excursions)

        # 聚类分天（K-Means，互斥分配——数据层保证每天景点不重复）
        day_clusters = cluster_pois_tool(
            pois=[c.model_dump() if hasattr(c, "model_dump") else c for c in urban_cands],
            days=state["days"],
            excursions=excursions,
        )

        _emit(config, "attraction", "done", {"status": "success", "count": len(candidates)})
        return {
            "attraction_data": text,
            "attraction_candidates": [c.model_dump() if hasattr(c, "model_dump") else c for c in candidates],
            "attraction_status": "success",
            "attraction_coords": coords,
            "excursion_pois": excursions,
            "day_clusters": day_clusters,
        }
    except Exception as e:
        _emit(config, "attraction", "done", {"status": "failed"})
        return {
            "attraction_data": "",
            "attraction_candidates": [],
            "attraction_status": "failed",
            "error_log": [f"景点搜索失败: {str(e)}"],
        }


# ================================================================
# Node 2: 酒店检索 + 目标函数选址（确定性，城市中心周边）
# ================================================================

def _hotel_urban_pois(state: TripPlannerState) -> list[dict]:
    """打分用的市区景点集合（远郊/自由日排除）。

    优先取聚类 normal 簇的 POI；聚类缺失时退化全量候选。
    """
    pois = []
    for c in state.get("day_clusters", []):
        if c.get("kind") == "normal":
            pois.extend(c.get("pois", []))
    if not pois:
        pois = [{"lng": p.get("lng"), "lat": p.get("lat")}
                for p in state.get("attraction_coords", [])]
    return [p for p in pois if p.get("lng") and p.get("lat")]


def _select_hotel(cands: list, state: TripPlannerState) -> dict:
    """本地目标函数选址（minimax 最远景点最小化）。保持函数名以供测试直接调用。"""
    if not cands:
        return {}
    pois = _hotel_urban_pois(state)
    profile = state.get("user_profile", {})
    acc = profile.get("accommodation") or ""
    return select_hotel_minimax(cands, pois, acc)


def hotel_node(state: TripPlannerState, config: dict | None = None) -> dict:
    _emit(config, "hotel", "start")
    city = state["city"]
    try:
        wrapper = _get_amap_wrapper()
        center = _city_center(city)
        pois = _hotel_urban_pois(state)
        profile = state.get("user_profile", {})
        acc = profile.get("accommodation") or ""

        res = search_hotel_minimax_tool(
            city=city,
            attraction_coords=pois,
            accommodation_pref=acc,
            amap_wrapper=wrapper,
            city_center=center,
        )
        if res.get("hotel_status") == "failed":
            raise RuntimeError(res.get("error_log", ["未知错误"])[0])

        _emit(config, "hotel", "done", {"status": "success", "count": len(res.get("hotel_candidates", []))})
        return {
            "hotel_data": res.get("hotel_data", ""),
            "hotel_candidates": res.get("hotel_candidates", []),
            "hotel_status": "success",
            "hotel_selected": res.get("hotel_selected", {}),
        }
    except Exception as e:
        _emit(config, "hotel", "done", {"status": "failed"})
        return {
            "hotel_data": "",
            "hotel_candidates": [],
            "hotel_status": "failed",
            "error_log": [f"酒店搜索失败: {str(e)}"],
        }


# ================================================================
# Node 3: 记忆读取（租户隔离，纯本地）
# ================================================================

def memory_node(state: TripPlannerState, config: dict | None = None) -> dict:
    _emit(config, "memory", "start")
    from ..memory.repository import get_memory_repository
    try:
        _, profile = get_memory_repository().get_profile(state["user_id"])
        _emit(config, "memory", "done")
        return {"user_profile": profile}
    except Exception as e:
        _emit(config, "memory", "done", {"status": "failed"})
        return {"error_log": [f"记忆加载失败: {str(e)}"]}


# ================================================================
# 校验与回环
# ================================================================

def _validate_and_refine(state: TripPlannerState, plan: dict) -> dict:
    """本地校验：硬伤（重试）/ 软伤（警告）→ 路由决策。"""
    retry_count = state.get("planner_retry_count", 0)
    profile = state.get("user_profile", {})
    error_log: list[str] = []
    hard_errors: list[str] = []

    # ── 1a. 硬伤检测 ──
    plan_days = plan.get("days", [])
    if not plan_days:
        hard_errors.append("plan 缺少 .days 字段")

    for d in plan_days:
        if d.get("kind") in (LEISURE, EXCURSION):
            continue
        attrs = d.get("attractions", [])
        if len(attrs) < 2:
            hard_errors.append(f"{d.get('date', '?')}: 景点数 {len(attrs)} < 2")

    required = ["city", "start_date", "days", "budget", "overall_suggestions"]
    for f in required:
        if f not in plan:
            hard_errors.append(f"缺少必填字段: {f}")

    budget = plan.get("budget", {})
    total = budget.get("total", 0) if isinstance(budget, dict) else 0
    requested_budget = state.get("budget_total")
    if requested_budget is not None and total > requested_budget:
        hard_errors.append(f"预算 {total} 元 超出请求总预算 {requested_budget} 元")
    if profile.get("budget_range"):
        try:
            pref_hi = int(profile["budget_range"].split("-")[1].replace("元", ""))
            if total > pref_hi * (1 + BUDGET_OVER_PCT):
                hard_errors.append(
                    f"预算 {total} 元 超出用户偏好 {pref_hi} 元 超过 30%")
        except (ValueError, IndexError):
            pass

    # ── 1b. 软伤检测 ──
    warnings: list[str] = []

    for d in plan_days:
        hotel = d.get("hotel", {})
        hloc = hotel.get("location", {})
        hlng = hloc.get("longitude") or hloc.get("lng")
        hlat = hloc.get("latitude") or hloc.get("lat")
        if hlng is not None and hlat is not None:
            max_d = 0.0
            for a in d.get("attractions", []):
                aloc = a.get("location", {})
                alng = aloc.get("longitude") or aloc.get("lng")
                alat = aloc.get("latitude") or aloc.get("lat")
                if alng is not None and alat is not None:
                    dist = haversine_km(float(hlng), float(hlat), float(alng), float(alat))
                    if dist > max_d:
                        max_d = dist
            if max_d > MAX_HOTEL_DIST_KM:
                warnings.append(
                    f"{d.get('date', '?')}: 酒店到最远景点 {max_d:.1f}km > {MAX_HOTEL_DIST_KM}km")

    weather_info = plan.get("weather_info", [])
    outdoor_cats = ["自然", "公园", "爬山", "户外", "登山", "徒步", "海滩", "动物园"]
    for d in plan_days:
        date = d.get("date", "")
        wi = next((w for w in weather_info if w.get("date") == date), None)
        day_weather = (wi.get("day_weather", "") if wi else "")
        if any(kw in day_weather for kw in ["暴雨", "大雨", "暴雪", "台风"]):
            outdoor_attrs = [
                a.get("name") for a in d.get("attractions", [])
                if any(kw in (a.get("category", "") + (a.get("name", ""))) for kw in outdoor_cats)
            ]
            if outdoor_attrs:
                warnings.append(
                    f"{date}: {day_weather}天安排了户外景点: {', '.join(outdoor_attrs)}")

    # ── 路由决策 ──
    if hard_errors and retry_count < MAX_RETRY:
        error_log.append(f"硬伤 #{retry_count + 1}: {'; '.join(hard_errors)}")
        return {
            "error_log": error_log,
            "planner_route": "retry_planner",
            "planner_retry_count": retry_count + 1,
            "planner_last_error": "",
        }

    exhausted = hard_errors and retry_count >= MAX_RETRY
    if exhausted:
        error_log.append(f"硬伤（重试{MAX_RETRY}次仍失败）: {'; '.join(hard_errors)}")

    result: dict = {
        "planner_route": "done",
        "planner_retry_count": retry_count,
    }
    if warnings:
        result["error_log"] = [f"软伤: {'; '.join(warnings)}"]
    if error_log:
        if "error_log" in result:
            result["error_log"] = error_log + result["error_log"]
        else:
            result["error_log"] = error_log
    return result


# ================================================================
# 三餐真实数据落地
# ================================================================

def _enrich_meals(plan: dict, city: str) -> None:
    """用真实美食 POI 填充每天三餐（保留函数签名供测试直接调用）"""
    try:
        wrapper = _get_amap_wrapper()
    except Exception:
        wrapper = None
    enrich_meals_tool(plan.get("days", []), city, amap_wrapper=wrapper)


# ================================================================
# Node 4: Planner（唯一 LLM 调用）
# ================================================================

def _build_profile_constraints(profile: dict) -> str:
    """根据用户画像生成约束指令注入 LLM prompt"""
    constraints = []
    budget_tier = profile.get("budget_tier") or ""
    if budget_tier == "穷游":
        constraints.append("- 优先免费景点，预算 < 500 元/天")
    diet = profile.get("diet") or []
    if any("不吃辣" in d for d in diet):
        constraints.append("- 避免川菜、湘菜等辣味菜系")
    accommodation = profile.get("accommodation") or ""
    if "经济型" in accommodation:
        constraints.append("- 推荐经济型酒店，控制住宿预算")
    pace = profile.get("pace") or ""
    if pace == "紧凑高效":
        constraints.append("- 每天至少 3 个景点，行程紧凑")
    if constraints:
        return "\n**画像约束指令（必须遵守）:**\n" + "\n".join(constraints) + "\n"
    return ""


# ================================================================
# v3: 分日并发（Send API 动态 fan-out）
# ================================================================

def _fan_out(state: TripPlannerState) -> list[Send]:
    """conditional path: 按聚类结果动态分发 N 个 day_node（Send API，原生并行）。"""
    clusters = state.get("day_clusters", [])
    dates = state.get("date_list", [])
    sends = []
    for c in clusters:
        i = c["day_index"]
        sends.append(Send("day_node", {
            "day_index": i,
            "day_kind": c.get("kind", "normal"),
            "day_pois": c.get("pois", []),
            "day_date": dates[i] if i < len(dates) else "",
            "city": state.get("city", ""),
            "origin": state.get("origin", ""),
            "transport_mode": state.get("transport_mode", "高铁"),
            "preferences": state.get("preferences", []),
            "user_profile": state.get("user_profile", {}),
            "day_start_hour": state.get("day_start_hour", 9),
            "day_end_hour": state.get("day_end_hour", 20),
            "budget_total": state.get("budget_total"),
            "weather_data": state.get("weather_data", ""),
            "hotel_candidates": state.get("hotel_candidates", []),
            "hotel_selected": state.get("hotel_selected", {}),
            "intercity_distance_km": state.get("intercity_distance_km", 0),
            "intercity_duration_h": state.get("intercity_duration_h", 0),
            "intercity_cost": state.get("intercity_cost", 0),
            "distance_category": state.get("distance_category", ""),
            "planner_last_error": state.get("planner_last_error", ""),
        }))
    return sends


def _format_day_prompt(idx: int, date: str, kind: str, attractions: list,
                       state: TripPlannerState,
                       guide_lines: list[str] | None = None) -> str:
    """单天文案 prompt（LLM 只写文案，不决策选点/顺序/时间）。"""
    city = state.get("city", "")
    prefs = state.get("preferences", [])
    profile = state.get("user_profile", {})
    lines = [
        f"你是行程规划专家。请为第{idx + 1}天（{date}）的行程撰写当天文案。",
        f"目的地: {city}",
        f"每天可安排时间: {state.get('day_start_hour', 9)}:00-{state.get('day_end_hour', 20)}:00",
    ]
    if state.get("budget_total"):
        lines.append(f"总预算硬约束: ¥{state.get('budget_total')}")
    if kind == EXCURSION:
        lines.append("⚠️ 今天是远郊一日游：景点距市中心超过 80km，早出晚归，当天只去该方向。")
    if kind == LEISURE:
        lines.append("今天是自由活动日，无固定景点安排。")

    if attractions:
        lines.append("景点顺序（已按路径优化排序，含到达/离开时间）：")
        for i, a in enumerate(attractions, 1):
            t = f"{a.get('arrive_time', '')}-{a.get('depart_time', '')}" if a.get("arrive_time") else ""
            price = a.get("ticket_price")
            lines.append(f"  {i}. {a['name']} {t} 门票{price if price is not None else '未知'}元 "
                         f"{a.get('category', '')}")

    lines.append(f"用户偏好: {', '.join(prefs) if prefs else '无'}")
    if profile:
        parts = []
        for k, label in [("accommodation", "酒店档次"), ("budget_tier", "预算偏好"),
                          ("pace", "旅行节奏")]:
            if profile.get(k):
                parts.append(f"- {label}: {profile[k]}")
        for k, label in [("diet", "饮食"), ("transport", "交通"), ("interests", "兴趣")]:
            if profile.get(k):
                parts.append(f"- {label}: {', '.join(profile[k])}")
        if parts:
            lines.append("**用户画像:**\n" + "\n".join(parts))
    constraints = _build_profile_constraints(profile)
    if constraints:
        lines.append(constraints.strip())

    if guide_lines:
        lines.append("**参考攻略片段（来自攻略知识库，请在文案中自然引用其中的具体玩法/避坑细节）:**")
        lines.extend(guide_lines[:4])

    lines.append(
        '请只输出 JSON 对象: {"description": "第N天行程概述(80字内)", '
        '"transportation": "市内交通建议(50字内)", '
        '"accommodation": "住宿说明(30字内)", '
        '"overall_tips": "当天贴心建议(50字内)"}'
    )
    return "\n".join(lines)


def day_node(state: TripPlannerState, config: dict | None = None) -> dict:
    """单日计划节点（Send 并行实例，每天一次 LLM 文案调用）。"""
    idx = state.get("day_index", 0)
    kind = state.get("day_kind", "normal")
    pois = state.get("day_pois", [])
    date = state.get("day_date", "")

    day: dict = {
        "date": date, "day_index": idx, "kind": kind,
        "description": "", "transportation": "", "accommodation": "",
        "hotel": {}, "attractions": [], "meals": [], "overall_tips": "",
        "guide_references": [],
    }

    if kind == LEISURE:
        day["description"] = f"第{idx + 1}天自由活动，可逛街购物、品尝当地美食、休整充电。"
        day["transportation"] = "市内交通建议：优先地铁/公交。"
        day["overall_tips"] = "注意防晒补水，预留机动时间。"
        _emit(config, "planner", "done", {"day_index": idx, "status": "leisure"})
        return {"plan_days": [day]}

    _emit(config, "planner", "start", {"day_index": idx, "kind": kind})

    # 本地路径求解（确定性，受指纹缓存加速）
    hotel = state.get("hotel_selected") or {}
    route_res = solve_day_route_tool(
        pois=pois,
        start_hour=state.get("day_start_hour", 9),
        close_hour=state.get("day_end_hour", 20),
        start_hotel=hotel if hotel.get("lng") and hotel.get("lat") else None,
        day_index=idx,
    )
    window_ok = route_res.diagnostics is None
    if route_res.route:
        if isinstance(route_res.route[0], dict) and "poi" in route_res.route[0]:
            attractions = format_plan(route_res.route)
        else:
            attractions = route_res.route
    else:
        # 时间窗超限降级：全量点按聚类顺序（无时间标注）
        window_ok = False
        plan = [{"poi": p, "arrive_min": 0, "depart_min": 0, "travel_min_from_prev": 0} for p in pois]
        attractions = format_plan(plan)

    # 攻略知识库检索（轻量 RAG，BM25）
    guide_refs: list[dict] = []
    guide_lines: list[str] = []
    try:
        from ..services.guide_rag import get_guide_rag
        rag = get_guide_rag()
        city = state.get("city", "")
        for a in attractions[:3]:
            for hit in rag.retrieve(a["name"], city=city or None, top_k=1):
                guide_refs.append({"attraction": a["name"], "guide": hit["guide"],
                                   "city": hit["city"], "tag": hit["tag"]})
                guide_lines.append(f"  · {hit['guide']}（{hit['tag']}）: {hit['text']}")
    except Exception:
        pass
    day["guide_references"] = guide_refs

    # LLM 文案（失败本地兜底，不阻断）
    text = _format_day_prompt(idx, date, kind, attractions, state, guide_lines)
    try:
        planner = get_planner()
        result = planner._run_agent_with_retry(
            planner.day_agent, text,
            response_format={"type": "json_object"},
        )
        meta = planner._parse_plan(result)
        day["description"] = str(meta.get("description", ""))
        day["transportation"] = str(meta.get("transportation", ""))
        day["accommodation"] = str(meta.get("accommodation", ""))
        day["overall_tips"] = str(meta.get("overall_tips", ""))
        status = "success"
    except Exception:
        day["description"] = f"第{idx + 1}天：游览{'、'.join(a['name'] for a in attractions)}。"
        day["transportation"] = "市内交通建议：优先地铁/公交。"
        day["overall_tips"] = "注意防晒补水，预留机动时间。"
        status = "llm_fallback"

    day["attractions"] = attractions
    if not window_ok:
        status = "window_fallback"
    _emit(config, "planner", "done", {"day_index": idx, "status": status})
    result_dict: dict = {"plan_days": [day]}
    if status == "llm_fallback":
        result_dict["error_log"] = [f"第{idx + 1}天文案生成失败（已用本地模板）"]
    if not window_ok:
        result_dict["error_log"] = result_dict.get("error_log", []) + [f"第{idx + 1}天景点总时长超日窗口，已降级为无时间标注顺序"]
    return result_dict


# ================================================================
# v3: 聚合节点（Send 汇聚只触发 1 次）
# ================================================================

def _parse_weather_data(text: str) -> list[dict]:
    """本地解析天气文本"""
    out = []
    for line in (text or "").splitlines():
        m = re.match(r"-\s*([\d-]+):\s*(.+)$", line.strip())
        if not m:
            continue
        date, rest = m.group(1), m.group(2)
        parts = [p.strip() for p in rest.split(",")]
        weather = parts[0] if parts else ""
        if "转" in weather:
            day_w, night_w = weather.split("转", 1)
        else:
            day_w, night_w = weather, ""
        temp_m = re.match(r"(\d+)°C~(\d+)°C", parts[1]) if len(parts) > 1 else None
        wind = parts[2] if len(parts) > 2 else ""
        wind_m = re.match(r"(.+?)风", wind) if wind else None
        out.append({
            "date": date,
            "day_weather": day_w, "night_weather": night_w,
            "day_temp": int(temp_m.group(1)) if temp_m else None,
            "night_temp": int(temp_m.group(2)) if temp_m else None,
            "wind_direction": wind_m.group(1) if wind_m else "",
            "wind_power": wind,
        })
    return out


def _parse_price_range(price_range: str) -> int:
    """"300-500元" → 400（中值估算）；解析失败返回 0。"""
    m = re.search(r"(\d+)\s*-\s*(\d+)", price_range or "")
    if m:
        return (int(m.group(1)) + int(m.group(2))) // 2
    m = re.search(r"(\d+)", price_range or "")
    return int(m.group(1)) if m else 0


def _compute_budget(days: list[dict], state: TripPlannerState) -> dict:
    """本地预算计算（确定性）"""
    total_attractions = sum(a.get("ticket_price") or 0
                            for d in days for a in d.get("attractions", []))
    total_meals = sum(m.get("estimated_cost") or 0
                      for d in days for m in d.get("meals", []))
    hotel = state.get("hotel_selected") or {}
    hotel_price = _parse_price_range(str(hotel.get("price_range", "")))
    if not hotel_price and hotel.get("price"):
        hotel_price = int(hotel["price"])
    total_hotels = hotel_price * len(days)
    intercity = state.get("intercity_cost", 0) or 0
    total_transportation = intercity + 50 * len(days)
    total = total_attractions + total_hotels + total_meals + total_transportation
    return {
        "total_attractions": int(total_attractions),
        "total_hotels": int(total_hotels),
        "total_meals": int(total_meals),
        "total_transportation": int(total_transportation),
        "total": int(total),
    }


def merge_node(state: TripPlannerState, config: dict | None = None) -> dict:
    """聚合节点: 排序 → 填充 → 校验 → final_plan。"""
    city = state.get("city", "")
    days = sorted(state.get("plan_days", []), key=lambda d: d.get("day_index", 0))
    error_log: list[str] = []

    if not days:
        error_log.append("分日计划生成失败（无任何天产出）")
        return {
            "final_plan": {
                "city": city, "start_date": state.get("start_date", ""),
                "days": [], "budget": {}, "overall_suggestions": "规划服务暂时不可用",
                "status": "fallback",
            },
            "planner_route": "done",
            "error_log": error_log,
        }

    # 1. 天气结构化
    weather_info = _parse_weather_data(state.get("weather_data", ""))
    if not weather_info:
        error_log.append("天气数据解析失败，天气信息为空（降级）")

    # 2. 酒店填充（全程同一家）
    hotel = state.get("hotel_selected") or {}
    for d in days:
        if hotel:
            d["hotel"] = {
                "name": hotel.get("name", ""),
                "address": hotel.get("address", ""),
                "location": {"longitude": hotel.get("lng"), "latitude": hotel.get("lat")},
                "price_range": hotel.get("price_range", ""),
                "rating": hotel.get("rating", ""),
                "type": hotel.get("hotel_type", ""),
                "distance": "全程入住同一家酒店",
            }

    # 3. 本地预算
    budget = _compute_budget(days, state)

    # 4. 三餐真实 POI 填充
    plan = {"city": city,
            "start_date": state.get("start_date", ""),
            "days": days,
            "budget": budget,
            "overall_suggestions": ""}
    _enrich_meals(plan, city)

    # 5. 校验（软伤记录，硬伤降级交付）
    validation = _validate_and_refine(state, plan)
    error_log.extend(validation.get("error_log", []))
    if validation.get("planner_route") == "retry_planner":
        error_log.append("校验发现硬伤但本地链路无法重试，已按当前结果交付")

    # 6. 组装 final_plan
    tips = [d.get("overall_tips", "") for d in days if d.get("overall_tips")]
    overall = "；".join(tips)[:200] if tips else "祝旅途愉快！建议提前预约热门景点门票，预留机动时间。"
    final_plan = {
        "city": city,
        "start_date": state.get("start_date", ""),
        "end_date": days[-1].get("date", "") if days else "",
        "days": days,
        "weather_info": weather_info,
        "overall_suggestions": overall,
        "budget": budget,
        "status": "success" if not error_log else "degraded",
    }

    _emit(config, "planner", "merge_done", {"day_count": len(days)})
    result: dict = {"final_plan": final_plan, "planner_route": "done"}
    if error_log:
        result["error_log"] = error_log
    return result
