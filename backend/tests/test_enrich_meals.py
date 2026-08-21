"""三餐真实数据落地 — 不再让 LLM 编造餐厅（v3: merge 阶段填充，坐标结构保证）"""
from conftest import base_state, make_plan_response
from app.graph import nodes


def test_meals_filled_from_real_food_pois(graph, patch_nodes):
    """normal 天三餐用 500m 美食 POI 填充；leisure 天无景点三餐留空。"""
    wrapper, fake_planner, _ = patch_nodes
    fake_planner.response = make_plan_response(days=2, attractions_per_day=2)

    result = graph.invoke(base_state(days=2), {"configurable": {"thread_id": "test-thread"}})
    days = result["final_plan"]["days"]
    normal_days = [d for d in days if d.get("kind") != "leisure"]
    assert normal_days, "至少一个 normal 天"
    for d in normal_days:
        assert d["meals"], f"{d['date']} 的 meals 应为空后被填充"
        assert len(d["meals"]) == 3
        assert {m["type"] for m in d["meals"]} == {"breakfast", "lunch", "dinner"}
        # 餐厅名来自真实候选（fake foods），且带坐标与来源
        for m in d["meals"]:
            assert m["name"]
            assert m["source"] == "amap"
            assert "location" in m

    # food 查询按景点坐标 500m 周边执行（每 normal 天 1 次）
    food_calls = [c for c in wrapper.calls if c[0] == "food"]
    assert len(food_calls) == len(normal_days)
    assert food_calls[0][2]  # center 非空
    assert food_calls[0][3] == ""  # radius 默认（500m）


def test_meals_skipped_when_no_coords(monkeypatch):
    """景点无坐标 → 跳过填充（防御性: v3 结构上坐标必有，不阻塞计划）。"""
    from tests.conftest import FakeAmapWrapper
    monkeypatch.setattr(nodes, "_get_amap_wrapper", lambda: FakeAmapWrapper(foods=[]))
    plan = {"city": "北京", "days": [{
        "date": "2026-08-21", "kind": "normal",
        "attractions": [{"name": "A", "location": {}}],
    }]}
    nodes._enrich_meals(plan, "北京")  # 不抛异常
    assert plan["days"][0].get("meals", []) == []


def test_food_failure_degrades_silently(graph, patch_nodes):
    """美食检索失败 → meals 保持原样，不产生硬伤。"""
    wrapper, fake_planner, _ = patch_nodes
    wrapper.foods = []
    fake_planner.response = make_plan_response(days=1, attractions_per_day=2)
    result = graph.invoke(base_state(days=1), {"configurable": {"thread_id": "test-thread"}})
    assert result["final_plan"]["days"]
    assert not any("三餐" in e for e in result["error_log"] if "硬伤" in e)
