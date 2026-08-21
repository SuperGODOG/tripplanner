"""多日景点聚簇分配 — 手写 K-Means（无 sklearn 依赖）

v3 分日并发的数据层基础:
- 把市区 POI 按地理位置聚成 days 个互斥簇，每个 POI 只属于一天
- **互斥在数据层保证**（LLM 不再做全局去重推理，幻觉率根源消除）
- 簇内顺序/时间窗由 route_solver 处理（贪心 + 2-opt）

边界处理:
- 远郊 POI（excursion）单独成"远郊日"簇（该天可只有 1 个点，校验豁免）
- 市区 POI 不足 days*2 时簇数收缩，剩余天生成"自由活动日"（无景点，leisure_day）
- k-means++ 初始化（最远点采样）避免空簇/局部最优
"""
import math
from typing import Any

MAX_ITER = 20          # K-Means 迭代上限（本地小规模，足够收敛）
MIN_PER_DAY = 2        # 每天最少景点数（自由日/远郊日豁免）
LEISURE = "leisure"    # 自由活动日标记
EXCURSION = "excursion"  # 远郊一日游标记


def _haversine_km(lng1: float, lat1: float, lng2: float, lat2: float) -> float:
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlng / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _kmeans_plusplus(pois: list[dict], k: int) -> list[dict]:
    """k-means++ 初始化: 首个质心取全量质心，后续取离已选质心最远的点。

    返回恰好 k 个质心（含全量质心种子）——注意不能用 centers[1:]，
    循环只跑 k-1 次会导致少一个质心（k=2 时 IndexError，实测踩过）。
    """
    n = len(pois)
    clng = sum(p["lng"] for p in pois) / n
    clat = sum(p["lat"] for p in pois) / n
    centers = [{"lng": clng, "lat": clat, "name": "_center"}]
    while len(centers) < k:
        farthest, best_d = None, -1.0
        for p in pois:
            d = min(_haversine_km(p["lng"], p["lat"], c["lng"], c["lat"])
                    for c in centers)
            if d > best_d:
                best_d, farthest = d, p
        if farthest is None:
            break
        centers.append({"lng": farthest["lng"], "lat": farthest["lat"],
                        "name": farthest["name"]})
    return centers


def cluster_pois_by_day(pois: list[dict], days: int,
                        excursion_pois: list[dict] | None = None) -> list[dict]:
    """把 POI 分到 days 个互斥簇。

    返回 list[dict]，每个元素:
      {"day_index": i, "pois": [PoiCandidate.model_dump(), ...],
       "kind": "normal" | "excursion" | "leisure"}
    簇的 day_index 连续从 0 开始（市区簇优先，excursion 占最后一天，leisure 补位）。
    """
    normal = [p for p in pois if p.get("lng") and p.get("lat")]
    excursions = [p for p in (excursion_pois or []) if p.get("lng") and p.get("lat")]

    clusters: list[dict] = []

    # ── 1. 远郊日（每簇一个远郊 POI，允许单独一天）──
    # 多个远郊点合并成簇（同方向一日游语义），最多占 1 天；超出部分并入最后一簇
    if excursions:
        merged_ex = [{"day_index": None, "pois": excursions, "kind": EXCURSION}]
        clusters.extend(merged_ex)

    # ── 2. 市区聚类: k = min(days - 远郊日数, len//MIN_PER_DAY) ──
    used_days = len(clusters)
    remain_days = max(1, days - used_days)
    k = min(remain_days, len(normal) // MIN_PER_DAY) if normal else 0

    if k >= 1:
        centers = _kmeans_plusplus(normal, k)
        assign = [0] * len(normal)
        for _ in range(MAX_ITER):
            # 分配
            changed = False
            for i, p in enumerate(normal):
                best = min(range(k), key=lambda c: _haversine_km(
                    p["lng"], p["lat"], centers[c]["lng"], centers[c]["lat"]))
                if assign[i] != best:
                    assign[i], changed = best, True
            # 更新质心
            for c in range(k):
                members = [normal[i] for i in range(len(normal)) if assign[i] == c]
                if members:
                    centers[c]["lng"] = sum(m["lng"] for m in members) / len(members)
                    centers[c]["lat"] = sum(m["lat"] for m in members) / len(members)
            if not changed:
                break

        for c in range(k):
            members = [normal[i] for i in range(len(normal)) if assign[i] == c]
            if members:
                clusters.append({"day_index": None, "pois": members, "kind": "normal"})

    # ── 3. 自由日补位: 簇数 < days 时，剩余天生成 leisure 簇 ──
    while len(clusters) < days:
        clusters.append({"day_index": None, "pois": [], "kind": LEISURE})

    # ── 4. 分配 day_index（市区簇优先占前段，excursion 占后，leisure 填空位）──
    # 排序: normal 簇按质心经度（近似行程方向），excursion 在最后，leisure 按空位
    ordered = []
    normal_clusters = [c for c in clusters if c["kind"] == "normal"]
    normal_clusters.sort(key=lambda c: sum(p["lng"] for p in c["pois"]) / len(c["pois"]))
    exc_clusters = [c for c in clusters if c["kind"] == EXCURSION]
    leisure_clusters = [c for c in clusters if c["kind"] == LEISURE]

    ordered = normal_clusters + exc_clusters + leisure_clusters
    for i, c in enumerate(ordered):
        c["day_index"] = i
    return ordered


def cluster_to_payload(cluster: dict) -> dict:
    """簇 → Send payload 的字段（只带需要的，避免大对象进 checkpoint）。"""
    return {
        "day_index": cluster["day_index"],
        "kind": cluster["kind"],
        "pois": [{"name": p["name"], "lng": p["lng"], "lat": p["lat"],
                  "district": p.get("district", ""), "category": p.get("category", ""),
                  "price": p.get("price"), "id": p.get("id", "")}
                 for p in cluster["pois"]],
    }
