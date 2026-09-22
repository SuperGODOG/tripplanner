"""标准 RFC 5545 iCalendar (.ics) 日历导出测试套件 (Calendar Export Tests)

验证核心场景:
1. export_itinerary_to_ics 文本符合 RFC 5545 标准规范 (VCALENDAR, VEVENT, GEO, VALARM)
2. 特殊字符转义与多行备忘录安全渲染 (门票、游玩时长、避坑贴士、预约预警)
3. 酒店首晚自动生成办理入住 VEVENT
4. REST API POST /api/session/calendar/export 导出端点正常返回 text/calendar 附件流
5. REST API GET /api/session/{session_id}/calendar.ics 会话持久化日历下载端点
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api.main import app
from app.harness.session_store import harness_session_store, HarnessSessionSnapshot
from app.services.calendar_exporter import export_itinerary_to_ics


SAMPLE_PLAN = {
    "city": "北京",
    "days": [
        {
            "day_number": 1,
            "date": "2026-09-22",
            "hotel": {
                "name": "王府井希尔顿酒店",
                "lng": 116.415,
                "lat": 39.918,
            },
            "attractions": [
                {
                    "name": "天安门广场",
                    "arrive_time": "08:30",
                    "depart_time": "10:00",
                    "lng": 116.397,
                    "lat": 39.908,
                    "price": 0.0,
                    "category": "国家级地标",
                    "visit_minutes": 90,
                    "tavily_guide": {
                        "tips": ["需提前安检入场", "携带身份证原件"],
                    },
                },
                {
                    "name": "故宫博物院",
                    "arrive_time": "10:30",
                    "depart_time": "14:30",
                    "lng": 116.397,
                    "lat": 39.916,
                    "price": 60.0,
                    "category": "世界文化遗产",
                    "visit_minutes": 180,
                    "reservation_alert": {
                        "risk_level": "critical",
                        "alert_title": "⚠️ 故宫需提前7天实名预约 · 当前可能已售罄",
                        "alert_detail": "现场不设购票处，每日20:00放票",
                        "backup_poi": "恭王府",
                        "release_time": "20:00",
                        "booking_channel": "故宫博物院官方小程序",
                    },
                    "tavily_guide": {
                        "tips": ["午门只进不出", "周一闭馆不要跑空"],
                    },
                },
            ],
        },
        {
            "day_number": 2,
            "date": "2026-09-23",
            "attractions": [
                {
                    "name": "颐和园",
                    "arrive_time": "09:00",
                    "depart_time": "12:30",
                    "lng": 116.273,
                    "lat": 39.999,
                    "price": 30.0,
                    "category": "皇家园林",
                    "visit_minutes": 180,
                }
            ],
        },
    ],
}


def test_export_itinerary_to_ics_rfc5545_compliance():
    """1. 验证生成的 .ics 文本严格遵循 RFC 5545 标头、日历属性与事件段"""
    ics_text = export_itinerary_to_ics(SAMPLE_PLAN, city="北京")

    # 规范标头与日历属性
    assert "BEGIN:VCALENDAR\r\n" in ics_text
    assert "VERSION:2.0\r\n" in ics_text
    assert "PRODID:-//TripPlanner AI//Smart Travel Itinerary//CN\r\n" in ics_text
    assert "X-WR-TIMEZONE:Asia/Shanghai\r\n" in ics_text
    assert "END:VCALENDAR\r\n" in ics_text

    # 包含天安门、故宫与颐和园三个主要景点事件 + 1个首日酒店事件 = 4个 VEVENT
    vevent_count = ics_text.count("BEGIN:VEVENT")
    assert vevent_count == 4

    # 检查故宫事件包含时空坐标
    assert "SUMMARY:📍 Day 1 · 故宫博物院" in ics_text
    assert "DTSTART;TZID=Asia/Shanghai:20260922T103000" in ics_text
    assert "DTEND;TZID=Asia/Shanghai:20260922T143000" in ics_text
    assert "GEO:39.916000;116.397000" in ics_text
    assert "LOCATION:故宫博物院" in ics_text

    # 检查注入的预约告警与避坑贴士
    assert "【门票参考】¥60 元" in ics_text
    assert "【预约注意】⚠️ 故宫需提前7天实名预约" in ics_text
    assert "【满票备选】建议改道平替: 恭王府" in ics_text
    assert "午门只进不出" in ics_text

    # 检查提前 1 小时出行弹窗提醒 (VALARM)
    assert "BEGIN:VALARM" in ics_text
    assert "TRIGGER:-PT1H" in ics_text
    assert "ACTION:DISPLAY" in ics_text

    # 检查酒店入住日程
    assert "SUMMARY:🏨 办理入住 · 王府井希尔顿酒店" in ics_text


def test_api_calendar_direct_export_endpoint():
    """2. 验证 POST /api/session/calendar/export 直接导出端点"""
    client = TestClient(app)
    resp = client.post(
        "/api/session/calendar/export",
        json={
            "plan": SAMPLE_PLAN,
            "city": "北京",
            "calendar_title": "北京金秋二日游",
        },
    )
    assert resp.status_code == 200
    from urllib.parse import unquote
    assert "attachment" in resp.headers.get("content-disposition", "")
    assert "北京_calendar.ics" in unquote(resp.headers.get("content-disposition", ""))

    content = resp.text
    assert "BEGIN:VCALENDAR" in content
    assert "故宫博物院" in content


def test_api_session_calendar_download_endpoint():
    """3. 验证 GET /api/session/{session_id}/calendar.ics 会话持久化导出端点"""
    session_id = "test_sess_cal_123"
    harness_session_store.update(
        session_id=session_id,
        user_id="test_user",
        current_plan=SAMPLE_PLAN,
    )

    client = TestClient(app)
    resp = client.get(
        f"/api/session/{session_id}/calendar.ics",
        headers={"X-User-Id": "test_user"},
    )
    assert resp.status_code == 200
    assert "text/calendar" in resp.headers.get("content-type", "")
    assert "BEGIN:VCALENDAR" in resp.text
    assert "王府井希尔顿酒店" in resp.text

    # 跨租户访问防御 (IDOR 鉴权)
    forbidden_resp = client.get(
        f"/api/session/{session_id}/calendar.ics",
        headers={"X-User-Id": "malicious_hacker"},
    )
    assert forbidden_resp.status_code == 403
