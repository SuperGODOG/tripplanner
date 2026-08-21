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

DETOUR_FACTOR = 1.4       # 城市内道路绕路系数（直线距离 → 通行距离）
AVG_SPEED_KPH = 30.0      # 市内通行平均速度 km/h
DEFAULT_VISIT_MIN = 90    # 默认游玩时长（分钟）
DEFAULT_OPEN_HOUR = 9     # 默认开始时间（日窗口左界）
DEFAULT_CLOSE_HOUR = 20   # 默认结束时间（日窗口右界）


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
                           start_hour: int, close_hour: int) -> list[dict] | None:
    """时间窗可行性检查: 贪心顺序上逐点推进时间，超窗返回 None（调用方换插入位）。"""
    cur_min = start_hour * 60
    plan: list[dict] = []
    prev = None
    for idx in order:
        p = pois[idx]
        travel = 0
        if prev is not None:
            travel = _travel_minutes(prev, p)
            cur_min += travel
        visit = int(p.get("visit_minutes", DEFAULT_VISIT_MIN))
        if cur_min + visit > close_hour * 60:
            return None  # 时间窗硬约束不满足
        plan.append({"poi": p, "arrive_min": cur_min, "depart_min": cur_min + visit,
                     "travel_min_from_prev": travel})
        cur_min += visit
        prev = p
    return plan


def solve_daily_route(pois: list[dict], start_hour: int = DEFAULT_OPEN_HOUR,
                      close_hour: int = DEFAULT_CLOSE_HOUR,
                      start: dict | None = None) -> list[dict]:
    """求解当天最优访问路径。

    输入: pois 为当天 POI dict 列表（含 lng/lat，可选 visit_minutes/price）
    输出: 有序 plan 列表:
      [{"poi": poi_dict, "arrive_min": int(分钟, 当天起点偏移), "depart_min": int,
        "travel_min_from_prev": int}, ...]
    时间窗硬约束不满足时（如全部 POI 游玩总时长超日窗口）:
      - 优先 2-opt 后仍超窗 → 尝试按游玩时长降序剪枝（保留门票更贵/评分更高的？）
      - 剪枝后仍超窗 → 返回空列表（调用方走软伤降级，不阻断）
    """
    if not pois:
        return []
    order = _greedy_nearest(pois, start)
    order = _two_opt(pois, order)

    plan = _schedule_with_windows(pois, order, start_hour, close_hour)
    if plan is not None:
        return plan

    # 时间窗超限: 剪枝最少量的点（游玩时长最大的先剪），重排重检
    trimmed = list(order)
    while len(trimmed) > 1:
        # 剪掉当前顺序中游玩时长最长的点
        longest = max(trimmed, key=lambda i: pois[i].get("visit_minutes", DEFAULT_VISIT_MIN))
        trimmed.remove(longest)
        new_order = _two_opt(pois, trimmed)
        plan = _schedule_with_windows(pois, new_order, start_hour, close_hour)
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
