"""LangGraph Node 函数

Phase 3 核心概念 #2: Node

每个 Node 是一个纯函数: (state) → partial_update
返回的 dict 会由 LangGraph 自动 merge 回全局 State。

与 Phase 2 的关键区别:
  Phase 2: 自主管理错误——try/except 在外层，失败了后面全不跑
  Phase 3: Error-as-Observation——每个 Node 内部 catch 异常，
           失败记入 state.error_log + status="failed"，
           下游 Node 自己决定降级策略
"""
from .state import TripPlannerState
from ..agents.trip_planner_agent import get_planner


def attraction_node(state: TripPlannerState) -> dict:
    """
    Node 1: 景点搜索。

    调用景点搜索 Agent（SimpleAgent + MCPTool），
    成功 → attraction_data 填结果
    失败 → attraction_data 留空，attraction_status="failed"
           不抛异常——下游 weather_node 会继续执行
    """
    city = state["city"]
    prefs = state.get("preferences", [])

    try:
        planner = get_planner()
        keywords = prefs[0] if prefs else "景点"
        query = (
            f"请搜索{city}的{keywords}相关景点。\n"
            f"[TOOL_CALL:amap_maps_text_search:keywords={keywords},city={city}]"
        )
        result = planner.attraction_agent.run(query)

        return {
            "attraction_data": result,
            "attraction_status": "success",
        }
    except Exception as e:
        return {
            "attraction_data": "",
            "attraction_status": "failed",
            "error_log": [f"景点搜索失败: {str(e)}"],
        }


def weather_node(state: TripPlannerState) -> dict:
    """
    Node 2: 天气查询。

    不论 attraction_node 成功与否，本 Node 都会执行。
    这是 conditional routing 的关键——Edge 定义了"跳过"而非 Node 自己判断。
    """
    city = state["city"]

    try:
        planner = get_planner()
        query = f"请查询{city}的天气。\n[TOOL_CALL:amap_maps_weather:city={city}]"
        result = planner.weather_agent.run(query)

        return {
            "weather_data": result,
            "weather_status": "success",
        }
    except Exception as e:
        return {
            "weather_data": "",
            "weather_status": "failed",
            "error_log": [f"天气查询失败: {str(e)}"],
        }


def hotel_node(state: TripPlannerState) -> dict:
    """Node 3: 酒店搜索"""
    city = state["city"]

    try:
        planner = get_planner()
        query = (
            f"请搜索{city}的酒店。\n"
            f"[TOOL_CALL:amap_maps_text_search:keywords=酒店,city={city}]"
        )
        result = planner.hotel_agent.run(query)

        return {
            "hotel_data": result,
            "hotel_status": "success",
        }
    except Exception as e:
        return {
            "hotel_data": "",
            "hotel_status": "failed",
            "error_log": [f"酒店搜索失败: {str(e)}"],
        }


def planner_node(state: TripPlannerState) -> dict:
    """
    Node 5: 行程规划。

    整合前三者数据 + 用户画像，生成个性化旅行计划。

    用户画像（Phase 6 集成）:
      如果 state 中有 user_profile，Planner Agent 会参考:
      - 酒店档次（经济/舒适/豪华）
      - 预算区间
      - 饮食偏好
      - 交通偏好
      这使行程推荐从"通用推荐"变成"个性化推荐"。
    """
    city = state["city"]
    origin = state.get("origin", "")
    days = state["days"]
    date_list = state.get("date_list", [])
    prefs = state.get("preferences", [])
    profile = state.get("user_profile", {})

    warnings = []
    if state.get("attraction_status") == "failed":
        warnings.append("⚠️ 景点数据不可用，行程中景点为通用推荐")
    if state.get("weather_status") == "failed":
        warnings.append("⚠️ 天气数据不可用，请根据季节准备衣物")
    if state.get("hotel_status") == "failed":
        warnings.append("⚠️ 酒店数据不可用，住宿为通用推荐")

    planner = get_planner()

    # 用户画像文本
    profile_text = ""
    if profile:
        profile_parts = []
        if profile.get("hotel_tier"):
            profile_parts.append(f"- 酒店档次偏好: {profile['hotel_tier']}")
        if profile.get("budget_range"):
            profile_parts.append(f"- 预算范围: {profile['budget_range']}")
        if profile.get("diet"):
            profile_parts.append(f"- 饮食偏好: {', '.join(profile['diet'])}")
        if profile.get("transport"):
            profile_parts.append(f"- 交通偏好: {', '.join(profile['transport'])}")
        if profile.get("preferences"):
            profile_parts.append(f"- 其他偏好: {'; '.join(profile['preferences'][:5])}")
        if profile_parts:
            profile_text = "**用户画像（基于历史行为统计）:**\n" + "\n".join(profile_parts)

    # 预计算日期（本地 Python，不依赖 LLM）
    dates_str = ", ".join(date_list) if date_list else "请自行推断"
    date_requirement = f"每天日期必须按顺序使用: {dates_str}" if date_list else "请使用合理的日期"

    # 城际交通信息
    dist = state.get("intercity_distance_km", 0)
    dur = state.get("intercity_duration_h", 0)
    ic_cost = state.get("intercity_cost", 0)
    dist_cat = state.get("distance_category", "")
    tmode = state.get("transport_mode", "高铁")
    intercity_text = ""
    if dist > 0:
        intercity_text = f"""
**城际交通:**
- 方式: {tmode}
- 距离: {dist}km（{dist_cat}）
- 预估时间: {dur}小时
- 预估费用: ¥{ic_cost}
"""

    query = f"""请根据以下信息生成{days}天旅行计划:

{intercity_text}
出发地: {origin if origin else '未指定'}
目的地: {city}
日期: {date_requirement}
天数: {days}天

景点信息:
{state.get('attraction_data', '无景点数据')}

天气信息:
{state.get('weather_data', '无天气数据')}

酒店信息:
{state.get('hotel_data', '无酒店数据')}

用户偏好: {', '.join(prefs) if prefs else '无'}
{profile_text}
{'【注意】' + '; '.join(warnings) if warnings else ''}
"""
    result = planner.planner_agent.run(query)
    plan = planner._parse_plan(result)

    return {"final_plan": plan}


def memory_node(state: TripPlannerState) -> dict:
    """
    Node 4: 记忆加载（Phase 6 集成）。

    从记忆模块加载用户画像，注入 State。
    这个 Node 不调 LLM，不调外部 API——纯本地读取。

    为什么是独立的 Node 而非 planner_node 内部调？
    - 职责分离: memory_node 管数据获取，planner_node 管推理
    - 可测试性: 可以单独 mock memory_node
    - 可扩展: 后续可以加 RAG、向量检索等更复杂的记忆策略
    """
    from ..memory.manager import get_memory

    try:
        memory = get_memory()
        profile = memory.get_profile()
        return {"user_profile": profile}
    except Exception as e:
        return {"error_log": [f"记忆加载失败: {str(e)}"]}
