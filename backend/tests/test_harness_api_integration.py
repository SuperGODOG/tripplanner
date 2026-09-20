"""Harness API 端到端集成测试 (Harness API & SSE Streaming Integration Tests)"""
import json
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from app.api.main import app
from app.harness.registry import ToolRegistry


client = TestClient(app)


def test_get_harness_tools():
    """验证 GET /api/harness/tools 能够列出全部契约工具"""
    resp = client.get("/api/harness/tools")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["total"] >= 6
    tool_names = [t["name"] for t in data["tools"]]
    assert "search_scenic_pois" in tool_names
    assert "cluster_days_kmeans" in tool_names
    assert "select_minimax_hotel" in tool_names
    assert "solve_2opt_route" in tool_names
    assert "enrich_meals" in tool_names
    assert "fetch_tavily_notes" in tool_names


def test_harness_stream_endpoint_flow():
    """验证 POST /api/harness/stream 能够产生标准的 SSE 事件流"""
    # 构造 Fake 工具数据
    mock_reg = ToolRegistry()

    @mock_reg.register("search_scenic_pois", "mock")
    def _m1(city, preferences=None):
        return [
            {"name": f"{city}名胜1", "lng": 104.0, "lat": 30.0, "category": "风景名胜", "typecode": "110200", "price": 50},
            {"name": f"{city}名胜2", "lng": 104.05, "lat": 30.05, "category": "风景名胜", "typecode": "110200", "price": 40},
        ]

    @mock_reg.register("cluster_days_kmeans", "mock")
    def _m2(pois, days):
        return [{"day_index": 0, "pois": pois}]

    @mock_reg.register("select_minimax_hotel", "mock")
    def _m3(city, attraction_coords):
        return {"hotel_selected": {"name": "中心精选酒店", "price": 300}}

    @mock_reg.register("solve_2opt_route", "mock")
    def _m4(pois):
        class Res:
            route = [{"name": p["name"], "arrive_time": "09:00", "depart_time": "11:00", "distance_km": 1.5} for p in pois]
            total_ticket = 90.0
        return Res()

    @mock_reg.register("enrich_meals", "mock")
    def _m5(plan_days, city, food_preferences=None):
        for d in plan_days:
            d["meals"] = [
                {"type": "breakfast", "name": "特色早茶", "rating": 4.5},
                {"type": "lunch", "name": "老字号川菜", "rating": 4.7},
                {"type": "dinner", "name": "地道火锅", "rating": 4.8},
            ]
        return plan_days

    @mock_reg.register("fetch_tavily_notes", "mock")
    def _m6(city, poi_name):
        return {"booking_policy": "提前一天预约", "tips": ["早起排队少"], "summary": "必游名胜"}

    with patch("app.api.harness_api.travel_tools", mock_reg):
        resp = client.post(
            "/api/harness/stream",
            json={
                "session_id": "test_session_sse",
                "user_id": "tester_1",
                "input_text": "想去成都玩1天，喜欢历史文化和火锅",
            },
        )
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers["content-type"]

        body_text = resp.text
        # 验证产生了标准的 SSE 协议事件
        assert "event: thinking" in body_text
        assert "event: tool_start" in body_text
        assert "event: tool_end" in body_text
        assert "event: plan_version" in body_text
        assert "event: message_delta" in body_text
        assert "event: done" in body_text

        # 验证携带了真实的内容数据
        assert "成都" in body_text
        assert "中心精选酒店" in body_text
        assert "test_session_sse" in body_text
