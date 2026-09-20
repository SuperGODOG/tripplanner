"""周一闭馆与时间窗微调优化专项测试集"""
import pytest
from app.models.diagnostics import ErrorCode, DiagnosticSeverity, DiagnosticSignal
from app.services.route_solver import solve_day_route_with_diagnostics
from app.tools.rag_tools import lookup_place_facts_tool
from app.agents.repair_agent import RepairAgent


def test_flexible_evening_window_preserves_all_pois():
    """测试常规规划（4个景点）即使游玩耗时稍长，也通过弹性延展至22:00保全全部景点，绝不删减"""
    # 模拟 4 个充实景点，每处 120 分钟 + 交通，总时长预计超过 21:00 但在 22:00 内
    pois = [
        {"name": "景点A", "lng": 104.06, "lat": 30.67, "visit_minutes": 120, "price": 50},
        {"name": "景点B", "lng": 104.08, "lat": 30.68, "visit_minutes": 120, "price": 40},
        {"name": "景点C", "lng": 104.07, "lat": 30.65, "visit_minutes": 120, "price": 30},
        {"name": "景点D", "lng": 104.09, "lat": 30.66, "visit_minutes": 120, "price": 20},
    ]

    res = solve_day_route_with_diagnostics(
        pois=pois,
        start_hour=9,
        close_hour=21,
        day_index=0,
    )

    # 1. 全部 4 个景点完整保留，绝不丢失
    assert res.success is True
    assert len(res.route) == 4
    route_names = [r["poi"]["name"] for r in res.route]
    assert route_names == ["景点A", "景点B", "景点C", "景点D"] or len(set(route_names)) == 4

    # 2. 诊断级别为 WARNING 软预警，绝非致命的 HARD_FAIL
    if res.diagnostics:
        assert res.diagnostics.severity == DiagnosticSeverity.WARNING
        assert "RELAX_PACE" in res.diagnostics.actionable_suggestions


def test_nature_venues_exempt_from_monday_closure():
    """测试自然风光与开放街区逢周一不会被误判为周一闭馆"""
    # 2026-08-24 是周一
    monday_str = "2026-08-24"

    # 自然名胜与街区均应正常开放
    emei = lookup_place_facts_tool("峨眉山风景区", target_date=monday_str, city="乐山")
    assert emei.is_open_on_date is not False

    dadu = lookup_place_facts_tool("乐山大佛", target_date=monday_str, city="乐山")
    assert dadu.is_open_on_date is not False

    chunxi = lookup_place_facts_tool("春熙路商业街", target_date=monday_str, city="成都")
    assert chunxi.is_open_on_date is not False


def test_national_museums_monday_closed():
    """测试全国著名文博场馆能精准识别周一闭馆"""
    monday_str = "2026-08-24"

    sanxingdui = lookup_place_facts_tool("三星堆博物馆", target_date=monday_str, city="德阳")
    assert sanxingdui.is_open_on_date is False
    assert "闭馆冲突" in sanxingdui.evidence_snippet or "周一" in sanxingdui.evidence_snippet

    shaanxi = lookup_place_facts_tool("陕西历史博物馆", target_date=monday_str, city="西安")
    assert shaanxi.is_open_on_date is False


def test_repair_agent_single_day_monday_closure_soft_notice():
    """测试单日行程遇到周一闭馆时，安全降级为温馨提示，不崩溃、不强删"""
    agent = RepairAgent(max_attempts=2)

    single_day = [
        {
            "day_index": 0,
            "attractions": [{"name": "三星堆博物馆", "visit_minutes": 180, "price": 72}],
            "route": [],
        }
    ]

    closure_diag = DiagnosticSignal(
        error_code=ErrorCode.VENUE_CLOSED,
        day_index=0,
        severity=DiagnosticSeverity.HARD_FAIL,
        summary="第 1 天行程冲突：三星堆博物馆周一闭馆",
        details={"place_name": "三星堆博物馆", "target_date": "2026-08-24"},
        conflicting_items=["三星堆博物馆"],
        immutable_constraints=[],
        actionable_suggestions=["SWAP_TO_ANOTHER_DAY"],
    )

    repaired_days, is_resolved, actions = agent.repair_plan(
        plan_days=single_day,
        diagnostics=[closure_diag],
        immutable_names=[],
    )

    # 1. 成功处理，无异常
    assert is_resolved is True
    # 2. 生成 VENUE_NOTICE 软性提示
    assert any("VENUE_NOTICE" in a for a in actions)
    # 3. 景点安全保留
    assert repaired_days[0]["attractions"][0]["name"] == "三星堆博物馆"


def test_repair_agent_preserves_rich_schedule():
    """测试 RepairAgent 在处理 <= 4 个景点的日常行程时，绝不随意执行 PRUNE_POI 删减景点"""
    agent = RepairAgent(max_attempts=2)

    normal_day = [
        {
            "day_index": 0,
            "start_hour": 9,
            "close_hour": 21,
            "attractions": [
                {"name": "景点甲", "visit_minutes": 90, "price": 30},
                {"name": "景点乙", "visit_minutes": 120, "price": 40},
                {"name": "景点丙", "visit_minutes": 90, "price": 20},
            ],
            "route": [],
        }
    ]

    overrun_diag = DiagnosticSignal(
        error_code=ErrorCode.TIME_WINDOW_EXCEEDED,
        day_index=0,
        severity=DiagnosticSeverity.WARNING,
        summary="第 1 天总用时预计超过日时间窗 15 分钟",
        details={"available_minutes": 720, "required_minutes": 735},
        conflicting_items=["景点乙"],
        immutable_constraints=[],
        actionable_suggestions=["EXPAND_WINDOW", "RELAX_PACE"],
    )

    repaired_days, is_resolved, actions = agent.repair_plan(
        plan_days=normal_day,
        diagnostics=[overrun_diag],
        immutable_names=[],
    )

    assert is_resolved is True
    # 绝不产生 PRUNE_POI
    assert not any("PRUNE_POI" in a for a in actions)
    # 3 个景点全部健在
    assert len(repaired_days[0]["attractions"]) == 3
    # 触发弹性延展 EXPAND_SCHEDULE
    assert any("EXPAND_SCHEDULE" in a for a in actions)
    assert repaired_days[0]["close_hour"] == 22
