"""三餐真实数据落地 — 不再让 LLM 编造餐厅"""
from conftest import base_state, make_plan_response, make_poi
from app.graph import nodes


def test_meals_filled_from_real_food_pois(graph, patch_nodes):
    """planner 输出空 meals → _enrich_meals 用 500m 美食 POI 填充。"""
    wrapper, fake_planner, _ = patch_nodes
    fake_planner.response = make_plan_response(days=2, attractions_per_day=2)

    result = graph.invoke(base_state(), {"configurable": {"thread_id": "test-thread"}})
    days = result["final_plan"]["days"]
    for d in days:
        assert d["meals"], f"{d['date']} 的 meals 应为空后被填充"
        assert len(d["meals"]) == 3
        assert {m["type"] for m in d["meals"]} == {"breakfast", "lunch", "dinner"}
        # 餐厅名来自真实候选（fake foods），且带坐标与来源
        for m in d["meals"]:
            assert m["name"]
            assert m["source"] == "amap"
            assert "location" in m

    # food 查询按景点坐标 500m 周边执行（planner 只执行 1 次 → 每天 1 次）
    food_calls = [c for c in wrapper.calls if c[0] == "food"]
    assert len(food_calls) == 2
    assert food_calls[0][2]  # center 非空
    assert food_calls[0][3] == ""  # radius 默认（500m）


def test_meals_skipped_when_no_coords(graph, patch_nodes):
    """景点无坐标 → 跳过填充（不阻塞计划）。"""
    wrapper, fake_planner, _ = patch_nodes
    plan = make_plan_response(days=1, attractions_per_day=2)
    plan = plan.replace('"location": {"longitude": 116.4, "latitude": 39.9}',
                        '"location": {}')
    fake_planner.response = plan
    result = graph.invoke(base_state(), {"configurable": {"thread_id": "test-thread"}})
    assert result["final_plan"]["days"][0]["meals"] == []


def test_food_failure_degrades_silently(graph, patch_nodes):
    """美食检索失败 → meals 保持原样，不产生硬伤。"""
    wrapper, fake_planner, _ = patch_nodes
    wrapper.foods = []
    fake_planner.response = make_plan_response(days=1, attractions_per_day=2)
    result = graph.invoke(base_state(), {"configurable": {"thread_id": "test-thread"}})
    assert result["final_plan"]["days"]          # 计划仍然有效
    assert not any("三餐" in e for e in result["error_log"] if "硬伤" in e)
