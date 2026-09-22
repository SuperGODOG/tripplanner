"""热门名胜实名预约与售罄预警测试套件 (Reservation Policy Tests)

验证核心场景:
1. 重点 5A 与热门文博 (故宫/国博/莫高窟/兵马俑/布达拉宫) 放票周期与抢票窗口判定
2. 出行临近 (天数不足放票周期) 准确触发 CRITICAL 售罄风险并推荐平替名胜
3. 当天放票窗口准确触发 URGENT 抢票告警
4. 远期出行准确触发 NOTICE 备忘日历提示
5. 普通非限制名胜安全返回 None 不做冗余干扰
6. Harness 规划循环中对含受限名胜的行程自动富化 reservation_alert 并发射思考预警事件
"""
from __future__ import annotations

from datetime import date, timedelta
import pytest

from app.services.reservation_policy import evaluate_poi_reservation, RESERVATION_RULES
from app.harness.agent_loop import TravelAgentHarness
from app.harness.events import ThinkingEvent, PlanVersionEvent
from app.harness.registry import travel_tools


def test_reservation_rules_coverage():
    """1. 规则库基础完整度检验"""
    assert len(RESERVATION_RULES) >= 10
    names = {r.poi_name for r in RESERVATION_RULES}
    assert "故宫博物院" in names
    assert "莫高窟" in names
    assert "秦始皇帝陵博物院(兵马俑)" in names


def test_critical_reservation_risk_when_days_insufficient():
    """2. 距离出行不足放票天数且不可现场购票 -> 触发 CRITICAL 售罄警告与平替推荐"""
    today = date(2026, 9, 21)
    # 模拟用户明天就要去故宫 (提前 1 天规划，故宫需提前 7 天)
    visit_tomorrow = date(2026, 9, 22)
    alert = evaluate_poi_reservation("故宫博物院", visit_date=visit_tomorrow, planning_date=today)

    assert alert is not None
    assert alert["risk_level"] == "critical"
    assert alert["lead_days"] == 7
    assert alert["days_ahead"] == 1
    assert "售罄" in alert["alert_title"]
    assert "恭王府" in alert["backup_pois"]
    assert alert["backup_poi"] == "恭王府"
    assert alert["release_time"] == "20:00"


def test_urgent_booking_window():
    """3. 正好在放票当天 -> 触发 URGENT 紧急定闹钟抢票"""
    today = date(2026, 9, 21)
    # 7 天后出行: 2026-09-28，今日正是放票日
    visit_target = today + timedelta(days=7)
    alert = evaluate_poi_reservation("故宫博物院-午门", visit_date=visit_target, planning_date=today)

    assert alert is not None
    assert alert["risk_level"] == "urgent"
    assert alert["lead_days"] == 7
    assert alert["days_ahead"] == 7
    assert "今日放票" in alert["alert_title"]


def test_notice_future_booking_reminder():
    """4. 远期出行 (15天后) -> 触发 NOTICE 备忘"""
    today = date(2026, 9, 21)
    visit_future = today + timedelta(days=15)
    alert = evaluate_poi_reservation("莫高窟", visit_date=visit_future, planning_date=today)

    assert alert is not None
    # 莫高窟需提前 30 天，15 天后出行属于已不足 30 天的 CRITICAL
    assert alert["risk_level"] == "critical"

    # 40 天后出行对莫高窟属于 NOTICE
    visit_far = today + timedelta(days=40)
    alert_far = evaluate_poi_reservation("莫高窟", visit_date=visit_far, planning_date=today)
    assert alert_far is not None
    assert alert_far["risk_level"] == "notice"
    assert alert_far["lead_days"] == 30
    assert "西千佛洞" in alert_far["backup_pois"]


def test_unrestricted_poi_returns_none():
    """5. 普通开放公园与历史商业街区 -> 返回 None"""
    today = date(2026, 9, 21)
    alert = evaluate_poi_reservation("朝阳公园", visit_date=today + timedelta(days=1), planning_date=today)
    assert alert is None

    alert2 = evaluate_poi_reservation("前门大街", visit_date=today + timedelta(days=1), planning_date=today)
    assert alert2 is None


@pytest.mark.asyncio
async def test_harness_agent_loop_injects_reservation_alert(monkeypatch):
    """6. 验证 Harness 主循环自动将 reservation_alert 注入景点卡片并广播思考事件"""
    orig_call = travel_tools.call

    async def mock_call(name: str, **kwargs):
        if name == "fetch_tavily_notes":
            return {"summary": "测试指南", "tips": ["提前准备证件"]}, 5.0
        return await orig_call(name, **kwargs)

    monkeypatch.setattr(travel_tools, "call", mock_call)

    harness = TravelAgentHarness(registry=travel_tools)
    events = []

    # 明天去北京（故宫作为核心景点），必触发提前抢票预警
    async for ev in harness.run(
        session_id="sess_test_reservation",
        user_input="明天去北京玩2天，必须去故宫博物院",
        user_id="alice_tester",
    ):
        events.append(ev)

    # 验证思考流包含预约预警
    alert_events = [e for e in events if isinstance(e, ThinkingEvent) and e.payload.get("step") == "reservation_alert"]
    assert len(alert_events) >= 1
    assert "预约预警" in alert_events[0].payload.get("detail", "")
    assert "故宫" in alert_events[0].payload.get("detail", "")

    # 验证最终计划中的景点字典包含 reservation_alert
    plan_events = [e for e in events if isinstance(e, PlanVersionEvent)]
    assert len(plan_events) >= 1
    days = plan_events[0].payload.get("plan", {}).get("days", [])
    
    gugong_poi = None
    for d in days:
        for a in d.get("attractions", []):
            if "故宫" in a.get("name", ""):
                gugong_poi = a
                break
        if gugong_poi:
            break

    assert gugong_poi is not None
    assert "reservation_alert" in gugong_poi
    res_info = gugong_poi["reservation_alert"]
    assert res_info["risk_level"] in ("critical", "urgent")
    assert res_info["lead_days"] == 7
    assert res_info["backup_poi"] == "恭王府"
