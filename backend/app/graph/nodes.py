"""LangGraph Node 函数 — 确定性检索节点 + 唯一 LLM planner 节点

2026-08 重构:
- attraction/hotel 从"LLM 转发伪 Agent"改为确定性检索（AmapToolWrapper.search_pois 直连）
- 坐标全程字段化（PoiCandidate），不再走 Markdown + 📍 正则
- 多偏好全量召回（并行）→ 稳定 ID 去重
- 远郊（>80km）标记 excursion 一日游，不再删除；酒店选址用市区质心
- retry_hotel 回环删除（离群不再触发酒店重搜），图只剩 planner 自回环
- 三餐由 _enrich_meals 用真实美食 POI 填充（每天第一个景点 500m 周边）
"""
import math
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from .state import TripPlannerState
from .context import event_sink_from_config
from ..agents.trip_planner_agent import get_planner
from ..tools.amap_wrapper import AmapToolWrapper
from ..services.amap_service import get_amap_mcp_tool


def _emit(config: dict | None, node: str, status: str, data: dict | None = None) -> None:
    sink = event_sink_from_config(config)
    if sink:
        sink.emit(node, status, data)


# ── 常量 ──
MAX_RETRY = 3                # Planner 自回环最大次数（硬伤重生成）
EXCURSION_KM = 80            # >80km → 远郊一日游标记（业务语义，非删除）
MAX_HOTEL_DIST_KM = 10       # 酒店到最远景点距离阈值（软伤）
BUDGET_OVER_PCT = 0.3        # 预算超用户偏好 30%（硬伤）


# ── 确定性检索单例 ──
_amap_wrapper: AmapToolWrapper | None = None


def _get_amap_wrapper() -> AmapToolWrapper:
    global _amap_wrapper
    if _amap_wrapper is None:
        _amap_wrapper = AmapToolWrapper()
    return _amap_wrapper


# ================================================================
# 工具函数
# ================================================================

def _city_center(city: str) -> tuple[str, str] | None:
    """maps_geo 本地调用获取城市中心坐标（不经过 LLM）。"""
    try:
        mcp = get_amap_mcp_tool()
        geo_result = mcp.run({
            "action": "call_tool", "tool_name": "maps_geo",
            "arguments": {"address": city},
        })
        m = re.search(r'"location"\s*:\s*"([\d.]+),([\d.]+)"', str(geo_result))
        if m:
            return m.group(1), m.group(2)
    except Exception:
        pass
    return None


def _haversine_km(lng1: float, lat1: float, lng2: float, lat2: float) -> float:
    """两点间 Haversine 直线距离 (km)"""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlng / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _format_candidates(cands: list, excursions: list | None = None) -> str:
    """结构化候选 → planner prompt 文本（本地生成，不经 LLM 转发）。"""
    exc_names = {e["name"] for e in (excursions or [])}
    lines = ["【景点搜索结果】"]
    for i, c in enumerate(cands, 1):
        parts = [f"{i}. {c.name}"]
        if c.name in exc_names:
            parts.append("【远郊】")
        if c.district:
            parts.append(f"[{c.district}]")
        if c.address:
            parts.append(c.address)
        parts.append(f"({c.lng},{c.lat})")
        if c.category:
            parts.append(c.category)
        if c.price is not None:
            parts.append(f"参考价¥{c.price:.0f}")
        lines.append(" | ".join(parts))
    if not cands:
        lines.append("无")
    return "\n".join(lines)


def _format_hotels(cands: list) -> str:
    """酒店候选 → planner prompt 文本。"""
    lines = ["【酒店搜索结果】"]
    for i, c in enumerate(cands, 1):
        parts = [f"{i}. {c.name}"]
        if c.hotel_type:
            parts.append(c.hotel_type)
        if c.rating:
            parts.append(f"评分{c.rating}")
        if c.price_range:
            parts.append(c.price_range)
        if c.address:
            parts.append(c.address)
        parts.append(f"({c.lng},{c.lat})")
        lines.append(" | ".join(parts))
    if not cands:
        lines.append("无")
    return "\n".join(lines)


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

        # ── 多偏好全量召回：每个偏好一个周边搜索，并行执行 ──
        keywords = [p.strip() for p in prefs if p.strip()] or ["景点"]
        center_str = f"{center[0]},{center[1]}" if center else ""
        merged: list = []
        with ThreadPoolExecutor(max_workers=min(len(keywords), 5)) as pool:
            futures = {}
            for kw in keywords:
                if center_str:
                    fut = pool.submit(wrapper.search_pois, city, "around", kw, center_str, "20000")
                else:
                    fut = pool.submit(wrapper.search_pois, city, "attraction", kw)
                futures[fut] = kw
            for fut in as_completed(futures):
                try:
                    merged.extend(fut.result())
                except Exception as e:
                    print(f"⚠️ [景点搜索] 偏好「{futures[fut]}」失败: {e}")

        # ── 稳定 ID 去重融合 ──
        seen: dict[str, Any] = {}
        for p in merged:
            seen.setdefault(p.id, p)
        candidates = list(seen.values())
        candidates.sort(key=lambda c: c.name)
        if not candidates:
            raise RuntimeError("未检索到任何景点")

        # ── 质心 + 市区质心 + 远郊标记（本地计算，不交 LLM）──
        # 远郊判定基准：城市中心（业务语义"距市中心 >80km"）；拿不到则用候选质心
        coords = [{"name": c.name, "lng": c.lng, "lat": c.lat} for c in candidates]
        n = len(coords)
        clng = sum(c["lng"] for c in coords) / n
        clat = sum(c["lat"] for c in coords) / n
        base_lng, base_lat = clng, clat
        if center:
            try:
                base_lng, base_lat = float(center[0]), float(center[1])
            except (ValueError, TypeError):
                pass

        urban, excursions = [], []
        for c in coords:
            d = _haversine_km(base_lng, base_lat, c["lng"], c["lat"])
            if d > EXCURSION_KM:
                excursions.append({"name": c["name"], "dist_km": round(d, 1)})
            else:
                urban.append(c)

        urban_center = {}
        if urban:
            urban_center = {
                "urban_lng": round(sum(c["lng"] for c in urban) / len(urban), 6),
                "urban_lat": round(sum(c["lat"] for c in urban) / len(urban), 6),
            }

        text = _format_candidates(candidates, excursions)
        _emit(config, "attraction", "done", {"status": "success", "count": len(candidates)})
        return {
            "attraction_data": text,
            "attraction_candidates": [c.model_dump() for c in candidates],
            "attraction_status": "success",
            "center_lng": round(clng, 6), "center_lat": round(clat, 6),
            "attraction_coords": coords,
            "excursion_pois": excursions,
            **urban_center,
        }
    except Exception as e:
        _emit(config, "attraction", "done", {"status": "failed"})
        return {"attraction_data": "", "attraction_candidates": [],
                "attraction_status": "failed",
                "error_log": [f"景点搜索失败: {str(e)}"]}


# ================================================================
# Node 2: 酒店检索（确定性，市区质心周边）
# ================================================================

def hotel_node(state: TripPlannerState, config: dict | None = None) -> dict:
    _emit(config, "hotel", "start")
    city = state["city"]
    try:
        wrapper = _get_amap_wrapper()
        ulng, ulat = state.get("urban_lng"), state.get("urban_lat")
        if ulng and ulat:
            print(f"🏨 [酒店搜索] 市区质心 ({ulng},{ulat}) 周边 5km")
            cands = wrapper.search_pois(city, "around", "酒店", f"{ulng},{ulat}", "5000")
        else:
            print(f"🏨 [酒店搜索] 无市区质心，退化为全城搜索")
            cands = wrapper.search_pois(city, "hotel", "酒店")
        text = _format_hotels(cands)
        _emit(config, "hotel", "done", {"status": "success", "count": len(cands)})
        return {"hotel_data": text,
                "hotel_candidates": [c.model_dump() for c in cands],
                "hotel_status": "success"}
    except Exception as e:
        _emit(config, "hotel", "done", {"status": "failed"})
        return {"hotel_data": "", "hotel_candidates": [],
                "hotel_status": "failed",
                "error_log": [f"酒店搜索失败: {str(e)}"]}


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
    """本地校验：硬伤（重试）/ 软伤（警告）→ 路由决策。

    2026-08 重构: 离群检测已移至 attraction_node（excursion 标记），
    此处不再删除景点、不再触发 retry_hotel 回环。
    """
    retry_count = state.get("planner_retry_count", 0)
    profile = state.get("user_profile", {})
    error_log: list[str] = []
    hard_errors: list[str] = []

    # ── 1a. 硬伤检测 ──
    plan_days = plan.get("days", [])
    if not plan_days:
        hard_errors.append("plan 缺少 .days 字段")

    for d in plan_days:
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
            max_d = 0
            for a in d.get("attractions", []):
                aloc = a.get("location", {})
                alng = aloc.get("longitude") or aloc.get("lng")
                alat = aloc.get("latitude") or aloc.get("lat")
                if alng is not None and alat is not None:
                    dist = _haversine_km(hlng, hlat, alng, alat)
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
# 坐标溯源
# ================================================================

def _ground_truth_coordinates(plan: dict, state: TripPlannerState) -> None:
    """用结构化候选的真实坐标覆盖 LLM 输出的坐标（防幻觉）。

    LLM 可能在 JSON 里写出偏差/错误坐标（实测出现过 1300km 级误差），
    而候选坐标来自高德检索。按名称匹配后覆盖 location 字段。
    """
    attrs_by_name = {c["name"]: c for c in state.get("attraction_candidates", [])}
    hotels_by_name = {c["name"]: c for c in state.get("hotel_candidates", [])}
    for d in plan.get("days", []):
        for a in d.get("attractions", []):
            cand = attrs_by_name.get(a.get("name", ""))
            if cand:
                a["location"] = {"longitude": cand["lng"], "latitude": cand["lat"]}
        hotel = d.get("hotel", {})
        cand = hotels_by_name.get(hotel.get("name", ""))
        if cand:
            hotel["location"] = {"longitude": cand["lng"], "latitude": cand["lat"]}


# ================================================================
# 三餐真实数据落地
# ================================================================

def _enrich_meals(plan: dict, city: str) -> None:
    """用真实美食 POI 填充每天三餐（每天第一个景点 500m 周边）。

    替换 LLM 编造餐厅；失败静默降级（meals 保持原样，不阻塞计划）。
    """
    try:
        wrapper = _get_amap_wrapper()
    except Exception:
        return
    for d in plan.get("days", []):
        attrs = d.get("attractions", [])
        if not attrs:
            continue
        a = attrs[0]
        loc = a.get("location", {})
        lng = loc.get("longitude") or loc.get("lng")
        lat = loc.get("latitude") or loc.get("lat")
        if not lng or not lat:
            continue
        try:
            foods = wrapper.search_pois(city, "food", "", f"{lng},{lat}", "", max_results=3)
        except Exception:
            continue
        if not foods:
            continue
        meal_types = ["breakfast", "lunch", "dinner"]
        meals = []
        for i, f in enumerate(foods[:3]):
            meals.append({
                "type": meal_types[i],
                "name": f.name,
                "description": f"{f.district} {f.category}".strip() or f.address,
                "estimated_cost": int(f.price or 0),
                "source": f.source,
                "location": {"longitude": f.lng, "latitude": f.lat},
            })
        if meals:
            d["meals"] = meals
            print(f"🍽️ [三餐] {d.get('date', '?')}: 已用真实美食 POI 填充 {len(meals)} 餐")


# ================================================================
# Node 4: Planner（唯一 LLM 调用）
# ================================================================

def _build_profile_constraints(profile: dict) -> str:
    """根据用户画像生成约束指令注入 LLM prompt"""
    constraints = []
    # 注意: profile 可能含值为 None 的键（记忆 JSON 宽松），一律 or 兜底
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


def planner_node(state: TripPlannerState, config: dict | None = None) -> dict:
    _emit(config, "planner", "start")
    city = state["city"]
    origin = state.get("origin", "")
    date_list = state.get("date_list", [])
    prefs = state.get("preferences", [])
    profile = state.get("user_profile", {})
    retry_count = state.get("planner_retry_count", 0)

    warnings = []
    for n, k in [("景点", "attraction"), ("天气", "weather"), ("酒店", "hotel")]:
        if state.get(f"{k}_status") == "failed":
            warnings.append(f"⚠️ {n}数据不可用，已使用降级方案")

    profile_description = ""
    if profile:
        parts = []
        for k, label in [("accommodation", "酒店档次"), ("budget_tier", "预算偏好"),
                          ("pace", "旅行节奏")]:
            if profile.get(k): parts.append(f"- {label}: {profile[k]}")
        for k, label in [("diet", "饮食"), ("transport", "交通"), ("interests", "兴趣")]:
            if profile.get(k): parts.append(f"- {label}: {', '.join(profile[k])}")
        if parts: profile_description = "**用户画像:**\n" + "\n".join(parts)

    profile_constraints = _build_profile_constraints(profile)

    dates_str = ", ".join(date_list) if date_list else "请自行推断"
    date_req = f"每天日期必须按顺序使用: {dates_str}" if date_list else ""

    dist = state.get("intercity_distance_km", 0)
    ic_text = ""
    if dist > 0:
        ic_text = (f"\n**城际交通:** {state.get('transport_mode', '高铁')} · "
                   f"{dist}km · 约{state.get('intercity_duration_h', 0)}h · "
                   f"¥{state.get('intercity_cost', 0)}\n")

    retry_hint = ""
    if retry_count > 0:
        retry_hint = (f"\n⚠️ 第{retry_count}次重试——上次生成的计划有硬伤，"
                      f"请务必修正以下问题并严格遵守约束！\n")

    # ── 远郊一日游提示（业务语义：不删除，安排单独一天）──
    excursion_hint = ""
    excursions = state.get("excursion_pois", [])
    if excursions:
        names = "、".join(e["name"] for e in excursions)
        excursion_hint = (
            f"\n**远郊一日游:** 以下景点距市中心超过 80km，"
            f"请安排为单独一日游（早出晚归，当天只去该方向景点）: {names}\n")

    query = f"""请根据以下信息生成{state['days']}天旅行计划:

{ic_text}
出发地: {origin if origin else '未指定'}
目的地: {city}
日期: {date_req}
天数: {state['days']}天
每日可安排时间: {state.get("day_start_hour", 9)}:00-{state.get("day_end_hour", 20)}:00
总预算硬约束: ¥{state.get("budget_total")}（未提供则不限制）

景点信息:
{state.get('attraction_data', '无')}

天气信息:
{state.get('weather_data', '无')}

酒店信息:
{state.get('hotel_data', '无')}

用户偏好: {', '.join(prefs) if prefs else '无'}
{profile_description}
{profile_constraints}{excursion_hint}{retry_hint}
{('【注意】' + '; '.join(warnings) if warnings else '')}
"""
    try:
        planner = get_planner()
        result = planner._run_agent_with_retry(planner.planner_agent, query)
        plan = planner._parse_plan(result)
        _ground_truth_coordinates(plan, state)
        _enrich_meals(plan, city)
        validation = _validate_and_refine(state, plan)
    except Exception as exc:
        _emit(config, "planner", "done", {"status": "failed"})
        return {
            "final_plan": {
                "city": city, "start_date": state.get("start_date", ""),
                "days": [], "budget": {}, "overall_suggestions": "规划服务暂时不可用",
                "status": "fallback",
            },
            "planner_route": "done",
            "error_log": [f"行程规划失败: {exc}"],
        }

    _emit(config, "planner", "done")
    return {"final_plan": plan, **validation}
