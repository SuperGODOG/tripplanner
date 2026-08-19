"""硬伤校验与 Planner 回环 — 预算 / 景点数 / 重试耗尽"""
from conftest import base_state, make_plan_response
from app.graph import nodes


def test_valid_plan_routes_done(graph, patch_nodes):
    state = base_state(budget=2000)
    result = graph.invoke(state, {"configurable": {"thread_id": "test-thread"}})
    assert result["final_plan"]["city"] == "北京"
    assert result["final_plan"]["days"]


def test_budget_overrun_retries_planner(graph, patch_nodes):
    """总预算超限 → retry_planner 自回环。"""
    _, fake_planner, _ = patch_nodes
    fake_planner.response = make_plan_response(budget_total=3000)   # 请求预算 2000
    result = graph.invoke(base_state(budget=2000), {"configurable": {"thread_id": "test-thread"}})
    assert len(fake_planner.prompts) >= 2        # 至少重试了一次
    assert result["final_plan"]["days"]


def test_budget_exhausted_after_retries_done_with_error(graph, patch_nodes):
    """重试 3 次仍超预算 → 强制 done + 硬伤 error_log（不无限循环）。"""
    _, fake_planner, _ = patch_nodes
    fake_planner.response = make_plan_response(budget_total=5000)
    result = graph.invoke(base_state(budget=1000), {"configurable": {"thread_id": "test-thread"}})
    assert len(fake_planner.prompts) <= 1 + 3    # 初始 + 最多 3 次重试
    assert any("硬伤" in e and "重试" in e for e in result["error_log"])


def test_few_attractions_retries(graph, patch_nodes):
    """每天 <2 景点 → 硬伤重试。"""
    _, fake_planner, _ = patch_nodes
    fake_planner.response = make_plan_response(attractions_per_day=1)
    result = graph.invoke(base_state(), {"configurable": {"thread_id": "test-thread"}})
    assert len(fake_planner.prompts) >= 2


def test_zero_budget_ok_when_none_requested(graph, patch_nodes):
    """未提供预算时预算字段不触发硬伤。"""
    _, fake_planner, _ = patch_nodes
    fake_planner.response = make_plan_response(budget_total=0)
    result = graph.invoke(base_state(budget=None), {"configurable": {"thread_id": "test-thread"}})
    assert result["final_plan"]["days"]


def test_validate_refine_no_hotel_loop_route():
    """离群不再产生 retry_hotel 路由（回环已删除）。"""
    state = base_state()
    plan = {"city": "北京", "start_date": "2026-08-21", "days": [
        {"date": "2026-08-21", "attractions": [
            {"name": "A", "location": {"longitude": 116.4, "latitude": 39.9}},
            {"name": "B", "location": {"longitude": 116.5, "latitude": 39.95}},
        ]}], "budget": {"total": 100}, "overall_suggestions": "ok"}
    result = nodes._validate_and_refine(state, plan)
    assert result["planner_route"] in ("done", "retry_planner")
    assert "retry_hotel" not in result.values()
