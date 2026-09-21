"""Phase C 生活方式体温画像与伴随式主动关怀自动化测试 (Lifestyle & Companion Care Tests)"""
import pytest
from fastapi.testclient import TestClient

from app.api.main import app
from app.memory.repository import get_memory_repository, MemoryRepository
from app.harness.agent_loop import TravelAgentHarness
from app.harness.registry import ToolRegistry
from app.harness.events import ThinkingEvent, PlanVersionEvent, MessageDeltaEvent


client = TestClient(app)


def test_lifestyle_repository_crud_and_seeding(tmp_path):
    """验证生活方式体温画像的 SQLite 持久化与租户种子自愈"""
    repo = MemoryRepository(db_path=tmp_path / "test_lifestyle.db")

    # 1. 验证 Alice 预置画像：松弛晚起 (10:30)、6km 限制
    alice_p = repo.get_lifestyle("alice_explorer")
    assert alice_p["user_id"] == "alice_explorer"
    assert alice_p["travel_pace"] == "relaxed"
    assert alice_p["morning_person"] is False
    assert alice_p["daily_walking_limit_km"] == 6.0
    assert alice_p["companion_type"] == "solo"

    # 2. 验证 Bob 预置画像：晨起早游 (08:30)、12km 充沛
    bob_p = repo.get_lifestyle("bob_foodie")
    assert bob_p["user_id"] == "bob_foodie"
    assert bob_p["travel_pace"] == "intense"
    assert bob_p["morning_person"] is True
    assert bob_p["daily_walking_limit_km"] == 12.0
    assert bob_p["companion_type"] == "family_with_kids"

    # 3. 验证原子更新与差量合并
    updated = repo.update_lifestyle("alice_explorer", {
        "daily_walking_limit_km": 7.5,
        "companion_type": "couple",
    })
    assert updated["daily_walking_limit_km"] == 7.5
    assert updated["companion_type"] == "couple"
    assert updated["travel_pace"] == "relaxed"  # 未受影响的字段保持不变


def test_lifestyle_rest_api_endpoints():
    """验证生活方式 REST API 端点与定向缓存失效"""
    # 1. GET 读取
    resp = client.get("/api/user/bob_foodie/lifestyle")
    assert resp.status_code == 200
    data = resp.json()
    assert data["user_id"] == "bob_foodie"

    # 2. PUT 更新
    put_resp = client.put(
        "/api/user/bob_foodie/lifestyle",
        json={
            "daily_walking_limit_km": 11.5,
            "special_needs": ["kid_friendly", "night_market"],
        },
    )
    assert put_resp.status_code == 200
    res_json = put_resp.json()
    assert res_json["status"] == "success"
    assert res_json["lifestyle"]["daily_walking_limit_km"] == 11.5
    assert "cache_invalidated" in res_json

    # 恢复 Bob
    client.put(
        "/api/user/bob_foodie/lifestyle",
        json={"daily_walking_limit_km": 12.0},
    )


@pytest.mark.asyncio
async def test_harness_loop_lifestyle_adaptive_scheduling():
    """验证 Harness 主循环结合生活方式画像执行自适应时序与体温关怀注入"""
    mock_reg = ToolRegistry()

    @mock_reg.register("search_scenic_pois", "mock")
    def _m1(city, preferences=None):
        return [
            {"name": f"{city}名胜1", "lng": 116.40, "lat": 39.90, "category": "名胜古迹", "typecode": "110000", "price": 40},
            {"name": f"{city}名胜2", "lng": 116.42, "lat": 39.92, "category": "名胜古迹", "typecode": "110000", "price": 50},
        ]

    @mock_reg.register("cluster_days_kmeans", "mock")
    def _m2(pois, days):
        return [{"day_index": 0, "pois": pois}]

    @mock_reg.register("select_minimax_hotel", "mock")
    def _m3(city, attraction_coords):
        return {"hotel_selected": {"name": "中心商圈酒店", "lng": 116.41, "lat": 39.91}}

    @mock_reg.register("solve_2opt_route", "mock")
    def _m4(pois):
        class Res:
            route = [
                {"name": pois[0]["name"], "distance_km": 1.5, "poi": pois[0]},
                {"name": pois[1]["name"], "distance_km": 2.0, "poi": pois[1]},
            ]
            total_ticket = 90.0
        return Res()

    @mock_reg.register("enrich_meals", "mock")
    def _m5(plan_days, city, food_preferences=None):
        for d in plan_days:
            d["meals"] = [
                {"type": "breakfast", "name": "特色早茶", "rating": 4.6},
                {"type": "lunch", "name": "本帮菜午餐", "rating": 4.7},
                {"type": "dinner", "name": "风味晚餐", "rating": 4.8},
            ]
        return plan_days

    @mock_reg.register("fetch_tavily_notes", "mock")
    def _m6(city, poi_name):
        return {"booking_policy": "现场购票", "tips": ["注意防晒"], "summary": "名胜"}

    harness = TravelAgentHarness(registry=mock_reg)

    # 1. 模拟 Alice (松弛晚起) -> 首站应为 10:30
    alice_events = []
    async for ev in harness.run("sess_alice_lifestyle", "2026-09-21去北京玩1天", user_id="alice_explorer"):
        alice_events.append(ev)

    thinking_details = [e.payload.get("detail", "") for e in alice_events if isinstance(e, ThinkingEvent)]
    assert any("体温画像" in d and "松弛晚起" in d for d in thinking_details)

    plan_events = [e for e in alice_events if isinstance(e, PlanVersionEvent)]
    assert len(plan_events) == 1
    alice_plan = plan_events[0].payload["plan"]
    assert "lifestyle_care" in alice_plan
    assert "松弛" in alice_plan["lifestyle_care"]
    # 验证首站自适应延后至 10:30
    assert alice_plan["days"][0]["attractions"][0]["arrive_time"] == "10:30"
    # 验证每日徒步负荷 telemetry
    assert "telemetry" in alice_plan["days"][0]
    assert alice_plan["days"][0]["telemetry"]["walking_limit_km"] == 6.0

    # 验证输出的正文中包含 Pi 伴随式体温关怀
    delta_events = [e for e in alice_events if isinstance(e, MessageDeltaEvent)]
    assert any("Pi 伴随式体温关怀" in e.payload.get("delta", "") for e in delta_events)

    # 2. 模拟 Bob (晨起早游) -> 首站应为 08:30
    bob_events = []
    async for ev in harness.run("sess_bob_lifestyle", "2026-09-21去北京玩1天", user_id="bob_foodie"):
        bob_events.append(ev)

    bob_plans = [e for e in bob_events if isinstance(e, PlanVersionEvent)]
    assert len(bob_plans) == 1
    bob_plan = bob_plans[0].payload["plan"]
    # 验证首站自适应为 08:30 早起时段
    assert bob_plan["days"][0]["attractions"][0]["arrive_time"] == "08:30"
    assert bob_plan["days"][0]["telemetry"]["walking_limit_km"] == 11.5 or bob_plan["days"][0]["telemetry"]["walking_limit_km"] == 12.0
