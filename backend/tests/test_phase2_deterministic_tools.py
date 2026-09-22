"""Phase 2 自动化单元测试集: 确定性算法工具化与丰富诊断信号改造

覆盖目标:
1. 日内路线求解正常时间窗规划 (solve_day_route_tool)
2. 日内路线时间窗超限与结构化诊断信号生成 (TIME_WINDOW_EXCEEDED)
3. 用户锁定项 (immutable_constraints) 保护与自愈建议生成
4. 预算精算工具正常核算与超支诊断 (check_budget_tool, BUDGET_EXCEEDED)
5. 空间 K-Means 聚类工具包装 (cluster_pois_tool)
6. 现有算法接口向下兼容性检验 (solve_daily_route)
"""
import pytest
from app.models.diagnostics import ErrorCode, DiagnosticSeverity
from app.services.route_solver import solve_daily_route, solve_day_route_with_diagnostics
from app.tools.planning_tools import (
    solve_day_route_tool,
    cluster_pois_tool,
    check_budget_tool,
)


@pytest.fixture
def nearby_pois():
    """北京核心区 3 个临近景点，正常用时约 5 小时"""
    return [
        {"name": "故宫博物院", "lng": 116.397, "lat": 39.916, "visit_minutes": 150, "price": 60},
        {"name": "景山公园", "lng": 116.396, "lat": 39.924, "visit_minutes": 60, "price": 2},
        {"name": "天安门广场", "lng": 116.397, "lat": 39.908, "visit_minutes": 60, "price": 0},
    ]


@pytest.fixture
def overloaded_pois():
    """4 个高耗时且空间跨度大的景点，总耗时远超 8 小时"""
    return [
        {"name": "故宫博物院", "lng": 116.397, "lat": 39.916, "visit_minutes": 200, "price": 60},
        {"name": "八达岭长城", "lng": 116.016, "lat": 40.359, "visit_minutes": 240, "price": 40},
        {"name": "颐和园", "lng": 116.273, "lat": 39.999, "visit_minutes": 180, "price": 30},
        {"name": "天坛公园", "lng": 116.411, "lat": 39.882, "visit_minutes": 120, "price": 15},
    ]


def test_route_solver_normal_success(nearby_pois):
    """测试正常时间窗内规划成功，无诊断异常"""
    hotel = {"lng": 116.405, "lat": 39.912}
    result = solve_day_route_tool(
        pois=nearby_pois,
        start_hour=9,
        close_hour=20,
        start_hotel=hotel,
        day_index=0,
    )

    assert result.success is True
    assert result.exceeds_day is False
    assert result.diagnostics is None
    assert len(result.route) == 3
    assert result.total_ticket == 62
    assert result.total_min > 0


def test_route_solver_time_window_exceeded_diagnostics(overloaded_pois):
    """测试时间窗超限时，输出结构化诊断信号并保护锁定项"""
    # 设定紧凑时间窗 9:00 ~ 17:00 (8小时=480分钟)
    result = solve_day_route_tool(
        pois=overloaded_pois,
        start_hour=9,
        close_hour=17,
        day_index=1,
        immutable_names=["故宫博物院"],  # 用户显式锁定
    )

    assert result.success is False
    assert result.exceeds_day is True
    assert result.diagnostics is not None

    diag = result.diagnostics
    assert diag.error_code == ErrorCode.TIME_WINDOW_EXCEEDED
    assert diag.severity == DiagnosticSeverity.HARD_FAIL
    assert diag.day_index == 1
    assert diag.details["exceeded_minutes"] > 0
    assert diag.details["available_minutes"] == 480
    assert "故宫博物院" in diag.immutable_constraints
    assert "八达岭长城" in diag.conflicting_items
    assert "PRUNE_LOW_PRIORITY_POI" in diag.actionable_suggestions


def test_check_budget_tool_within_budget():
    """测试预算核算：开销在预算内，无超支诊断"""
    mock_days = [
        {"attractions": [{"name": "A", "ticket_price": 60}, {"name": "B", "ticket_price": 40}]},
        {"attractions": [{"name": "C", "ticket_price": 50}]},
    ]
    # 门票 150 + 酒店 300*1 + 餐饮 150*2=300 + 城际 200 = 950
    breakdown, diag = check_budget_tool(
        plan_days=mock_days,
        hotel_per_night_cost=300.0,
        days=2,
        intercity_cost=200.0,
        budget_limit=1500.0,
    )

    assert diag is None
    assert breakdown["ticket_cost"] == 150.0
    assert breakdown["hotel_cost"] == 300.0
    assert breakdown["meals_cost"] == 300.0
    assert breakdown["intercity_cost"] == 200.0
    assert breakdown["total_cost"] == 950.0


def test_check_budget_tool_overrun_diagnostics():
    """测试预算超支：触发 BUDGET_EXCEEDED 诊断，包含超额金额"""
    mock_days = [
        {"attractions": [{"name": "A", "ticket_price": 200}]},
        {"attractions": [{"name": "B", "ticket_price": 300}]},
        {"attractions": [{"name": "C", "ticket_price": 200}]},
    ]
    # 门票 700 + 酒店 600*2=1200 + 餐饮 150*3=450 + 城际 500 = 2850
    breakdown, diag = check_budget_tool(
        plan_days=mock_days,
        hotel_per_night_cost=600.0,
        days=3,
        intercity_cost=500.0,
        budget_limit=2000.0,  # 上限2000，超额 850
    )

    assert diag is not None
    assert diag.error_code == ErrorCode.BUDGET_EXCEEDED
    assert diag.severity == DiagnosticSeverity.HARD_FAIL
    assert diag.details["overrun_amount"] == 850.0
    assert "SWAP_HOTEL_TO_ECONOMY" in diag.actionable_suggestions


def test_cluster_pois_tool_execution(nearby_pois, overloaded_pois):
    """测试空间聚类工具包装正确执行分日划分"""
    all_pois = nearby_pois + overloaded_pois
    clusters = cluster_pois_tool(pois=all_pois, days=2)

    assert len(clusters) == 2
    allocated_count = sum(len(c.get("pois", [])) for c in clusters)
    assert allocated_count == len(all_pois)


def test_backward_compatibility_solve_daily_route(nearby_pois):
    """确保既有老函数 solve_daily_route 返回类型与行为 100% 保持不变"""
    plan = solve_daily_route(nearby_pois, start_hour=9, close_hour=20)
    assert isinstance(plan, list)
    assert len(plan) == 3
    assert "arrive_min" in plan[0]
    assert "depart_min" in plan[0]
    assert "travel_min_from_prev" in plan[0]
