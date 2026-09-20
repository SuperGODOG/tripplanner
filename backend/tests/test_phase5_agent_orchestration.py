"""Phase 5 自动化单元测试集: 三 Agent 编排状态机 & 闭环自愈网络

覆盖目标:
1. 意图澄清 Agent 槽位抽取与持久性副词防污染作用域判定 (test_clarification_agent_extracts_slots)
2. 缺失必要信息时触发 LangGraph 原生 interrupt 挂起，通过 thread_id 恢复执行 (test_clarification_interrupt_and_resume)
3. 闭环自愈: 周一闭馆冲突自动与常态开放景点跨日对调 (test_repair_monday_closure_swap_days)
4. 闭环自愈: 时间超限裁剪时严格保护用户显式锁定项 (test_repair_protects_immutable_constraints)
5. 闭环自愈: 预算超支时自动降级酒店住宿成本 (test_repair_budget_exceeded)
6. 闭环自愈: 熔断机制 (max_attempts = 2) 超出后安全转人工裁决 (test_repair_max_attempts_escalation)
"""
import pytest
from langgraph.types import Command
from langgraph.checkpoint.memory import InMemorySaver

from app.models.session import (
    EffectiveRequirements,
    SlotOrigin,
    PreferenceScope,
)
from app.models.diagnostics import (
    ErrorCode,
    DiagnosticSeverity,
    DiagnosticSignal,
)
from app.agents.clarification_agent import (
    extract_slots_from_input,
    check_clarification_needed,
)
from app.agents.repair_agent import RepairAgent
from app.graph.session_graph import build_session_graph


def test_clarification_agent_extracts_slots():
    """测试自然语言槽位抽取与持久性偏好作用域判定"""
    # 场景 1: 单次行程需求，带锁定项
    text1 = "我想去北京玩3天，预算5000元，必须去故宫，这次想吃烤鸭和涮羊肉"
    req1 = extract_slots_from_input(text1)

    assert req1.get_slot_value("city") == "北京"
    assert req1.get_slot_value("days") == 3
    assert req1.get_slot_value("budget_total") == 5000.0
    assert "故宫" in req1.locked_items
    pref_slot1 = req1.slots.get("preferences")
    assert pref_slot1 is not None
    assert pref_slot1.scope == PreferenceScope.TRIP_TRANSIENT  # 单次需求

    # 场景 2: 带有“平时一直”，判定为长期偏好作用域
    text2 = "我打算去西安5天，平时一直吃辣，每次都住靠近地铁的酒店"
    req2 = extract_slots_from_input(text2)

    assert req2.get_slot_value("city") == "西安"
    assert req2.get_slot_value("days") == 5
    pref_slot2 = req2.slots.get("preferences")
    assert pref_slot2 is not None
    assert pref_slot2.scope == PreferenceScope.LONG_TERM_USER  # 长期偏好防污染作用域


def test_clarification_interrupt_and_resume():
    """测试必要信息缺失时触发 interrupt 挂起，并通过 thread_id + Command 恢复执行"""
    saver = InMemorySaver()
    graph = build_session_graph(checkpointer=saver)

    thread_id = "test_thread_interrupt_001"
    config = {"configurable": {"thread_id": thread_id}}

    # 1. 首次输入缺少城市和天数：“我想带家人出去旅游，预算1万”
    initial_state = {
        "session_id": "s_001",
        "user_id": "u_001",
        "thread_id": thread_id,
        "input_text": "我想带家人出去旅游，预算1万元",
        "messages": [],
    }

    res1 = graph.invoke(initial_state, config=config)

    # 断言触发了中断挂起
    assert "__interrupt__" in res1
    interrupts = res1["__interrupt__"]
    assert len(interrupts) > 0
    prompt_payload = interrupts[0].value
    assert "城市" in prompt_payload["prompt_text"]
    assert "city" in prompt_payload["missing_slots"]
    assert len(prompt_payload["options"]) >= 3

    # 2. 模拟前端用户点击选项或回复“北京”恢复执行
    # LangGraph 1.2+ 支持 Command(resume=...)
    res2 = graph.invoke(Command(resume={"key": "city", "value": "北京"}), config=config)

    # 再次挂起：城市已补齐，但天数仍然缺失
    assert "__interrupt__" in res2
    interrupts2 = res2["__interrupt__"]
    assert "days" in interrupts2[0].value["missing_slots"]

    # 3. 模拟用户提供天数：“3天”
    res3 = graph.invoke(Command(resume={"key": "days", "value": 3}), config=config)

    # 再次挂起：城市、天数已补齐，提示选择出发日期以对接天气与闭馆核验
    assert "__interrupt__" in res3
    interrupts3 = res3["__interrupt__"]
    assert "start_date" in interrupts3[0].value["missing_slots"]

    # 4. 模拟用户提供日期：“2026-10-01”
    res4 = graph.invoke(Command(resume={"key": "start_date", "value": "2026-10-01"}), config=config)

    # 信息已齐全，成功跑通全流程到达输出
    assert res4.get("status") in ("ready", "escalated")
    assert "北京" in res4.get("final_response", "")
    assert res4.get("current_plan") is not None
    assert len(res4["current_plan"]["days"]) == 3


def test_repair_monday_closure_swap_days():
    """测试周一闭馆冲突自动与常态开放景点跨日对调"""
    agent = RepairAgent(max_attempts=2)

    # Day 0 是周一，安排了周一闭馆的“故宫博物院”
    # Day 1 是周二，安排了常态化开放的“天坛公园”
    mock_days = [
        {
            "day_index": 0,
            "date": "2026-08-24",  # 2026-08-24 是周一
            "attractions": [
                {"name": "故宫博物院", "visit_minutes": 180, "price": 60},
                {"name": "景山公园", "visit_minutes": 60, "price": 2},
            ],
        },
        {
            "day_index": 1,
            "date": "2026-08-25",  # 2026-08-25 是周二
            "attractions": [
                {"name": "天坛公园", "visit_minutes": 120, "price": 15},
                {"name": "天安门广场", "visit_minutes": 60, "price": 0},
            ],
        },
    ]

    closure_diag = DiagnosticSignal(
        error_code=ErrorCode.VENUE_CLOSED,
        day_index=0,
        severity=DiagnosticSeverity.HARD_FAIL,
        summary="第 1 天行程冲突：故宫博物院周一闭馆",
        details={"place_name": "故宫博物院", "target_date": "2026-08-24"},
        conflicting_items=["故宫博物院"],
        immutable_constraints=[],
        actionable_suggestions=["SWAP_TO_ANOTHER_DAY"],
    )

    repaired_days, is_resolved, actions = agent.repair_plan(
        plan_days=mock_days,
        diagnostics=[closure_diag],
        immutable_names=["故宫博物院"],
    )

    assert is_resolved is True
    assert len(actions) == 1
    assert "SWAP_DAYS" in actions[0]

    # 故宫博物院必须已被调换到 Day 1 (周二)
    day0_names = [a["name"] for a in repaired_days[0]["attractions"]]
    day1_names = [a["name"] for a in repaired_days[1]["attractions"]]

    assert "故宫博物院" not in day0_names
    assert "故宫博物院" in day1_names
    assert "天坛公园" in day0_names  # 天坛公园被对调到 Day 0


def test_repair_protects_immutable_constraints():
    """测试时间超限自愈裁剪时，严格保护锁定项，仅裁剪非锁定景点"""
    agent = RepairAgent(max_attempts=2)

    mock_days = [
        {
            "day_index": 0,
            "start_hour": 9,
            "close_hour": 17,  # 8 小时
            "attractions": [
                {"name": "故宫博物院", "visit_minutes": 240, "price": 60, "lng": 116.397, "lat": 39.916},
                {"name": "八达岭长城", "visit_minutes": 300, "price": 40, "lng": 116.016, "lat": 40.359},  # 耗时极长
            ],
        }
    ]

    overrun_diag = DiagnosticSignal(
        error_code=ErrorCode.TIME_WINDOW_EXCEEDED,
        day_index=0,
        severity=DiagnosticSeverity.HARD_FAIL,
        summary="第 1 天用时超限 120 分钟",
        details={"available_minutes": 480, "required_minutes": 600},
        conflicting_items=["八达岭长城"],
        immutable_constraints=["故宫博物院"],  # 用户锁定故宫
        actionable_suggestions=["PRUNE_LOW_PRIORITY_POI"],
    )

    repaired_days, is_resolved, actions = agent.repair_plan(
        plan_days=mock_days,
        diagnostics=[overrun_diag],
        immutable_names=["故宫博物院"],
    )

    assert is_resolved is True
    assert any("PRUNE_POI" in a for a in actions)

    remaining_names = [a["name"] for a in repaired_days[0]["attractions"]]
    # 锁定项故宫博物院必须保留
    assert "故宫博物院" in remaining_names
    # 非锁定超长项八达岭长城被安全裁剪
    assert "八达岭长城" not in remaining_names


def test_repair_budget_exceeded():
    """测试超支自愈：自动调低高星酒店价格至经济型基准，降低总成本"""
    agent = RepairAgent(max_attempts=2)

    mock_days = [
        {
            "day_index": 0,
            "attractions": [{"name": "A", "price": 100}],
        },
        {
            "day_index": 1,
            "attractions": [{"name": "B", "price": 100}],
        },
    ]

    budget_diag = DiagnosticSignal(
        error_code=ErrorCode.BUDGET_EXCEEDED,
        day_index=0,
        severity=DiagnosticSeverity.HARD_FAIL,
        summary="预算超支 ¥300",
        details={"budget_limit": 800.0, "total_cost": 1100.0, "overrun_amount": 300.0},
        conflicting_items=[],
        immutable_constraints=[],
        actionable_suggestions=["SWAP_HOTEL_TO_ECONOMY"],
    )

    repaired_days, is_resolved, actions = agent.repair_plan(
        plan_days=mock_days,
        diagnostics=[budget_diag],
        budget_total=800.0,
        hotel_cost_per_night=500.0,  # 原每晚 500
    )

    assert is_resolved is True
    assert any("DOWNGRADE_HOTEL" in a for a in actions)
    assert repaired_days[0]["hotel_cost_per_night"] == 200.0


def test_repair_max_attempts_escalation():
    """测试最大自愈重试熔断机制：无法自愈时升级为人机确认 (escalated)"""
    saver = InMemorySaver()
    graph = build_session_graph(checkpointer=saver)

    thread_id = "test_thread_escalate_001"
    config = {"configurable": {"thread_id": thread_id}}

    # 构造一次性输入且包含无法自愈的超低预算（如3天总预算只要 100 元）
    state = {
        "session_id": "s_002",
        "user_id": "u_002",
        "thread_id": thread_id,
        "input_text": "去北京玩3天，2026-10-01出发，预算只要100元，必须去故宫和颐和园",
        "messages": [],
    }

    res = graph.invoke(state, config=config)

    # 断言安全退出，不会无限死循环
    assert res.get("status") in ("ready", "escalated")
    assert res.get("final_response") is not None
    # 包含对预算超支的提示说明
    assert "第 1 天" in res.get("final_response", "")
