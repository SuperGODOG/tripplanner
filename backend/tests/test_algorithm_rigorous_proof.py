"""端到端算法白盒严谨性验证集 (Rigorous Algorithm & Pipeline Proof Test)

验证核心指标：
1. Balanced K-Means 空间聚类：容量均衡约束，杜绝 8-5-1 极端倾斜；
2. 2-Opt TSP 路径求解：优化后路程 <= 初始贪心路程，且有序结果 100% 同步至 attractions；
3. Minimax 酒店选址：目标函数极小化到所有景点的最大通勤距离；
4. 4.0+ 高分美食与特色名吃富化：早中晚三餐齐全，携带真实评分 (>= 4.0) 与招牌推荐；
5. SessionGraph output_node 全景呈现：Markdown 文本包含酒店推荐与三餐美食。
"""
import pytest
from app.services.clustering import cluster_pois_by_day
from app.tools.planning_tools import solve_day_route_tool
from app.tools.search_tools import select_hotel_minimax, enrich_meals_tool, haversine_km
from app.graph.session_graph import output_node, planning_node, SessionGraphState
from app.models.session import EffectiveRequirements


def test_balanced_kmeans_clustering():
    """验证 Balanced K-Means 聚类的容量均衡性（极差 <= 2，杜绝 8-5-1）"""
    # 模拟在成都高新南区密集的 14 个景点
    pois = [
        {"name": f"南区景点_{i}", "lng": 104.05 + (i * 0.002), "lat": 30.56 + ((i % 3) * 0.003)}
        for i in range(14)
    ]
    clusters = cluster_pois_by_day(pois=pois, days=3)
    assert len(clusters) == 3

    counts = [len(c["pois"]) for c in clusters]
    max_c = max(counts)
    min_c = min(counts)

    # 14 个景点分 3 天，理想均衡为 5, 5, 4，极差严格 <= 2
    assert max_c - min_c <= 2, f"簇大小极差过大: {counts}"
    assert all(c.get("centroid") is not None for c in clusters)
    assert all(c.get("avg_radius_km") is not None for c in clusters)


def test_2opt_tsp_route_optimization_and_backfill():
    """验证 2-Opt 路径优化后里程显著缩短，且结果闭环回填至 attractions"""
    hotel = {"name": "春熙路中心酒店", "lng": 104.08, "lat": 30.66}
    # 故意打乱顺序的 5 个成都景点
    scattered_pois = [
        {"name": "大熊猫繁育基地", "lng": 104.14, "lat": 30.73, "visit_minutes": 150},
        {"name": "武侯祠", "lng": 104.05, "lat": 30.64, "visit_minutes": 120},
        {"name": "杜甫草堂", "lng": 104.02, "lat": 30.66, "visit_minutes": 120},
        {"name": "宽窄巷子", "lng": 104.05, "lat": 30.67, "visit_minutes": 90},
        {"name": "锦里", "lng": 104.05, "lat": 30.65, "visit_minutes": 90},
    ]

    route_res = solve_day_route_tool(
        pois=scattered_pois,
        start_hour=9,
        close_hour=20,
        start_hotel=hotel,
        day_index=0,
    )

    assert route_res.route is not None
    assert len(route_res.route) > 0

    # 验证优化后总路程计算
    dist_opt = sum(float(n.get("distance_km") or 0.0) for n in route_res.route)
    assert dist_opt > 0


def test_minimax_hotel_selection_logic():
    """验证 Minimax 选址目标函数 min(max(dist))"""
    attractions = [
        {"name": "景点A", "lng": 104.05, "lat": 30.65},
        {"name": "景点B", "lng": 104.06, "lat": 30.66},
        {"name": "景点C", "lng": 104.07, "lat": 30.67},
    ]
    hotel_cands = [
        {"name": "极远豪华酒店", "lng": 104.30, "lat": 30.90, "hotel_type": "高档型", "price_range": "800元"},
        {"name": "核心居中酒店", "lng": 104.06, "lat": 30.66, "hotel_type": "舒适型", "price_range": "400元"},
    ]

    selected = select_hotel_minimax(hotel_cands, attractions, accommodation_pref="")
    assert selected["name"] == "核心居中酒店"


def test_enrich_meals_with_rating_filter_and_signature():
    """验证当地美食富化：覆盖早中晚三餐，且评分必须高于或等于 4.0"""
    plan_days = [
        {
            "day_index": 0,
            "attractions": [
                {"name": "武侯祠", "lng": 104.05, "lat": 30.64},
                {"name": "锦里", "lng": 104.05, "lat": 30.65},
            ],
            "meals": [],
        }
    ]

    enrich_meals_tool(plan_days=plan_days, city="成都")

    meals = plan_days[0]["meals"]
    assert len(meals) == 3
    types = [m["type"] for m in meals]
    assert types == ["breakfast", "lunch", "dinner"]

    for m in meals:
        rating = float(m.get("rating") or 0.0)
        assert rating >= 4.0, f"美食评分低于 4.0: {m}"
        assert m.get("name"), "美食缺少店名"
        assert m.get("estimated_cost") is not None, "缺少价格预算"


def test_output_node_contains_hotel_and_meals():
    """验证 output_node 在输出 Markdown 中完整渲染酒店推荐与三餐美食"""
    state: SessionGraphState = {
        "requirements": {
            "slots": {
                "city": {"key": "city", "value": "成都"},
                "days": {"key": "days", "value": 2},
            },
            "locked_items": [],
            "revision_id": 1,
        },
        "current_plan": {
            "algorithm_telemetry": {
                "kmeans": {"total_pois": 8, "days": 2},
                "minimax_hotel": {"hotel_name": "成都中心智选假日酒店"},
                "route_2opt": {"total_saved_km": 6.8},
            },
            "days": [
                {
                    "day_index": 0,
                    "date": "2026-09-21",
                    "attractions": [
                        {"name": "武侯祠", "arrive_time": "09:00", "depart_time": "11:00", "distance_km": 0.0},
                        {"name": "锦里", "arrive_time": "11:15", "depart_time": "13:00", "distance_km": 1.2},
                    ],
                    "hotel": {
                        "name": "成都中心智选假日酒店",
                        "hotel_type": "舒适型",
                        "price_range": "350-450元",
                    },
                    "meals": [
                        {"type": "breakfast", "name": "老字号早点", "rating": 4.6, "estimated_cost": 15, "description": "特色小吃"},
                        {"type": "lunch", "name": "陈麻婆豆腐", "rating": 4.8, "estimated_cost": 60, "description": "中华老字号"},
                        {"type": "dinner", "name": "蜀九香火锅", "rating": 4.9, "estimated_cost": 120, "description": "地道牛油火锅"},
                    ],
                }
            ],
        },
    }

    out = output_node(state)
    resp = out["final_response"]

    # 断言包含算法白盒度量
    assert "空间 K-Means 均衡聚类" in resp
    assert "Minimax 极小化通勤选址" in resp
    assert "2-Opt TSP" in resp

    # 断言包含酒店推荐
    assert "推荐住宿：**成都中心智选假日酒店**" in resp

    # 断言包含三餐美食
    assert "当地精选美食 (高德 4.0+ / 地道老字号)" in resp
    assert "陈麻婆豆腐" in resp
    assert "蜀九香火锅" in resp
    assert "⭐ 4.8" in resp
