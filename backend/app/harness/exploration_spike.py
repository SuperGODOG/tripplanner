"""Pi 风格自主旅行与地理探索 Harness 最小可运行原型 (Minimal Exploration Spike)

遵循 harness-deep-diver 单文件原型规范 (200行高内聚闭环):
1. 单主循环 (Pi-Style Single Async Loop): 纯异步生成器驱动；
2. 动态地图动作协议 (Map Action Protocol): 发射 FOCUS_VIEWPORT / DRAW_ROUTE / HIGHLIGHT_POI；
3. 多维自适应记忆矩阵 (Multi-Tier Memory): 瞬时槽位 + 长期画像 + 历史足迹库 (跨年防重)；
4. 集合论数据互斥硬核校验 (Mathematical Disjointness Check): 运行时断言跨天零重复。

运行方式:
  PYTHONPATH=backend .venv/bin/python backend/app/harness/exploration_spike.py
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import math
import time
from typing import Any, AsyncGenerator, Callable, Coroutine


# ══════════════════════════════════════════════════════════════════════════════
# 1. 强类型事件体系与动态地图交互协议 (Typed Events & Map Action Protocol)
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class SpikeEvent:
    event_type: str
    payload: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


@dataclass
class MapActionEvent(SpikeEvent):
    """动态地图视口与交互图层指令"""
    def __init__(self, action: str, data: dict[str, Any]):
        super().__init__(
            event_type="map_action",
            payload={"action": action, "data": data}
        )


# ══════════════════════════════════════════════════════════════════════════════
# 2. 多维记忆中枢：历史足迹与画像管理 (Multi-Tier Memory Matrix)
# ══════════════════════════════════════════════════════════════════════════════

class FootprintMemory:
    """历史足迹库：跨年/跨次旅行去重防线"""
    def __init__(self, user_id: str):
        self.user_id = user_id
        # 模拟该用户过去已经深度游览过的北京景点
        self.visited_pois: set[str] = {"天安门广场", "八达岭长城", "南锣鼓巷"}

    def is_visited(self, poi_name: str) -> bool:
        return poi_name in self.visited_pois

    def record_trip(self, pois: list[str]) -> None:
        self.visited_pois.update(pois)


# ══════════════════════════════════════════════════════════════════════════════
# 3. 运筹算法与探索工具注册中心 (Tool Registry)
# ══════════════════════════════════════════════════════════════════════════════

def _haversine_km(lng1: float, lat1: float, lng2: float, lat2: float) -> float:
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = math.sin(dlat / 2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlng / 2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


class SpikeToolRegistry:
    def __init__(self):
        self._tools: dict[str, Callable] = {}

    def register(self, name: str):
        def decorator(fn: Callable):
            self._tools[name] = fn
            return fn
        return decorator

    async def call(self, name: str, **kwargs: Any) -> Any:
        fn = self._tools[name]
        return await fn(**kwargs) if asyncio.iscoroutinefunction(fn) else fn(**kwargs)


tools = SpikeToolRegistry()


@tools.register("cluster_kmeans_mutex")
def _tool_kmeans(pois: list[dict[str, Any]], days: int) -> list[dict[str, Any]]:
    """K-Means++ 空间互斥分天聚簇（数学证明：C_i ∩ C_j = ∅）"""
    if not pois or days <= 0:
        return []
    k = min(days, max(1, len(pois) // 2))
    # 初始化质心
    centers = [{"lng": pois[0]["lng"], "lat": pois[0]["lat"]}]
    for _ in range(1, k):
        farthest = max(pois, key=lambda p: min(_haversine_km(p["lng"], p["lat"], c["lng"], c["lat"]) for c in centers))
        centers.append({"lng": farthest["lng"], "lat": farthest["lat"]})

    # 单值映射分配函数 f: POI -> ClusterIndex
    assign = [0] * len(pois)
    for _ in range(10):
        for i, p in enumerate(pois):
            assign[i] = min(range(k), key=lambda c: _haversine_km(p["lng"], p["lat"], centers[c]["lng"], centers[c]["lat"]))
        for c in range(k):
            members = [pois[i] for i in range(len(pois)) if assign[i] == c]
            if members:
                centers[c]["lng"] = sum(m["lng"] for m in members) / len(members)
                centers[c]["lat"] = sum(m["lat"] for m in members) / len(members)

    clusters = []
    for c in range(k):
        members = [pois[i] for i in range(len(pois)) if assign[i] == c]
        clusters.append({"day_index": c, "pois": members, "center": centers[c]})
    return clusters


@tools.register("solve_2opt")
def _tool_2opt(pois: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """2-Opt 启发式路径优化"""
    if len(pois) <= 2:
        return pois
    route = list(pois)
    for _ in range(5):
        for i in range(len(route) - 1):
            for j in range(i + 2, len(route)):
                d_orig = _haversine_km(route[i]["lng"], route[i]["lat"], route[i+1]["lng"], route[i+1]["lat"])
                d_new = _haversine_km(route[i]["lng"], route[i]["lat"], route[j]["lng"], route[j]["lat"])
                if d_new < d_orig:
                    route[i+1:j+1] = reversed(route[i+1:j+1])
    return route


@tools.register("discover_nearby_gems")
def _tool_discover_gems(center_lng: float, center_lat: float, radius_km: float = 3.0) -> list[dict[str, Any]]:
    """周边小众宝藏探索（模拟动态空间雷达发现）"""
    gems_db = [
        {"name": "东交民巷欧式建筑群", "lng": 116.415, "lat": 39.904, "category": "小众历史"},
        {"name": "人艺戏剧博物馆", "lng": 116.418, "lat": 39.919, "category": "艺术打卡"},
        {"name": "三联韬奋24小时书店", "lng": 116.419, "lat": 39.925, "category": "慢节奏文化"},
    ]
    return [g for g in gems_db if _haversine_km(center_lng, center_lat, g["lng"], g["lat"]) <= radius_km]


# ══════════════════════════════════════════════════════════════════════════════
# 4. Pi 风格自主旅行探索 Harness 核心主循环 (Exploration Harness Loop)
# ══════════════════════════════════════════════════════════════════════════════

class PiTravelExplorationHarness:
    def __init__(self, footprint_memory: FootprintMemory):
        self.memory = footprint_memory

    async def run(self, city: str, days: int) -> AsyncGenerator[SpikeEvent, None]:
        yield SpikeEvent("thinking", {"detail": f"⚡ Pi Harness 已挂载探索任务 [{city} · {days}天]..."})

        # 1. 模拟城市原始候选池 (含部分曾游览过的景点)
        raw_pool = [
            {"name": "故宫博物院", "lng": 116.397, "lat": 39.918},
            {"name": "天坛公园", "lng": 116.411, "lat": 39.883},
            {"name": "颐和园", "lng": 116.273, "lat": 39.999},
            {"name": "圆明园", "lng": 116.299, "lat": 40.008},
            {"name": "景山公园", "lng": 116.398, "lat": 39.928},
            {"name": "北海公园", "lng": 116.388, "lat": 39.926},
            {"name": "八达岭长城", "lng": 115.986, "lat": 40.359},  # 用户历史已打卡过
            {"name": "天安门广场", "lng": 116.397, "lat": 39.903},  # 用户历史已打卡过
        ]

        # 2. 结合 Tier-3 历史足迹库过滤（防止向老游客反复推荐已去过的景点）
        filtered_candidates = [p for p in raw_pool if not self.memory.is_visited(p["name"])]
        filtered_names = [p["name"] for p in filtered_candidates]
        yield SpikeEvent("thinking", {"detail": f"足迹库已过滤已游览景点，剩余 {len(filtered_candidates)} 个候选"})

        # 发射地图动作：视口飞越至城市中心
        yield MapActionEvent("FOCUS_VIEWPORT", {"city": city, "center": [116.407, 39.904], "zoom": 12})

        # 3. K-Means++ 空间互斥划分 (数学级零重复)
        clusters = await tools.call("cluster_kmeans_mutex", pois=filtered_candidates, days=days)

        final_days = []
        all_allocated_pois: list[str] = []

        for c in clusters:
            d_idx = c["day_index"]
            day_pois = c["pois"]
            optimized_route = await tools.call("solve_2opt", pois=day_pois)

            # 发射地图动作：为每一天绘制彩色路径折线
            polyline = [[p["lng"], p["lat"]] for p in optimized_route]
            yield MapActionEvent("DRAW_ROUTE", {"day_index": d_idx + 1, "polyline": polyline})

            final_days.append({
                "day_number": d_idx + 1,
                "pois": [p["name"] for p in optimized_route],
                "coordinates": polyline,
            })
            all_allocated_pois.extend([p["name"] for p in optimized_route])

        # 4. 探索型拓展：为第 1 天核心景点探测周边 3km 隐藏宝藏
        first_poi = clusters[0]["pois"][0]
        gems = await tools.call("discover_nearby_gems", center_lng=first_poi["lng"], center_lat=first_poi["lat"], radius_km=3.0)
        for gem in gems:
            yield MapActionEvent("HIGHLIGHT_POI", {"name": gem["name"], "category": gem["category"], "coords": [gem["lng"], gem["lat"]]})

        # 5. 产出最终行程版本
        yield SpikeEvent("plan_version", {"city": city, "days": final_days, "gems_discovered": [g["name"] for g in gems]})
        yield SpikeEvent("done", {"success": True, "total_pois": len(all_allocated_pois)})


# ══════════════════════════════════════════════════════════════════════════════
# 5. 独立单步调试与数学断言入口 (Self-Verification Entrypoint)
# ══════════════════════════════════════════════════════════════════════════════

async def main():
    print("=" * 70)
    print("🚀 启动 Pi-Style Sovereign Travel Exploration Harness Spike 原型")
    print("=" * 70)

    memory = FootprintMemory(user_id="user_explorer_007")
    print(f"[*] 用户的历史已游览足迹库: {memory.visited_pois}")

    harness = PiTravelExplorationHarness(footprint_memory=memory)
    events = []

    async for ev in harness.run(city="北京", days=2):
        events.append(ev)
        if ev.event_type == "map_action":
            print(f"  🗺️  [MapAction] {ev.payload['action']} -> {ev.payload['data']}")
        elif ev.event_type == "thinking":
            print(f"  💭 [Thinking] {ev.payload['detail']}")

    plan_event = next(e for e in events if e.event_type == "plan_version")
    plan = plan_event.payload
    print("\n" + "─" * 70)
    print("📋 【规划交付与数学划分验证】")
    for d in plan["days"]:
        print(f"  📅 第 {d['day_number']} 天景点 ({len(d['pois'])} 处): {d['pois']}")
    print(f"  💎 周边探索发现小众机位: {plan['gems_discovered']}")

    # ── 核心数学断言：严格验证 C_0 ∩ C_1 = ∅ ──
    day1_set = set(plan["days"][0]["pois"])
    day2_set = set(plan["days"][1]["pois"])
    intersection = day1_set.intersection(day2_set)

    print("\n🔍 【集合论互斥性形式化验证】")
    print(f"  - Day 1 景点集合: {day1_set}")
    print(f"  - Day 2 景点集合: {day2_set}")
    print(f"  - 交集 (Day 1 ∩ Day 2): {intersection}")

    assert len(intersection) == 0, f"❌ 严重数学违背：检测到跨天重复景点 {intersection}"
    print("  ✅ [数学定理验证通过] C_1 ∩ C_2 = ∅ (绝对零跨天重复！)")

    # ── 核心足迹断言：严格验证历史打卡点已被 100% 隔离 ──
    all_recommended = day1_set.union(day2_set)
    visited_leak = all_recommended.intersection(memory.visited_pois)
    assert len(visited_leak) == 0, f"❌ 历史足迹过滤失效：重复推荐了已游览景点 {visited_leak}"
    print(f"  ✅ [历史记忆验证通过] 历史打卡景点 {memory.visited_pois} 未被二次重复推荐！")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
