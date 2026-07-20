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
        return {"attraction_data": result, "attraction_status": "success"}
    except Exception as e:
        _emit("attraction", "done", {"status": "failed"})
        return {"attraction_data": "", "attraction_status": "failed",
                "error_log": [f"景点搜索失败: {str(e)}"]}


def weather_node(state: TripPlannerState) -> dict:
    _emit("weather", "start")
    city = state["city"]
    try:
        planner = get_planner()
        result = planner.weather_agent.run(
            f"请查询{city}的天气。\n[TOOL_CALL:amap_maps_weather:city={city}]"
        )
        _emit("weather", "done", {"status": "success"})
        return {"weather_data": result, "weather_status": "success"}
    except Exception as e:
        _emit("weather", "done", {"status": "failed"})
        return {"weather_data": "", "weather_status": "failed",
                "error_log": [f"天气查询失败: {str(e)}"]}


def hotel_node(state: TripPlannerState) -> dict:
    _emit("hotel", "start")
    city = state["city"]
    try:
        planner = get_planner()
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


def planner_node(state: TripPlannerState) -> dict:
    _emit("planner", "start")
    city = state["city"]
    origin = state.get("origin", "")
    date_list = state.get("date_list", [])
    prefs = state.get("preferences", [])
    profile = state.get("user_profile", {})

    warnings = []
    for n, k in [("景点", "attraction"), ("天气", "weather"), ("酒店", "hotel")]:
        if state.get(f"{k}_status") == "failed":
            warnings.append(f"⚠️ {n}数据不可用，已使用降级方案")

    profile_text = ""
    if profile:
        parts = []
        for k, label in [("accommodation", "酒店档次"), ("budget_tier", "预算偏好"),
                          ("pace", "旅行节奏")]:
            if profile.get(k): parts.append(f"- {label}: {profile[k]}")
        for k, label in [("diet", "饮食"), ("transport", "交通"), ("interests", "兴趣")]:
            if profile.get(k): parts.append(f"- {label}: {', '.join(profile[k])}")
        if parts: profile_text = "**用户画像:**\n" + "\n".join(parts)

    dates_str = ", ".join(date_list) if date_list else "请自行推断"
    date_req = f"每天日期必须按顺序使用: {dates_str}" if date_list else ""

    dist = state.get("intercity_distance_km", 0)
    ic_text = ""
    if dist > 0:
        ic_text = (f"\n**城际交通:** {state.get('transport_mode', '高铁')} · "
                   f"{dist}km · 约{state.get('intercity_duration_h', 0)}h · "
                   f"¥{state.get('intercity_cost', 0)}\n")

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
{profile_text}
{'【注意】' + '; '.join(warnings) if warnings else ''}
"""
    planner = get_planner()
    result = planner.planner_agent.run(query)
    plan = planner._parse_plan(result)
    _emit("planner", "done")
    return {"final_plan": plan}
