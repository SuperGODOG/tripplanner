"""LangGraph Node 函数 — 确定性检索节点 + v3 分日并发（Send API）

2026-08-21 v3 重构（多日并发拓扑）:
- attraction_node 检索后做 K-Means 聚簇分天（数据层互斥，LLM 不再全局去重）
- hotel_node 本地选定全程酒店（市区质心最近，确定性）
- _fan_out: Send API 按天动态分发 day_node（原生并行，汇聚只触发 1 次，实测）
- day_node: 本地路径求解（贪心+2-opt+时间窗）+ 单天文案 LLM（JSON mode）
- merge_node: 聚合 + 天气本地解析 + 三餐填充 + 本地预算 + 校验 → final_plan
- 全链路韧性: 单天文案 LLM 失败 → 本地模板兜底，不阻断整个计划

历史（2026-08 之前）: attraction/hotel 曾为 LLM 转发伪 Agent，v2 改为确定性检索，
单次 planner 生成全部天；v3 拆为分日并行。坐标溯源函数已删除——v3 景点坐标
全部本地组装（候选直出），LLM 不再输出坐标，幻觉源在结构上消除。
"""
import math
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from langgraph.types import Send

from .state import TripPlannerState
from .context import event_sink_from_config
from ..agents.trip_planner_agent import get_planner
from ..tools.amap_wrapper import AmapToolWrapper
from ..services.amap_service import geo_cached
from ..services.clustering import LEISURE, EXCURSION, cluster_pois_by_day
from ..services.route_solver import solve_daily_route, format_plan


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
    """maps_geo 本地调用获取城市中心坐标（不经过 LLM）。

    2026-08-21 优化: 经 geo_cached（内存 LRU + 全局 MCP 池限流），
    同城市反复请求直接命中缓存。签名保持不变（测试 monkeypatch 依赖）。
    """
    coord = geo_cached(city)
    if coord:
        return str(coord[0]), str(coord[1])
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

        # ── 远郊标记（本地计算，不交 LLM）──
        # 判定基准：城市中心（业务语义"距市中心 >80km"）；拿不到则用候选质心
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

        excursions = []
        for c in coords:
            d = _haversine_km(base_lng, base_lat, c["lng"], c["lat"])
            if d > EXCURSION_KM:
                excursions.append({"name": c["name"], "dist_km": round(d, 1),
                                   "lng": c["lng"], "lat": c["lat"]})

        text = _format_candidates(candidates, excursions)

        # ── v3: 聚类分天（K-Means，互斥分配——数据层保证每天景点不重复）──
        # 注意: 聚类只吃【市区】候选——远郊点已单独进 excursions（远郊日），
        # 全量传入会导致远郊点同时出现在市区簇和远郊日（重复入簇 bug，2026-08-21 修复）
        exc_names = {e["name"] for e in excursions}
        urban_cands = [c for c in candidates if c.name not in exc_names]
        day_clusters = cluster_pois_by_day(
            [c.model_dump() for c in urban_cands],
            state["days"],
            excursion_pois=excursions,
        )

        _emit(config, "attraction", "done", {"status": "success", "count": len(candidates)})
        return {
            "attraction_data": text,
            "attraction_candidates": [c.model_dump() for c in candidates],
            "attraction_status": "success",
            "attraction_coords": coords,
            "excursion_pois": excursions,
            "day_clusters": day_clusters,
        }
    except Exception as e:
        _emit(config, "attraction", "done", {"status": "failed"})
        return {"attraction_data": "", "attraction_candidates": [],
                "attraction_status": "failed",
                "error_log": [f"景点搜索失败: {str(e)}"]}


# ================================================================
# Node 2: 酒店检索 + 目标函数选址（确定性，城市中心周边）
# ================================================================

def _hotel_urban_pois(state: TripPlannerState) -> list[dict]:
    """打分用的市区景点集合（远郊/自由日排除）。

    优先取聚类 normal 簇的 POI（与分日链路一致）；聚类缺失时退化全量候选。
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
    """本地目标函数选址（v3，替代几何质心——质心离群敏感且无业务语义）。

    评分 = minimax（到所有市区景点的最大距离，Haversine）：保证"最远景点不远"，
    等价于优化每天从酒店出发的首站通勤（路径起点就是酒店）。
    远郊点不参与打分（excursion 日"早出晚归"默认长通勤，参与会惩罚所有酒店）。
    用户住宿偏好（经济型）作为候选池前置过滤，再在池内 minimax。
    """
    if not cands:
        return {}
    pois = _hotel_urban_pois(state)
    profile = state.get("user_profile", {})
    acc = profile.get("accommodation") or ""

    # 偏好过滤: 经济型用户 → 候选池收敛到经济型（若存在）
    if "经济型" in acc:
        econ = [h for h in cands if "经济" in (h.hotel_type or "")]
        if econ:
            cands = econ

    if not pois:
        return cands[0].model_dump()

    best = min(cands, key=lambda h: max(
        _haversine_km(h.lng, h.lat, p["lng"], p["lat"]) for p in pois))
    return best.model_dump()


def hotel_node(state: TripPlannerState, config: dict | None = None) -> dict:
    _emit(config, "hotel", "start")
    city = state["city"]
    try:
        wrapper = _get_amap_wrapper()
        # ── v3: 搜索中心 = 城市中心（高德 geocode，行政中心，稳定不随候选集漂移）
        # 替代几何质心——质心会被边缘/稀疏点拉偏，导致候选池本身有偏。
        # 半径放宽到 10km 弥补中心与酒店密集区之间的偏差。
        center = _city_center(city)
        if center:
            center_str = f"{center[0]},{center[1]}"
            print(f"🏨 [酒店搜索] 城市中心 ({center_str}) 周边 10km")
            cands = wrapper.search_pois(city, "around", "酒店", center_str, "10000")
        else:
            print(f"🏨 [酒店搜索] 无城市中心，退化为全城搜索")
            cands = wrapper.search_pois(city, "hotel", "酒店")
        text = _format_hotels(cands)

        # ── v3: 目标函数选址（minimax 通勤），本地确定性，不交 LLM ──
        hotel_selected = _select_hotel(cands, state)

        _emit(config, "hotel", "done", {"status": "success", "count": len(cands)})
        return {"hotel_data": text,
                "hotel_candidates": [c.model_dump() for c in cands],
                "hotel_status": "success",
                "hotel_selected": hotel_selected}
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
        # v3: 自由活动日/远郊日豁免"每天 ≥2 景点"硬伤（聚类边界，非 LLM 失误）
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
            "planner_last_error": "",  # 清掉上一轮解析失败原因（本轮是硬伤重试）
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


# ================================================================
# v3: 分日并发（Send API 动态 fan-out）
# ================================================================

def _fan_out(state: TripPlannerState) -> list[Send]:
    """conditional path: 按聚类结果动态分发 N 个 day_node（Send API，原生并行）。

    实测确认（LangGraph 1.2.9）: Send 分支的 state 只含 payload（不合并共享 state），
    因此 day_node 需要的全部上下文必须显式注入 payload。
    """
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
            # ── 共享上下文显式注入（Send 分支 state 隔离）──
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
                       state: TripPlannerState) -> str:
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

    lines.append(
        '请只输出 JSON 对象: {"description": "第N天行程概述(80字内)", '
        '"transportation": "市内交通建议(50字内)", '
        '"accommodation": "住宿说明(30字内)", '
        '"overall_tips": "当天贴心建议(50字内)"}'
    )
    return "\n".join(lines)


def day_node(state: TripPlannerState, config: dict | None = None) -> dict:
    """单日计划节点（Send 并行实例，每天一次 LLM 文案调用）。

    v3 职责划分:
    - 景点集合: 聚类分配（数据层互斥，LLM 不选点 → 跨天零重复）
    - 景点顺序/时间: route_solver 本地求解（贪心+2-opt+时间窗硬检查）
    - LLM 只写文案: description/transportation/accommodation/tips（JSON mode）
    - 韧性: leisure 天零 LLM；文案 LLM 失败 → 本地模板兜底，不阻断全链路
    """
    idx = state.get("day_index", 0)
    kind = state.get("day_kind", "normal")
    pois = state.get("day_pois", [])
    date = state.get("day_date", "")

    day: dict = {
        "date": date, "day_index": idx, "kind": kind,
        "description": "", "transportation": "", "accommodation": "",
        "hotel": {}, "attractions": [], "meals": [], "overall_tips": "",
    }

    # ── 自由活动日: 零 LLM，本地模板 ──
    if kind == LEISURE:
        day["description"] = f"第{idx + 1}天自由活动，可逛街购物、品尝当地美食、休整充电。"
        day["transportation"] = "市内交通建议：优先地铁/公交。"
        day["overall_tips"] = "注意防晒补水，预留机动时间。"
        _emit(config, "planner", "done", {"day_index": idx, "status": "leisure"})
        return {"plan_days": [day]}

    _emit(config, "planner", "start", {"day_index": idx, "kind": kind})

    # ── 本地路径求解（确定性，不交 LLM）──
    start_pt = None
    hotel = state.get("hotel_selected") or {}
    if hotel.get("lng") and hotel.get("lat"):
        start_pt = {"lng": hotel["lng"], "lat": hotel["lat"]}
    plan = solve_daily_route(pois, state.get("day_start_hour", 9),
                             state.get("day_end_hour", 20), start=start_pt)
    window_ok = True
    if not plan:
        # 时间窗无法容纳全部点 → 软伤降级：全量点按聚类顺序（无时间标注）
        window_ok = False
        plan = [{"poi": p, "arrive_min": 0, "depart_min": 0, "travel_min_from_prev": 0}
                for p in pois]
    attractions = format_plan(plan)

    # ── LLM 文案（失败本地兜底，不阻断）──
    text = _format_day_prompt(idx, date, kind, attractions, state)
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
    except Exception as exc:
        day["description"] = f"第{idx + 1}天：游览{'、'.join(a['name'] for a in attractions)}。"
        day["transportation"] = "市内交通建议：优先地铁/公交。"
        day["overall_tips"] = "注意防晒补水，预留机动时间。"
        status = "llm_fallback"

    day["attractions"] = attractions
    if not window_ok:
        status = "window_fallback"
    _emit(config, "planner", "done", {"day_index": idx, "status": status})
    result: dict = {"plan_days": [day]}
    if status == "llm_fallback":
        result["error_log"] = [f"第{idx + 1}天文案生成失败（已用本地模板）"]
    if not window_ok:
        result["error_log"] = result.get("error_log", []) +             [f"第{idx + 1}天景点总时长超日窗口，已降级为无时间标注顺序"]
    return result


# ================================================================
# v3: 聚合节点（Send 汇聚只触发 1 次，实测确认）
# ================================================================

def _parse_weather_data(text: str) -> list[dict]:
    """本地解析天气文本（_format_weather 固定格式）→ 结构化 weather_info。

    格式: "- 2026-08-21: 晴转多云, 25°C~15°C, 南风"
    解析失败返回空列表（软伤降级），不交 LLM。
    """
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
    """本地预算计算（确定性，不交 LLM）:
    门票 = Σ POI.price；住宿 = 酒店中值价 × 天数；餐饮 = Σ meals.estimated_cost；
    交通 = 城际 cost + 市内 50 元/天。"""
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
    """聚合节点（Send 分支汇聚，实测只触发 1 次）: 排序 → 填充 → 校验 → final_plan。

    本地完成: 酒店填充（全程同一家）、三餐真实 POI、天气结构化解析、预算计算。
    校验失败场景在本地链路中极少（聚类保证每天≥2 景点、预算本地算不超），
    硬伤/软伤仍记录 error_log（降级透明），不回环重试。
    """
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

    # ── 1. 天气结构化（本地解析）──
    weather_info = _parse_weather_data(state.get("weather_data", ""))
    if not weather_info:
        error_log.append("天气数据解析失败，天气信息为空（降级）")

    # ── 2. 酒店填充（全程同一家，本地选定）──
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

    # ── 3. 本地预算（先算，plan 校验需要 budget）──
    budget = _compute_budget(days, state)

    # ── 4. 三餐真实 POI 填充（复用既有机制）──
    plan = {"city": city,
            "start_date": state.get("start_date", ""),
            "days": days,
            "budget": budget,
            "overall_suggestions": ""}
    _enrich_meals(plan, city)

    # ── 5. 校验（软伤记录，硬伤不回环——本地链路已保证）──
    validation = _validate_and_refine(state, plan)
    error_log.extend(validation.get("error_log", []))
    if validation.get("planner_route") == "retry_planner":
        # 本地链路出现硬伤说明上游数据异常，记录后仍交付（透明降级）
        error_log.append("校验发现硬伤但本地链路无法重试，已按当前结果交付")

    # ── 6. 组装 final_plan ──
    tips = [d.get("overall_tips", "") for d in days if d.get("overall_tips")]
    overall = "；".join(tips)[:200] if tips else         "祝旅途愉快！建议提前预约热门景点门票，预留机动时间。"
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
