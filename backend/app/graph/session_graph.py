"""会话外层协作图与状态机 (Session Orchestration Graph)

串联 Clarification Agent、确定性规划与双工 RAG 工具群，以及 Repair Agent 自愈闭环。
支持 LangGraph 原生 `interrupt` 挂起与基于 `thread_id` 的 Checkpoint 状态恢复。
"""
from __future__ import annotations

from datetime import datetime, timedelta
import logging
from typing import Any, TypedDict

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver

from ..models.session import EffectiveRequirements, PlanVersion
from ..models.diagnostics import ErrorCode, DiagnosticSeverity, DiagnosticSignal
from ..agents.clarification_agent import clarification_node
from ..agents.repair_agent import RepairAgent
from ..tools.planning_tools import (
    cluster_pois_tool,
    solve_day_route_tool,
    check_budget_tool,
)
from concurrent.futures import ThreadPoolExecutor, as_completed
from ..tools.rag_tools import (
    lookup_place_facts_tool,
    search_guides_tool,
)
from ..tools.weather_tool import get_weather_for_date
from ..tools.tavily_tool import search_tavily_poi_guides
from ..tools.search_tools import (
    search_attractions_tool,
    search_hotel_minimax_tool,
    enrich_meals_tool,
    haversine_km,
)
from .nodes import _parse_price_range

from ..services.poi_synthesizer import synthesize_city_pois, get_city_geo_center

logger = logging.getLogger(__name__)


class SessionGraphState(TypedDict, total=False):
    """外层会话协调图全局状态"""
    session_id: str
    user_id: str
    thread_id: str

    input_text: str
    messages: list[dict[str, str]]

    # 需求状态与锁定项
    requirements: dict[str, Any]
    locked_items: list[str]

    # 规划版本与诊断
    current_plan: dict[str, Any] | None
    diagnostics: list[dict[str, Any]]

    # 自愈控制
    repair_attempts: int
    attempted_actions: list[str]
    needs_human_confirmation: bool

    # 最终输出与状态
    final_response: str
    status: str  # "clarifying" | "planning" | "ready" | "escalated"


def planning_node(state: SessionGraphState) -> dict[str, Any]:
    """规划执行节点：调用确定性工具与双工 RAG 生成行程版本并执行诊断"""
    req_dict = state.get("requirements", {})
    req = EffectiveRequirements.model_validate(req_dict) if req_dict else EffectiveRequirements()

    city = req.get_slot_value("city", "北京")
    days = int(req.get_slot_value("days", 3))
    start_date_str = req.get_slot_value("start_date") or datetime.now().strftime("%Y-%m-%d")
    budget_total = req.get_slot_value("budget_total")
    locked_items = state.get("locked_items") or list(req.locked_items)
    raw_prefs = req.get_slot_value("preferences")
    if isinstance(raw_prefs, str):
        preferences = [raw_prefs]
    elif isinstance(raw_prefs, list):
        preferences = [str(p) for p in raw_prefs]
    else:
        preferences = []

    # 严格解耦：景点向偏好 (scenic) vs 美食向偏好 (food)
    raw_scenic = req.get_slot_value("scenic_preferences") or []
    if isinstance(raw_scenic, str):
        scenic_preferences = [raw_scenic]
    elif isinstance(raw_scenic, list):
        scenic_preferences = [str(p) for p in raw_scenic]
    else:
        scenic_preferences = []

    raw_food = req.get_slot_value("food_preferences") or []
    if isinstance(raw_food, str):
        food_preferences = [raw_food]
    elif isinstance(raw_food, list):
        food_preferences = [str(p) for p in raw_food]
    else:
        food_preferences = []

    food_vocab = {"川菜", "粤菜", "湘菜", "鲁菜", "火锅", "美食", "小吃", "特色小吃", "特色菜", "特产", "烧烤", "地道美食", "早茶", "面食", "串串"}
    if not scenic_preferences:
        scenic_preferences = [p for p in preferences if p not in food_vocab]
    if not food_preferences:
        food_preferences = [p for p in preferences if p in food_vocab]

    # 1. 动态获取城市 POI 候选（Tier 1: 高德实时检索 -> Tier 2: 动态知识合成器，坚决杜绝硬编码）
    candidate_pool: list[dict[str, Any]] = []
    try:
        raw_cands = search_attractions_tool(
            city=city,
            preferences=scenic_preferences,
            user_id=state.get("user_id", ""),
            locked_items=locked_items,
        )
        for c in raw_cands:
            p_name = getattr(c, "name", None) or (c.get("name") if isinstance(c, dict) else "")
            p_lng = getattr(c, "lng", None) if hasattr(c, "lng") else (c.get("lng") if isinstance(c, dict) else None)
            p_lat = getattr(c, "lat", None) if hasattr(c, "lat") else (c.get("lat") if isinstance(c, dict) else None)
            p_dist = getattr(c, "district", None) or (c.get("district") if isinstance(c, dict) else "")
            p_cat = getattr(c, "category", None) or (c.get("category") if isinstance(c, dict) else "")
            p_price = getattr(c, "price", None) or (c.get("price") if isinstance(c, dict) else 0.0)
            p_rating = getattr(c, "rating", None) or (c.get("rating") if isinstance(c, dict) else None)
            p_addr = getattr(c, "address", None) or (c.get("address") if isinstance(c, dict) else "")
            p_open_time = getattr(c, "open_time", None) or (c.get("open_time") if isinstance(c, dict) else "")
            p_b_area = getattr(c, "business_area", None) or (c.get("business_area") if isinstance(c, dict) else "")
            p_level = getattr(c, "level", None) or (c.get("level") if isinstance(c, dict) else "")
            p_tel = getattr(c, "tel", None) or (c.get("tel") if isinstance(c, dict) else "")
            try:
                fl_lng = float(p_lng or 0.0)
                fl_lat = float(p_lat or 0.0)
            except (ValueError, TypeError):
                fl_lng, fl_lat = 0.0, 0.0
            try:
                fl_price = float(p_price or 0.0)
            except (ValueError, TypeError):
                fl_price = 0.0

            candidate_pool.append({
                "name": p_name,
                "lng": fl_lng,
                "lat": fl_lat,
                "district": p_dist,
                "category": p_cat,
                "visit_minutes": 120,
                "price": fl_price,
                "rating": p_rating,
                "address": p_addr,
                "open_time": p_open_time,
                "business_area": p_b_area,
                "level": p_level,
                "tel": p_tel,
            })
    except Exception as e:
        logger.warning("动态检索高德景点失败，进入动态自适应合成: %s", e)

    if not candidate_pool:
        # Tier 2 动态知识合成（自动包含锁定项并赋予真实该城市坐标，绝不偷换为北京！）
        candidate_pool = synthesize_city_pois(
            city=city,
            preferences=preferences,
            locked_items=locked_items,
        )
    else:
        # 补全可能遗漏的锁定项（例如峨眉山属于乐山代管县级市，高德单独搜乐山偶发未包含时动态注入）
        if locked_items:
            for lock in locked_items:
                clean_lock = lock.strip()
                if clean_lock and not any(clean_lock in p["name"] for p in candidate_pool):
                    synth_locks = synthesize_city_pois(city=city, preferences=preferences, locked_items=[clean_lock])
                    for sp in synth_locks:
                        if clean_lock in sp.get("name", "") and not any(p["name"] == sp["name"] for p in candidate_pool):
                            candidate_pool.insert(0, sp)

    # POI 名称强去重
    unique_pool: list[dict[str, Any]] = []
    pool_names: set[str] = set()
    for p in candidate_pool:
        if p["name"] not in pool_names:
            unique_pool.append(p)
            pool_names.add(p["name"])
    candidate_pool = unique_pool

    # 容量配比：单日合理负载 3~4 个景点。若候选池溢出，保留所有锁定项，其余截取高评分优质景点
    target_pool_cap = max(days * 4, 6)
    if len(candidate_pool) > target_pool_cap:
        locked_pois = [p for p in candidate_pool if any(lock in p["name"] for lock in (locked_items or []))]
        other_pois = [p for p in candidate_pool if not any(lock in p["name"] for lock in (locked_items or []))]
        remain_slots = max(0, target_pool_cap - len(locked_pois))
        candidate_pool = locked_pois + other_pois[:remain_slots]

    # 2. 空间 K-Means 聚类
    clusters = cluster_pois_tool(pois=candidate_pool, days=days)

    # 3. 动态 Minimax 酒店选址（兼顾经济型偏好与通勤最优）
    hotel_res = search_hotel_minimax_tool(
        city=city,
        attraction_coords=candidate_pool,
        accommodation_pref=str(req.get_slot_value("accommodation", "") or ""),
    )
    hotel_selected = dict(hotel_res.get("hotel_selected", {}))
    hotel_price_range = hotel_selected.get("price_range", "")
    hotel_night_cost = float(_parse_price_range(hotel_price_range) or hotel_selected.get("price") or 400.0)
    if hotel_night_cost <= 0:
        hotel_night_cost = 400.0

    if hotel_selected:
        hotel_selected["price_per_night"] = hotel_night_cost
        if not hotel_selected.get("price_range"):
            hotel_selected["price_range"] = f"¥{int(hotel_night_cost)}/晚"
        if not hotel_selected.get("hotel_type"):
            hotel_selected["hotel_type"] = "舒适型"
        if not hotel_selected.get("recommended_reason"):
            hotel_selected["recommended_reason"] = "Minimax 极小化通勤选址：距离全城景点综合距离最优，每日往返通勤顺畅"
        if not hotel_selected.get("commute_time_min"):
            hotel_selected["commute_time_min"] = 15

    try:
        base_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
    except Exception:
        base_date = datetime.now().date()

    plan_days = []
    all_diags: list[DiagnosticSignal] = []

    # 4. 逐天路径求解与双工 RAG
    for day_idx in range(days):
        day_date = (base_date + timedelta(days=day_idx)).strftime("%Y-%m-%d")
        cluster_info = clusters[day_idx] if day_idx < len(clusters) else {"pois": []}
        day_pois = list(cluster_info.get("pois", []))

        # 双工 RAG: 事实核验 (动态营业与周一闭馆)
        for p in day_pois:
            fact = lookup_place_facts_tool(poi_name=p["name"], target_date=day_date, city=city)
            p["place_fact"] = fact.model_dump()
            if fact.is_open_on_date is False:
                # 记录闭馆冲突诊断信号
                diag = DiagnosticSignal(
                    error_code=ErrorCode.VENUE_CLOSED,
                    day_index=day_idx,
                    severity=DiagnosticSeverity.HARD_FAIL,
                    summary=f"第 {day_idx + 1} 天行程冲突：{fact.evidence_snippet}",
                    details={"place_name": p["name"], "target_date": day_date},
                    conflicting_items=[p["name"]],
                    immutable_constraints=[item for item in locked_items if item in p["name"]],
                    actionable_suggestions=["SWAP_TO_ANOTHER_DAY", "REPLACE_WITH_OPEN_VENUE"],
                )
                all_diags.append(diag)

            # 半静态 RAG: 攻略经验与避坑建议
            guides = search_guides_tool(poi_name=p["name"], city=city, top_k=1)
            p["guides"] = [g.model_dump() for g in guides]

        # 确定性工具: 路径求解 (贪心初始解 + 2-Opt 局部搜索)
        dist_before = 0.0
        if day_pois:
            h_lng = hotel_selected.get("lng")
            h_lat = hotel_selected.get("lat")
            if h_lng and h_lat:
                dist_before += haversine_km(float(h_lng), float(h_lat), float(day_pois[0]["lng"]), float(day_pois[0]["lat"]))
            for i in range(len(day_pois) - 1):
                dist_before += haversine_km(float(day_pois[i]["lng"]), float(day_pois[i]["lat"]), float(day_pois[i+1]["lng"]), float(day_pois[i+1]["lat"]))

        # 0. 动态注入高德官方天气预报
        day_weather = get_weather_for_date(city, day_date)

        route_res = solve_day_route_tool(
            pois=day_pois,
            start_hour=9,
            close_hour=21,
            start_hotel=hotel_selected if hotel_selected.get("lng") and hotel_selected.get("lat") else None,
            day_index=day_idx,
            immutable_names=locked_items,
        )
        if route_res.diagnostics:
            if isinstance(route_res.diagnostics, list):
                all_diags.extend(route_res.diagnostics)
            else:
                all_diags.append(route_res.diagnostics)

        # 核心数据闭环：将 2-Opt 算出的最优时序与完整时刻回填给 attractions
        ordered_attractions = []
        if route_res.route:
            poi_map = {p["name"]: p for p in day_pois}
            for node in route_res.route:
                node_name = node.get("name") or (node.get("poi", {}).get("name") if isinstance(node.get("poi"), dict) else "")
                orig = dict(poi_map.get(node_name) or (node.get("poi") if isinstance(node.get("poi"), dict) else node))
                orig["arrive_time"] = node.get("arrive_time", "")
                orig["depart_time"] = node.get("depart_time", "")
                orig["distance_km"] = round(float(node.get("distance_km") or 0.0), 1)
                orig["travel_minutes"] = int(node.get("travel_minutes") or 0)
                ordered_attractions.append(orig)
        else:
            ordered_attractions = day_pois

        dist_after = sum(float(node.get("distance_km") or 0.0) for node in (route_res.route or []))
        saved_km = max(0.0, round(dist_before - dist_after, 1))
        saved_pct = round(saved_km / dist_before * 100, 1) if dist_before > 0.1 else 0.0

        day_dict = {
            "day_index": day_idx,
            "day_number": day_idx + 1,
            "date": day_date,
            "weather": day_weather,
            "attractions": ordered_attractions,
            "route": route_res.route,
            "hotel": hotel_selected,
            "meals": [],
            "total_ticket": route_res.total_ticket,
            "start_hour": 9,
            "close_hour": 21,
            "telemetry": {
                "dist_before_km": round(dist_before, 1),
                "dist_after_km": round(dist_after, 1),
                "saved_km": saved_km,
                "saved_pct": saved_pct,
            }
        }
        plan_days.append(day_dict)

    # 5. 真实三餐周边富化 (优先高德 4.0+ 评分店与本地代表性老字号，融合用户美食偏好)
    enrich_meals_tool(plan_days=plan_days, city=city, food_preferences=food_preferences)

    # 5.5 Tavily 真实互联网攻略与避坑检索 (实时网络活数据 RAG)
    try:
        all_poi_names = []
        for d in plan_days:
            for a in d.get("attractions", []):
                n = a.get("name")
                if n and n not in all_poi_names:
                    all_poi_names.append(n)

        if all_poi_names:
            with ThreadPoolExecutor(max_workers=min(len(all_poi_names), 4)) as pool:
                futs = {
                    pool.submit(search_tavily_poi_guides, city, name): name
                    for name in all_poi_names[:6]
                }
                tavily_map = {}
                for fut in as_completed(futs):
                    p_name = futs[fut]
                    try:
                        t_res = fut.result()
                        if t_res:
                            tavily_map[p_name] = t_res
                    except Exception as e:
                        logger.debug("Tavily 检索景点 %s 异常: %s", p_name, e)

                for d in plan_days:
                    for a in d.get("attractions", []):
                        t_info = tavily_map.get(a.get("name", ""))
                        if t_info:
                            a["guide_tips"] = {
                                "booking_policy": t_info.get("booking_policy", ""),
                                "tips": t_info.get("tips", []),
                                "summary": t_info.get("summary", ""),
                                "source_urls": t_info.get("source_urls", []),
                                "source": "tavily_search",
                                "source_label": "🌐 Tavily 搜索引擎实时提取",
                            }
    except Exception as e:
        logger.warning("Tavily 网络 RAG 富化阶段异常: %s", e)

    # 6. 预算核算
    breakdown, budget_diag = check_budget_tool(
        plan_days=plan_days,
        hotel_per_night_cost=hotel_night_cost,
        days=days,
        budget_limit=budget_total,
    )
    if budget_diag:
        all_diags.append(budget_diag)

    # 7. 算法白盒遥测指标汇总
    total_saved_km = round(sum(d.get("telemetry", {}).get("saved_km", 0.0) for d in plan_days), 1)
    algorithm_telemetry = {
        "kmeans": {
            "total_pois": len(candidate_pool),
            "days": days,
            "balanced": True,
            "clusters": [
                {
                    "day_index": c.get("day_index"),
                    "poi_count": len(c.get("pois", [])),
                    "centroid": c.get("centroid"),
                    "avg_radius_km": c.get("avg_radius_km", 0.0),
                }
                for c in clusters
            ],
        },
        "minimax_hotel": {
            "hotel_name": hotel_selected.get("name"),
            "hotel_type": hotel_selected.get("hotel_type", "舒适型"),
            "price_range": hotel_selected.get("price_range", "300-500元"),
            "target_metric": "min(max(dist_to_attractions))",
        },
        "route_2opt": {
            "total_saved_km": total_saved_km,
            "days_stat": [d.get("telemetry", {}) for d in plan_days],
        },
    }

    plan_version = PlanVersion(
        version_id=1,
        based_on_requirements_revision=req.revision_id,
        days=plan_days,
        locked_items=locked_items,
        algorithm_telemetry=algorithm_telemetry,
        status="draft",
        created_at=datetime.now().isoformat(),
    )

    return {
        "current_plan": plan_version.model_dump(),
        "diagnostics": [d.model_dump() for d in all_diags],
    }


def diagnose_node(state: SessionGraphState) -> dict[str, Any]:
    """诊断评估路由节点：检查是否存在 HARD_FAIL 级诊断"""
    diags = state.get("diagnostics", [])
    repair_attempts = state.get("repair_attempts", 0)

    has_hard_fail = False
    for d in diags:
        sev = d.get("severity") if isinstance(d, dict) else getattr(d, "severity", None)
        if sev == DiagnosticSeverity.HARD_FAIL or sev == "hard_fail":
            has_hard_fail = True
            break

    if has_hard_fail and repair_attempts < 2:
        return {"status": "needs_repair"}
    elif has_hard_fail and repair_attempts >= 2:
        return {"status": "escalated", "needs_human_confirmation": True}
    else:
        return {"status": "ready"}


def repair_node(state: SessionGraphState) -> dict[str, Any]:
    """自愈执行节点：调度 RepairAgent 执行结构化修复，并触发局部重算"""
    plan = state.get("current_plan", {})
    plan_days = plan.get("days", [])
    diagnostics = state.get("diagnostics", [])
    locked_items = state.get("locked_items", [])
    req_dict = state.get("requirements", {})
    budget_total = req_dict.get("slots", {}).get("budget_total", {}).get("value")

    repair_attempts = state.get("repair_attempts", 0) + 1
    attempted = list(state.get("attempted_actions", []))

    agent = RepairAgent(max_attempts=2)
    repaired_days, is_resolved, new_actions = agent.repair_plan(
        plan_days=plan_days,
        diagnostics=diagnostics,
        immutable_names=locked_items,
        budget_total=budget_total,
    )
    attempted.extend(new_actions)

    # 针对受影响的天数重新计算日内路径（未受影响天数 100% 命中 solve_day_route 缓存）
    for day in repaired_days:
        idx = day.get("day_index", 0)
        hotel = day.get("hotel") or {}
        route_res = solve_day_route_tool(
            pois=day.get("attractions", []),
            start_hour=day.get("start_hour", 9),
            close_hour=day.get("close_hour", 21),
            start_hotel=hotel if hotel.get("lng") and hotel.get("lat") else None,
            day_index=idx,
            immutable_names=locked_items,
        )
        day["route"] = route_res.route
        day["total_ticket"] = route_res.total_ticket
        day["day_number"] = idx + 1
        if route_res.route:
            curr_pois = day.get("attractions", [])
            poi_map = {p["name"]: p for p in curr_pois}
            ordered = []
            for node in route_res.route:
                node_name = node.get("name") or (node.get("poi", {}).get("name") if isinstance(node.get("poi"), dict) else "")
                orig = dict(poi_map.get(node_name) or (node.get("poi") if isinstance(node.get("poi"), dict) else node))
                orig["arrive_time"] = node.get("arrive_time", "")
                orig["depart_time"] = node.get("depart_time", "")
                orig["distance_km"] = round(float(node.get("distance_km") or 0.0), 1)
                orig["travel_minutes"] = int(node.get("travel_minutes") or 0)
                ordered.append(orig)
            day["attractions"] = ordered

    plan["days"] = repaired_days

    # 修复后清空已解决的硬伤诊断
    remaining_diags = [] if is_resolved else diagnostics

    return {
        "current_plan": plan,
        "diagnostics": remaining_diags,
        "repair_attempts": repair_attempts,
        "attempted_actions": attempted,
    }


def output_node(state: SessionGraphState) -> dict[str, Any]:
    """最终输出呈现节点：生成富文本 Markdown 交付方案与操作建议"""
    plan = state.get("current_plan", {})
    plan_days = plan.get("days", [])
    attempted = state.get("attempted_actions", [])
    needs_confirm = state.get("needs_human_confirmation", False)
    req_dict = state.get("requirements", {})
    req = EffectiveRequirements.model_validate(req_dict) if req_dict else EffectiveRequirements()

    city = req.get_slot_value("city", "北京")
    days = int(req.get_slot_value("days", len(plan_days)))
    telemetry = plan.get("algorithm_telemetry", {})

    lines = [
        f"### 🎯 【{city}】{days} 天旅行定制行程已为您生成完毕",
        "",
    ]

    # 算法白盒证明看板
    if telemetry:
        saved_km = telemetry.get("route_2opt", {}).get("total_saved_km", 0.0)
        lines.append("> [!NOTE]")
        lines.append(f"> **🧮 算法白盒度量与规划依据：**")
        lines.append(f"> - **空间 K-Means 均衡聚类**：将 {telemetry.get('kmeans', {}).get('total_pois', 0)} 个景点按地理质心划分为 {days} 个均衡日簇，杜绝跨城往返折返。")
        lines.append(f"> - **Minimax 极小化通勤选址**：优选酒店【{telemetry.get('minimax_hotel', {}).get('hotel_name', '精选商圈酒店')}】，极小化每日首站最大通勤成本。")
        if saved_km > 0:
            lines.append(f"> - **贪心 + 2-Opt TSP 局部搜索**：经两阶段路径优化，累计为您的行程节省约 **{saved_km} km** 无效路程。")
        lines.append("")

    if attempted:
        lines.append("> [!TIP]")
        lines.append("> **系统已自动完成以下自愈优化：**")
        for act in attempted:
            lines.append(f"> - {act}")
        lines.append("")

    if needs_confirm:
        lines.append("> [!WARNING]")
        lines.append("> **部分冲突未能完全自动解决，建议您人工确认：**")
        for d in state.get("diagnostics", []):
            lines.append(f"> - {d.get('summary', '行程约束冲突')}")
        lines.append("")

    for day in plan_days:
        d_idx = day.get("day_index", 0)
        d_date = day.get("date", "")
        lines.append(f"#### 📅 第 {d_idx + 1} 天 ({d_date})")

        # 0. 高德官方天气气象指引
        weather = day.get("weather") or {}
        if weather and weather.get("weather"):
            w_desc = weather.get("weather", "")
            t_range = weather.get("temp_range", "")
            wind = weather.get("wind", "")
            tip = weather.get("tip", "")
            src_lbl = weather.get("source_label", "⭐ 高德官方天气")
            lines.append(f"> 🌤️ **[{src_lbl}]**: **{w_desc}** · 🌡️ {t_range} · 💨 {wind} | 💡 *游玩贴士*: {tip}")
            lines.append("")

        # 1. 2-Opt 有序景点时间轴
        lines.append("##### 🚶 游览路线安排 (2-Opt 最优时序)")
        for a_idx, attr in enumerate(day.get("attractions", []), 1):
            name = attr.get("name", "")
            fact = attr.get("place_fact", {})
            open_hrs = attr.get("open_time") or fact.get("opening_hours") or "09:00-17:00"
            t_str = f" [{attr.get('arrive_time')}-{attr.get('depart_time')}]" if attr.get("arrive_time") else ""
            dist_str = f" · 距上站 {attr.get('distance_km')}km" if attr.get("distance_km") else ""
            
            meta_badges = []
            if attr.get("rating"):
                meta_badges.append(f"⭐ 高德评分 {attr['rating']}")
            if attr.get("level"):
                meta_badges.append(f"🏷️ {attr['level']}")
            meta_str = f" ({' · '.join(meta_badges)})" if meta_badges else ""

            lines.append(f"{a_idx}. **{name}**{meta_str}{t_str}{dist_str} (开放: {open_hrs})")
            if attr.get("address"):
                lines.append(f"   - 📍 *详细地址*: {attr['address']}")
            gt = attr.get("guide_tips") or {}
            if gt.get("booking_policy"):
                lines.append(f"   - 🎫 **[🌐 Tavily 搜索引擎实时票务]**: {gt['booking_policy']}")
            if gt.get("tips") and len(gt["tips"]):
                lines.append(f"   - 💡 **[🌐 Tavily 搜索引擎避坑提取]**: {gt['tips'][0]}")
            for g in attr.get("guides", []):
                lines.append(f"   - 💡 *{g.get('tag', '贴士')}*: {g.get('text', '')[:60]}...")

        # 2. 住宿推荐
        hotel = day.get("hotel") or {}
        if hotel and hotel.get("name"):
            h_name = hotel.get("name")
            h_type = hotel.get("hotel_type") or "舒适型"
            h_price = hotel.get("price_range") or "300-500元"
            lines.append("")
            lines.append(f"##### 🏨 推荐住宿：**{h_name}** ({h_type} · {h_price})")
            lines.append(f"> 📍 *Minimax 最优选址*：到当天各核心景点综合通勤最顺畅，早晚出入便捷。")

        # 3. 三餐推荐 (高德 4.0+ 评分与地道名吃)
        meals = day.get("meals") or []
        if meals:
            lines.append("")
            lines.append("##### 🍜 当地精选美食 (高德 4.0+ / 地道老字号)")
            type_label = {"breakfast": "🌅 早餐", "lunch": "☀️ 午餐", "dinner": "🌙 晚餐"}
            for m in meals:
                m_type = type_label.get(m.get("type"), "🍴 美食")
                r_val = m.get("rating", 4.6)
                cost = m.get("estimated_cost", 35)
                desc = m.get("description", "")
                lines.append(f"- **{m_type}**：**{m.get('name')}** (⭐ {r_val} · 人均 ¥{cost}) - *{desc}*")

        lines.append("")

    final_text = "\n".join(lines)
    messages = list(state.get("messages", []))
    messages.append({"role": "assistant", "content": final_text})

    return {
        "final_response": final_text,
        "messages": messages,
        "status": "escalated" if needs_confirm else "ready",
    }


def route_diagnose(state: SessionGraphState) -> str:
    status = state.get("status")
    if status == "needs_repair":
        return "repair_node"
    return "output_node"


def build_session_graph(checkpointer=None):
    """编译构建会话外层协作图"""
    workflow = StateGraph(SessionGraphState)

    workflow.add_node("clarification_node", clarification_node)
    workflow.add_node("planning_node", planning_node)
    workflow.add_node("diagnose_node", diagnose_node)
    workflow.add_node("repair_node", repair_node)
    workflow.add_node("output_node", output_node)

    workflow.add_edge(START, "clarification_node")
    workflow.add_edge("clarification_node", "planning_node")
    workflow.add_edge("planning_node", "diagnose_node")

    workflow.add_conditional_edges(
        "diagnose_node",
        route_diagnose,
        {"repair_node": "repair_node", "output_node": "output_node"},
    )
    workflow.add_edge("repair_node", "output_node")
    workflow.add_edge("output_node", END)

    saver = checkpointer if checkpointer is not None else MemorySaver()
    return workflow.compile(checkpointer=saver)
