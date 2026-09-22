"""高德天气与行程充实度专项测试 (Weather & Itinerary Enrichment Tests)"""
import pytest
from datetime import datetime, timedelta

from app.models.session import EffectiveRequirements, SlotOrigin
from app.agents.clarification_agent import (
    extract_slots_from_input,
    check_clarification_needed,
)
from app.tools.weather_tool import get_weather_for_date
from app.services.route_solver import solve_day_route_with_diagnostics, estimate_visit_minutes


def test_clarification_triggers_on_missing_start_date():
    """测试当城市与天数具备但缺少出发日期时，精确触发 start_date 意图澄清"""
    req = EffectiveRequirements()
    req.set_slot("city", "乐山", origin=SlotOrigin.USER_EXPLICIT)
    req.set_slot("days", 2, origin=SlotOrigin.USER_EXPLICIT)

    prompt = check_clarification_needed(req)
    assert prompt is not None
    assert prompt.missing_slots == ["start_date"]
    assert "出发" in prompt.prompt_text
    assert len(prompt.options) >= 3
    # 选项包含明天、周末等
    option_ids = [opt.option_id for opt in prompt.options]
    assert "date_tomorrow" in option_ids
    assert "date_weekend" in option_ids


def test_extract_slots_handles_relative_dates():
    """测试自然语言相对日期（明天/后天/本周末）直接抽取成功"""
    today = datetime.now().date()
    tomorrow_str = (today + timedelta(days=1)).strftime("%Y-%m-%d")

    # 1. 抽取“明天”
    text1 = "我想明天去乐山玩2天"
    req1 = extract_slots_from_input(text1)
    assert req1.get_slot_value("start_date") == tomorrow_str

    # 2. 抽取指定月日 “10月1日”
    text2 = "我想10月1日去北京玩3天"
    req2 = extract_slots_from_input(text2)
    assert req2.get_slot_value("start_date") == f"{today.year}-10-01"


def test_amap_weather_tool_parses_forecasts():
    """测试高德官方天气查询与穿衣出行贴士生成"""
    today_str = datetime.now().strftime("%Y-%m-%d")
    weather = get_weather_for_date("乐山", today_str)

    assert weather is not None
    assert "weather" in weather
    assert "temp_range" in weather
    assert "tip" in weather
    assert "source_label" in weather
    # 保证包含高德官方或气象指引标签
    assert any(k in weather["source_label"] for k in ("高德", "气象"))


def test_route_solver_maintains_3_to_4_attractions():
    """测试在 09:00-21:00 拓展时间窗与弹性压缩下，4 个合理景点不会被过度剪枝"""
    pois = [
        {"name": "乐山大佛", "lng": 103.771, "lat": 29.553, "level": "AAAAA"},
        {"name": "乌尤寺", "lng": 103.778, "lat": 29.542, "level": "AAAA"},
        {"name": "嘉定坊古街", "lng": 103.765, "lat": 29.560},
        {"name": "上中顺特色街区", "lng": 103.766, "lat": 29.565},
    ]

    res = solve_day_route_with_diagnostics(
        pois=pois,
        start_hour=9,
        close_hour=21,
        day_index=0,
        immutable_names=["乐山大佛"],
    )

    # 在 12 小时全景时间窗下，4 个相邻景点应 100% 容纳成功，绝不剪枝至 1 个
    assert res.success is True
    assert res.diagnostics is None
    assert len(res.route) >= 3
    # 验证时序递增
    arrive_mins = [node["arrive_min"] for node in res.route]
    assert arrive_mins == sorted(arrive_mins)


def test_poi_duration_estimation_hierarchy():
    """测试不同能级景点的分级游览时长估算"""
    # Grade A
    assert estimate_visit_minutes({"name": "峨眉山金顶", "level": "5A"}) == 180
    assert estimate_visit_minutes({"name": "乐山大佛", "level": "AAAAA"}) == 180
    # Grade B
    assert estimate_visit_minutes({"name": "万年寺"}) == 75
    assert estimate_visit_minutes({"name": "乐山市博物馆"}) == 75
    # Grade C
    assert estimate_visit_minutes({"name": "张公桥美食街"}) == 60
    assert estimate_visit_minutes({"name": "嘉州古城墙街区"}) == 60
