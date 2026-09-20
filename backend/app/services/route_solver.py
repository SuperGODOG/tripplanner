"""日内路径求解 — 贪心最近邻 + 2-opt + 时间窗硬检查（无 OR-Tools 依赖）

v3 分日链路的核心: 聚簇确定"每天去哪"，本模块确定"每天怎么走"。
- 距离矩阵: Haversine 直线 × 绕路系数（本地算，零 API 调用）
- 贪心最近邻: 从起点出发每次选最近未访问点，O(n²)
- 2-opt: 交换路径段消除交叉，对 ≤10 节点逼近最优
- 时间窗: 到达 + 游玩时长 ≤ 日结束时间，硬性检查（不满足则换插入位）
- 设计原则: 本地计算优于 LLM；先启发式后精确求解（接口预留 OR-Tools 替换位）
"""
import math
from typing import Any

from ..models.diagnostics import (
    RouteSolverResult,
    DiagnosticSignal,
    ErrorCode,
    DiagnosticSeverity,
)

DETOUR_FACTOR = 1.4       # 城市内道路绕路系数（直线距离 → 通行距离）
AVG_SPEED_KPH = 30.0      # 市内通行平均速度 km/h
DEFAULT_VISIT_MIN = 75    # 默认游玩时长（分钟）
DEFAULT_OPEN_HOUR = 9     # 默认开始时间（日窗口左界）
DEFAULT_CLOSE_HOUR = 21   # 默认结束时间（日窗口右界，09:00-21:00 全景游览）


def estimate_visit_minutes(poi: dict) -> int:
    """根据 POI 名称与属性分级估算游玩时长"""
    explicit = poi.get("visit_minutes")
    if explicit and isinstance(explicit, (int, float)) and 30 <= explicit <= 300:
        return int(explicit)

    name = poi.get("name", "")
    cat = poi.get("category", "")
    level = str(poi.get("level") or "")

    # Grade A: 大山名胜、巨型 5A 景区 (150-180m)
    if any(k in name for k in ("金顶", "万佛顶", "乐山大佛", "兵马俑", "故宫", "颐和园", "天坛", "泰山", "华山", "黄山")):
        return 180
    if "AAAAA" in level or "5A" in level or any(k in name for k in ("国家森林公园", "自然保护区", "国家公园")):
        return 150

    # Grade C: 街区、古镇老街、观景台、广场、美食街 (45-60m)
    if any(k in name for k in ("美食街", "古街", "老街", "街区", "广场", "观景", "码头", "江面", "步道", "城墙", "夜市", "坊")):
        return 60

    # Grade B: 寺庙、博物馆、文化古迹、常规公园 (75-90m)
    if any(k in name for k in ("寺", "宫", "阁", "馆", "堂", "院", "亭", "园", "墓")):
        return 75

    return DEFAULT_VISIT_MIN


def _haversine_km(lng1: float, lat1: float, lng2: float, lat2: float) -> float:
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlng / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _travel_minutes(p1: dict, p2: dict) -> int:
    """两点间通行时间（分钟）: 直线距离 × 绕路系数 / 市内速度。"""
    km = _haversine_km(p1["lng"], p1["lat"], p2["lng"], p2["lat"]) * DETOUR_FACTOR
    return max(1, int(km / AVG_SPEED_KPH * 60))


def _greedy_nearest(pois: list[dict], start: dict | None) -> list[int]:
    """贪心最近邻: 返回访问顺序（pois 下标列表），起点可指定（酒店/质心）。"""
    n = len(pois)
    if n <= 1:
        return list(range(n))
    cur = start or {"lng": sum(p["lng"] for p in pois) / n,
                    "lat": sum(p["lat"] for p in pois) / n}
    visited = [False] * n
    order: list[int] = []
    for _ in range(n):
        best, best_d = -1, float("inf")
        for i in range(n):
            if not visited[i]:
                d = _haversine_km(cur["lng"], cur["lat"], pois[i]["lng"], pois[i]["lat"])
                if d < best_d:
                    best_d, best = d, i
        visited[best] = True
        order.append(best)
        cur = pois[best]
    return order


def _two_opt(pois: list[dict], order: list[int]) -> list[int]:
    """2-opt 优化: 交换路径段消除交叉，直至无改善（≤10 节点几十轮内收敛）。"""
    n = len(order)
    improved = True
    while improved:
        improved = False
        for i in range(n - 1):
            for j in range(i + 2, n):
                a, b, c, d = order[i], order[i + 1], order[j], order[(j + 1) % n]
                old = (_haversine_km(pois[a]["lng"], pois[a]["lat"], pois[b]["lng"], pois[b]["lat"]) +
                       _haversine_km(pois[c]["lng"], pois[c]["lat"], pois[d]["lng"], pois[d]["lat"]))
                new = (_haversine_km(pois[a]["lng"], pois[a]["lat"], pois[c]["lng"], pois[c]["lat"]) +
                       _haversine_km(pois[b]["lng"], pois[b]["lat"], pois[d]["lng"], pois[d]["lat"]))
                if new + 1e-9 < old:
                    order[i + 1:j + 1] = reversed(order[i + 1:j + 1])
                    improved = True
    return order


def _schedule_with_windows(pois: list[dict], order: list[int],
                           start_hour: int, close_hour: int,
                           compress_ratio: float = 1.0) -> list[dict] | None:
    """时间窗可行性检查: 贪心顺序上逐点推进时间，超窗返回 None。支持弹性时长压缩。"""
    cur_min = start_hour * 60
    plan: list[dict] = []
    prev = None
    for idx in order:
        p = pois[idx]
        travel = 0
        if prev is not None:
            travel = _travel_minutes(prev, p)
            cur_min += travel
        base_visit = estimate_visit_minutes(p)
        # 弹性时长压缩：非大山核心名胜允许自适应压缩，最低不少于 45 分钟
        if compress_ratio < 1.0 and base_visit < 150:
            visit = max(45, int(base_visit * compress_ratio))
        else:
            visit = base_visit

        if cur_min + visit > close_hour * 60:
            return None  # 时间窗硬约束不满足
        dist = round(_haversine_km(float(prev["lng"]), float(prev["lat"]), float(p["lng"]), float(p["lat"])), 1) if prev and prev.get("lng") and prev.get("lat") else 0.0
        plan.append({
            "poi": p,
            "arrive_min": cur_min,
            "depart_min": cur_min + visit,
            "travel_min_from_prev": travel,
            "distance_km": dist,
            "arrive_time": _min_to_str(cur_min),
            "depart_time": _min_to_str(cur_min + visit),
        })
        cur_min += visit
        prev = p
    return plan


def solve_daily_route(pois: list[dict], start_hour: int = DEFAULT_OPEN_HOUR,
                      close_hour: int = DEFAULT_CLOSE_HOUR,
                      start: dict | None = None,
                      immutable_names: list[str] | None = None) -> list[dict]:
    """求解当天最优访问路径。

    策略:
    1. 尝试全量 POI 基础时长排期；
    2. 若超窗，优先自适应弹性压缩时长 (compress_ratio = 0.85 -> 0.70)，最大化保全景点丰富度；
    3. 仅在确实无法容纳时，才剪枝非锁定项，且尽量保证保留 3-4 个景点。
    """
    if not pois:
        return []
    order = _greedy_nearest(pois, start)
    order = _two_opt(pois, order)

    # 1. 基础时长尝试
    plan = _schedule_with_windows(pois, order, start_hour, close_hour, compress_ratio=1.0)
    if plan is not None:
        return plan

    # 2. 弹性时长压缩优先（保全景点丰富度，拒绝稀疏空洞）
    for ratio in (0.85, 0.70):
        plan = _schedule_with_windows(pois, order, start_hour, close_hour, compress_ratio=ratio)
        if plan is not None:
            return plan

    # 3. 弹性夜间时间窗优先保全 (至 22:00，保全全部景点游览)
    if close_hour < 22 and (close_hour - start_hour) >= 10:
        plan = _schedule_with_windows(pois, order, start_hour, 22, compress_ratio=0.85)
        if plan is not None:
            return plan

    # 4. 确实超限时，温和剪枝（保护锁定项，保留最多点）
    immutables = set(immutable_names or [])
    trimmed = list(order)
    while len(trimmed) > 1:
        prune_candidates = [i for i in trimmed if pois[i].get("name", "") not in immutables]
        if not prune_candidates:
            break
        # 裁剪耗时最大或非核心的次要点
        longest = max(prune_candidates, key=lambda i: estimate_visit_minutes(pois[i]))
        trimmed.remove(longest)
        new_order = _two_opt(pois, trimmed)
        
        # 尝试标准与微压缩
        for r in (1.0, 0.8):
            plan = _schedule_with_windows(pois, new_order, start_hour, close_hour, compress_ratio=r)
            if plan is not None:
                return plan

    return []


def format_plan(plan: list[dict], base_date: str = "") -> list[dict]:
    """plan 条目 → 行程 JSON 的景点条目（含时间标注，供 day_node 组装）。"""
    out = []
    for i, item in enumerate(plan):
        p = item["poi"]
        travel = item.get("travel_min_from_prev", 0)
        out.append({
            "name": p.get("name", ""),
            "address": p.get("address", ""),
            "category": p.get("category", ""),
            "ticket_price": p.get("price"),
            "visit_duration": p.get("visit_minutes", DEFAULT_VISIT_MIN),
            "arrive_time": _min_to_str(item["arrive_min"]),
            "depart_time": _min_to_str(item["depart_min"]),
            "travel_minutes_from_prev": travel,
            "location": {"longitude": p.get("lng"), "latitude": p.get("lat")},
            "description": "",
        })
    return out


def _min_to_str(m: int) -> str:
    return f"{m // 60:02d}:{m % 60:02d}"


def solve_day_route_with_diagnostics(
    pois: list[dict],
    start_hour: int = DEFAULT_OPEN_HOUR,
    close_hour: int = DEFAULT_CLOSE_HOUR,
    start: dict | None = None,
    day_index: int = 0,
    immutable_names: list[str] | None = None,
) -> RouteSolverResult:
    """带丰富结构化诊断的日内路径求解。

    时间窗满足时:
      返回 success=True, route=有序计划, diagnostics=None
    时间窗超限时:
      计算超额具体分钟数与冲突景点清单，
      标记用户不可变锁定项 (immutable_constraints)，
      生成 DiagnosticSignal(error_code=TIME_WINDOW_EXCEEDED)，
      返回 success=False, route=修剪/保底候选, diagnostics=诊断信号
    """
    if not pois:
        return RouteSolverResult(success=True, route=[], total_min=0, total_ticket=0, exceeds_day=False)

    order = _greedy_nearest(pois, start)
    order = _two_opt(pois, order)

    # 1. 尝试标准排期
    plan = _schedule_with_windows(pois, order, start_hour, close_hour, compress_ratio=1.0)
    total_ticket = sum(int(p.get("price") or 0) for p in pois)

    if plan is not None:
        first_travel = plan[0]["travel_min_from_prev"] if plan else 0
        total_min = (plan[-1]["depart_min"] - plan[0]["arrive_min"] + first_travel) if plan else 0
        return RouteSolverResult(
            success=True,
            route=plan,
            total_min=total_min,
            total_ticket=total_ticket,
            exceeds_day=False,
            diagnostics=None,
        )

    # 2. 尝试弹性时长压缩排期（保全景点，自愈无需剔除）
    for ratio in (0.85, 0.70):
        c_plan = _schedule_with_windows(pois, order, start_hour, close_hour, compress_ratio=ratio)
        if c_plan is not None:
            first_travel = c_plan[0]["travel_min_from_prev"] if c_plan else 0
            total_min = (c_plan[-1]["depart_min"] - c_plan[0]["arrive_min"] + first_travel) if c_plan else 0
            return RouteSolverResult(
                success=True,
                route=c_plan,
                total_min=total_min,
                total_ticket=total_ticket,
                exceeds_day=False,
                diagnostics=None,
            )

    # 3. 尝试弹性夜间窗口 (close_hour 延展至 22:00，配合 0.85 压缩)
    # 当日间时间窗常规宽裕 ((close_hour - start_hour) >= 10) 且景点可在 22:00 前容纳时，
    # 软约束处理为 WARNING，保全 100% 景点丰富度，绝不触发 HARD_FAIL 粗暴删点！
    if close_hour < 22 and (close_hour - start_hour) >= 10:
        e_plan = _schedule_with_windows(pois, order, start_hour, 22, compress_ratio=0.85)
        if e_plan is not None:
            first_travel = e_plan[0]["travel_min_from_prev"] if e_plan else 0
            total_min = (e_plan[-1]["depart_min"] - e_plan[0]["arrive_min"] + first_travel) if e_plan else 0
            immutables = [
                name for name in (immutable_names or [])
                if any(p.get("name") == name for p in pois)
            ]
            warning_diag = DiagnosticSignal(
                error_code=ErrorCode.TIME_WINDOW_EXCEEDED,
                day_index=day_index,
                severity=DiagnosticSeverity.WARNING,
                summary=f"第{day_index + 1}天行程较为充实（预计 {e_plan[-1]['depart_time']} 结束），已弹性优化时间窗",
                details={
                    "exceeded_minutes": max(1, total_min - (close_hour - start_hour) * 60),
                    "available_minutes": (close_hour - start_hour) * 60,
                    "estimated_total_minutes": total_min,
                    "poi_count": len(pois),
                },
                conflicting_items=[],
                immutable_constraints=immutables,
                attempted_actions=["已自动弹性延展夜间时间窗至 22:00，保全全部景点游览"],
                actionable_suggestions=["RELAX_PACE"],
            )
            return RouteSolverResult(
                success=True,
                route=e_plan,
                total_min=total_min,
                total_ticket=total_ticket,
                exceeds_day=False,
                diagnostics=warning_diag,
            )

    # ── 超限诊断计算 ──
    raw_cur = start_hour * 60
    prev = start
    for idx in order:
        p = pois[idx]
        travel = _travel_minutes(prev, p) if prev else 0
        raw_cur += travel
        visit = estimate_visit_minutes(p)
        raw_cur += visit
        prev = p

    raw_total_min = raw_cur - start_hour * 60
    available_min = (close_hour - start_hour) * 60
    exceeded_min = max(1, raw_total_min - available_min)

    immutables = [
        name for name in (immutable_names or [])
        if any(p.get("name") == name for p in pois)
    ]

    diag = DiagnosticSignal(
        error_code=ErrorCode.TIME_WINDOW_EXCEEDED,
        day_index=day_index,
        severity=DiagnosticSeverity.HARD_FAIL,
        summary=f"第{day_index + 1}天总用时预计超过日时间窗 {exceeded_min} 分钟",
        details={
            "exceeded_minutes": exceeded_min,
            "available_minutes": available_min,
            "estimated_total_minutes": raw_total_min,
            "poi_count": len(pois),
        },
        conflicting_items=[p.get("name", "") for p in pois if p.get("name")],
        immutable_constraints=immutables,
        attempted_actions=["2-opt 路线局部逆序调优已尝试，仍超出时间窗"],
        actionable_suggestions=["PRUNE_LOW_PRIORITY_POI", "EXPAND_WINDOW"],
    )

    # 尝试剪枝保留子集路线供参考（严格遵循锁定项约束）
    trimmed_plan = solve_daily_route(pois, start_hour, close_hour, start, immutable_names=immutables)

    return RouteSolverResult(
        success=False,
        route=trimmed_plan,
        total_min=raw_total_min,
        total_ticket=total_ticket,
        exceeds_day=True,
        diagnostics=diag,
    )

