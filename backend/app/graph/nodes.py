"""LangGraph Node 函数 — 支持 SSE 进度事件"""
from .state import TripPlannerState
from ..agents.trip_planner_agent import get_planner

_emitter = None

def set_emitter(emitter):
    global _emitter; _emitter = emitter

def _emit(node, status, data=None):
    if _emitter: _emitter.emit(node, status, data)


def attraction_node(state: TripPlannerState) -> dict:
    _emit("attraction", "start")
    city = state["city"]
    prefs = state.get("preferences", [])
    try:
        planner = get_planner()
        kw = prefs[0] if prefs else "景点"
        result = planner.attraction_agent.run(
            f"请搜索{city}的{kw}相关景点。\n"
            f"[TOOL_CALL:amap_maps_text_search:keywords={kw},city={city}]"
        )
        _emit("attraction", "done", {"status": "success"})

        # ── 计算景点群物理中心（本地 Python，不交 LLM）──
        import re
        coords = re.findall(r"📍\(([\d.]+),([\d.]+)\)", result)
        parsed = [{"name": "?", "lng": float(c[0]), "lat": float(c[1])} for c in coords]
        center = {}
        if parsed:
            clng = sum(p["lng"] for p in parsed) / len(parsed)
            clat = sum(p["lat"] for p in parsed) / len(parsed)
            center = {"center_lng": round(clng, 6), "center_lat": round(clat, 6),
                      "attraction_coords": parsed}
            print(f"🗺️  [中心计算] 景点数={len(parsed)} center_lng={round(clng,6)} center_lat={round(clat,6)}")
        else:
            print(f"⚠️  [中心计算] 未找到坐标标记，跳过中心计算")

        return {"attraction_data": result, "attraction_status": "success", **center}
    except Exception as e:
        _emit("attraction", "done", {"status": "failed"})
        return {"attraction_data": "", "attraction_status": "failed",
                "error_log": [f"景点搜索失败: {str(e)}"]}


def hotel_node(state: TripPlannerState) -> dict:
    _emit("hotel", "start")
    city = state["city"]
    try:
        planner = get_planner()
        # 优先使用覆写中心（离群检测后），其次原始中心
        clng = state.get("center_lng_override") or state.get("center_lng")
        clat = state.get("center_lat_override") or state.get("center_lat")
        if clng and clat:
            override = state.get("center_lng_override")
            tag = "覆写中心" if override else "原始中心"
            print(f"🏨 [酒店搜索] 使用{tag} center=({clng},{clat})")
            result = planner.hotel_agent.run(
                f"请以坐标({clng},{clat})为中心搜索{city}的酒店。\n"
                f"[TOOL_CALL:amap_search:city={city},type=around,center={clng},{clat},keywords=酒店]"
            )
        else:
            # 退化为全城搜索
            print(f"🏨 [酒店搜索] 无中心坐标，退化为全城搜索")
            result = planner.hotel_agent.run(
                f"请搜索{city}的酒店。\n[TOOL_CALL:amap_maps_text_search:keywords=酒店,city={city}]"
            )
        _emit("hotel", "done", {"status": "success"})
        return {"hotel_data": result, "hotel_status": "success"}
    except Exception as e:
        _emit("hotel", "done", {"status": "failed"})
        return {"hotel_data": "", "hotel_status": "failed",
                "error_log": [f"酒店搜索失败: {str(e)}"]}


def memory_node(state: TripPlannerState) -> dict:
    _emit("memory", "start")
    from ..memory.manager import get_memory
    try:
        profile = get_memory().get_profile()
        _emit("memory", "done")
        return {"user_profile": profile}
    except Exception as e:
        _emit("memory", "done", {"status": "failed"})
        return {"error_log": [f"记忆加载失败: {str(e)}"]}


# ── 常量 ──
MAX_RETRY = 3               # Planner 自回环最大次数
OUTLIER_DIST_FACTOR = 2.0   # 离群距离 > 平均值 * 这个因子 → 标记为离群
MAX_HOTEL_DIST_KM = 10      # 酒店到最远景点距离阈值（软伤）
BUDGET_OVER_PCT = 0.3       # 预算超用户偏好 30%（硬伤）


def _haversine_km(lng1: float, lat1: float, lng2: float, lat2: float) -> float:
    """两点间 Haversine 直线距离 (km)"""
    import math
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlng / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _validate_and_refine(state: TripPlannerState, plan: dict) -> dict:
    """本地校验：硬伤/软伤/离群检测 → 返回 {route, ...}"""
    import math

    retry_count = state.get("planner_retry_count", 0)
    days = state.get("days", 1)
    profile = state.get("user_profile", {})
    error_log: list[str] = []
    hard_errors: list[str] = []

    # ── 1a. 硬伤检测 ──
    plan_days = plan.get("days", [])
    if not plan_days:
        hard_errors.append("plan 缺少 .days 字段")

    # 每天景点数
    for d in plan_days:
        attrs = d.get("attractions", [])
        if len(attrs) < 2:
            hard_errors.append(f"{d.get('date', '?')}: 景点数 {len(attrs)} < 2")

    # 必填字段
    required = ["city", "start_date", "days", "budget", "overall_suggestions"]
    for f in required:
        if f not in plan:
            hard_errors.append(f"缺少必填字段: {f}")

    # 预算超 30%
    budget = plan.get("budget", {})
    total = budget.get("total", 0) if isinstance(budget, dict) else 0
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

    # 酒店到最远景点距离
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

    # 天气不适宜（暴雨 + 户外景点）
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

    # ── 1c. 离群景点检测 ──
    coords = state.get("attraction_coords", [])
    override_lng, override_lat = None, None
    outlier_names: list[str] = []

    if coords and len(coords) >= 3:
        # 原始中心
        orig_clng = state.get("center_lng", 0)
        orig_clat = state.get("center_lat", 0)

        # 计算每个景点到中心距离
        dists = []
        for c in coords:
            d = _haversine_km(orig_clng, orig_clat, c["lng"], c["lat"])
            dists.append(d)

        avg_dist = sum(dists) / len(dists) if dists else 0
        threshold = avg_dist * OUTLIER_DIST_FACTOR

        # 标记离群
        inliers = []
        for i, c in enumerate(coords):
            if dists[i] > threshold or dists[i] > avg_dist * OUTLIER_DIST_FACTOR:
                name = c.get("name", f"景点{i}")
                outlier_names.append(name)
            else:
                inliers.append(c)

        # 去掉离群景点重新算中心
        if outlier_names and inliers:
            override_lng = round(sum(c["lng"] for c in inliers) / len(inliers), 6)
            override_lat = round(sum(c["lat"] for c in inliers) / len(inliers), 6)
            warnings.append(
                f"离群景点: {', '.join(outlier_names)} → 新中心 ({override_lng}, {override_lat})")

    # ── 返回路由决策 ──
    if hard_errors and retry_count < MAX_RETRY:
        error_log.append(f"硬伤 #{retry_count + 1}: {'; '.join(hard_errors)}")
        return {
            "error_log": error_log,
            "planner_route": "retry_planner",
            "planner_retry_count": retry_count + 1,
        }

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

    # 如果有离群景点 → 写入 override 并触发 retry_hotel
    if override_lng is not None and override_lat is not None:
        result["center_lng_override"] = override_lng
        result["center_lat_override"] = override_lat
        result["planner_route"] = "retry_hotel"

    return result


def _build_profile_constraints(profile: dict) -> str:
    """根据用户画像生成约束指令注入 LLM prompt"""
    constraints = []

    budget_tier = profile.get("budget_tier", "")
    if budget_tier == "穷游":
        constraints.append("- 优先免费景点，预算 < 500 元/天")

    diet = profile.get("diet", [])
    if any("不吃辣" in d for d in diet):
        constraints.append("- 避免川菜、湘菜等辣味菜系")

    accommodation = profile.get("accommodation", "")
    if "经济型" in accommodation:
        constraints.append("- 推荐经济型酒店，控制住宿预算")

    pace = profile.get("pace", "")
    if pace == "紧凑高效":
        constraints.append("- 每天至少 3 个景点，行程紧凑")

    if constraints:
        return "\n**画像约束指令（必须遵守）:**\n" + "\n".join(constraints) + "\n"
    return ""


def planner_node(state: TripPlannerState) -> dict:
    _emit("planner", "start")
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

    # ── 画像指令注入 ──
    profile_constraints = _build_profile_constraints(profile)

    dates_str = ", ".join(date_list) if date_list else "请自行推断"
    date_req = f"每天日期必须按顺序使用: {dates_str}" if date_list else ""

    dist = state.get("intercity_distance_km", 0)
    ic_text = ""
    if dist > 0:
        ic_text = (f"\n**城际交通:** {state.get('transport_mode', '高铁')} · "
                   f"{dist}km · 约{state.get('intercity_duration_h', 0)}h · "
                   f"¥{state.get('intercity_cost', 0)}\n")

    # 重试时追加提示
    retry_hint = ""
    if retry_count > 0:
        retry_hint = (f"\n⚠️ 第{retry_count}次重试——上次生成的计划有硬伤，"
                      f"请务必修正以下问题并严格遵守约束！\n")

    query = f"""请根据以下信息生成{state['days']}天旅行计划:

{ic_text}
出发地: {origin if origin else '未指定'}
目的地: {city}
日期: {date_req}
天数: {state['days']}天

景点信息:
{state.get('attraction_data', '无')}

天气信息:
{state.get('weather_data', '无')}

酒店信息:
{state.get('hotel_data', '无')}

用户偏好: {', '.join(prefs) if prefs else '无'}
{profile_description}
{profile_constraints}{retry_hint}
{('【注意】' + '; '.join(warnings) if warnings else '')}
"""
    planner = get_planner()
    result = planner.planner_agent.run(query)
    plan = planner._parse_plan(result)

    # ── 本地校验/离群检测/画像指令注入 ──
    validation = _validate_and_refine(state, plan)

    _emit("planner", "done")

    return {"final_plan": plan, **validation}
