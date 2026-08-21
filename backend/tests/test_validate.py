"""v3 校验语义 — 本地链路硬伤记录仍交付（聚类/预算本地保证，不再回环重试）

v2: 硬伤 → retry_planner 自回环（预算/景点数由 LLM 输出决定，需重试修正）
v3: 景点集合由聚类分配（每天≥2 或 leisure 豁免）、预算由本地计算（_compute_budget），
    硬伤在结构上不可能由 LLM 引入 → merge_node 不回环，记录 error_log 透明降级交付。
"""
from conftest import base_state, make_plan_response
from app.graph import nodes


def test_valid_plan_routes_done(graph, patch_nodes):
    state = base_state(budget=2000)
    result = graph.invoke(state, {"configurable": {"thread_id": "test-thread"}})
    assert result["final_plan"]["city"] == "北京"
    assert result["final_plan"]["days"]


def test_budget_overrun_records_error_still_delivers(graph, patch_nodes):
    """本地预算超出请求预算 → 硬伤记录 error_log，仍交付计划（v3 不回环）。"""
    _, fake_planner, _ = patch_nodes
    fake_planner.response = make_plan_response()
    result = graph.invoke(base_state(budget=100), {"configurable": {"thread_id": "test-thread"}})
    # v3: 3 个 POI → 1 normal 簇 + 1 leisure 天 → 文案 LLM 只调 1 次（无重试）
    assert len(fake_planner.prompts) == 1
    assert result["final_plan"]["days"]
    assert any("预算" in e for e in result["error_log"])


def test_few_attractions_becomes_leisure_day(graph, patch_nodes):
    """景点不足每天 2 个 → 自由活动日补位（v3 聚类边界，不再触发硬伤重试）。"""
    _, fake_planner, _ = patch_nodes
    fake_planner.response = make_plan_response()
    # fake_wrapper 只有 3 个 POI，days=3 → 1 个 normal 簇 + 2 个 leisure 天
    result = graph.invoke(base_state(days=3), {"configurable": {"thread_id": "test-thread"}})
    days = result["final_plan"]["days"]
    assert len(days) == 3
    kinds = [d.get("kind") for d in days]
    assert "leisure" in kinds
    assert not any("硬伤" in e and "景点数" in e for e in result["error_log"])
    # leisure 天零 LLM：文案只对 normal 天调用
    assert len(fake_planner.prompts) == 1


def test_zero_budget_ok_when_none_requested(graph, patch_nodes):
    """未提供预算时预算字段不触发硬伤。"""
    _, fake_planner, _ = patch_nodes
    fake_planner.response = make_plan_response()
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
