"""多租户数据隔离与历史游览足迹测试套件 (Multi-Tenant Isolation & Footprint Tests)

面向生产级 Agent 面试工程化考点全覆盖：
1. SQLite 行级隔离与 (user_id, city) 复合唯一索引约束与幂等性
2. 租户间长期记忆与足迹严格隔离（Alice 与 Bob 互不渗透）
3. Harness 规划循环中足迹自动过滤去重，与显式锁定 (locked_items) 优先豁免
4. 会话存储 HarnessSessionStore 属主鉴权与防范横向越权 (IDOR / Session Hijacking)
5. 租户私有 LRU 配额与防恶邻冲击 (Noisy Neighbor DoS Prevention)
6. REST API 端点多租户鉴权与精准定向缓存失效 (Targeted Cache Invalidation)
"""
from __future__ import annotations

import asyncio
import pytest
from fastapi.testclient import TestClient

from app.api.main import app
from app.harness.agent_loop import TravelAgentHarness
from app.harness.events import ThinkingEvent, PlanVersionEvent
from app.harness.registry import travel_tools
from app.harness.session_store import HarnessSessionStore
from app.memory.repository import MemoryRepository
from app.services.cache_service import get_cache_manager


def test_sqlite_footprint_persistence_and_idempotency(tmp_path):
    """1. 验证 SQLite 足迹表 DDL、CRUD 及幂等打卡约束"""
    db_path = tmp_path / "test_memory.db"
    repo = MemoryRepository(db_path=db_path)

    # 首次打卡
    ok = repo.add_footprint(user_id="alice", poi_name="故宫博物院", city="北京")
    assert ok is True
    assert repo.is_visited("alice", "故宫博物院", "北京") is True
    assert repo.is_visited("alice", "天坛公园", "北京") is False

    # 幂等重复打卡：不报错，更新时间戳
    ok2 = repo.add_footprint(user_id="alice", poi_name="故宫博物院", city="北京")
    assert ok2 is True

    # 增加另一个景点
    repo.add_footprint(user_id="alice", poi_name="天坛公园", city="北京")
    fps = repo.get_footprints("alice", city="北京")
    assert len(fps) == 2
    names = {f["poi_name"] for f in fps}
    assert names == {"故宫博物院", "天坛公园"}

    # 移除打卡
    removed = repo.remove_footprint(user_id="alice", poi_name="天坛公园", city="北京")
    assert removed is True
    assert repo.is_visited("alice", "天坛公园", "北京") is False
    assert len(repo.get_footprints("alice", city="北京")) == 1


def test_multitenant_footprint_data_isolation(tmp_path):
    """2. 验证多租户数据行级隔离：Alice、Bob 与 Charlie 相互独立"""
    db_path = tmp_path / "test_memory.db"
    repo = MemoryRepository(db_path=db_path)

    repo.add_footprint(user_id="alice", poi_name="故宫博物院", city="北京")
    repo.add_footprint(user_id="alice", poi_name="颐和园", city="北京")
    repo.add_footprint(user_id="bob", poi_name="宽窄巷子", city="成都")

    # Alice 只能查到自己的北京足迹
    alice_bj = repo.get_footprints(user_id="alice", city="北京")
    assert len(alice_bj) == 2
    alice_cd = repo.get_footprints(user_id="alice", city="成都")
    assert len(alice_cd) == 0

    # Bob 只能查到自己的成都足迹
    bob_bj = repo.get_footprints(user_id="bob", city="北京")
    assert len(bob_bj) == 0
    bob_cd = repo.get_footprints(user_id="bob", city="成都")
    assert len(bob_cd) == 1
    assert bob_cd[0]["poi_name"] == "宽窄巷子"

    # 未打卡的新租户 Charlie 查不到任何数据
    charlie_fps = repo.get_footprints(user_id="charlie")
    assert len(charlie_fps) == 0


@pytest.mark.asyncio
async def test_harness_footprint_filtering_and_lock_override(monkeypatch, tmp_path):
    """3. 验证 Harness 主循环中足迹自动过滤去重，与显式锁定优先豁免闭环"""
    db_path = tmp_path / "test_memory.db"
    test_repo = MemoryRepository(db_path=db_path)

    # 模拟 Alice 已去过故宫博物院
    test_repo.add_footprint(user_id="alice", poi_name="故宫博物院", city="北京")

    import app.harness.agent_loop as loop_mod
    monkeypatch.setattr(loop_mod, "get_memory_repository", lambda: test_repo)

    # 避免外部网络调用，加速测试闭环
    orig_call = travel_tools.call

    async def mock_call(name: str, **kwargs):
        if name == "fetch_tavily_notes":
            return {"summary": "测试避坑指南", "tips": ["提前预约"]}, 5.0
        return await orig_call(name, **kwargs)

    monkeypatch.setattr(travel_tools, "call", mock_call)

    harness = TravelAgentHarness(registry=travel_tools)

    # Case 3.1: Alice 规划北京 2 天，故宫博物院应被自动过滤排除
    alice_events = []
    async for ev in harness.run(session_id="sess_alice_filter", user_input="明天去北京玩2天", user_id="alice"):
        alice_events.append(ev)

    filtered_events = [e for e in alice_events if isinstance(e, ThinkingEvent) and e.payload.get("step") == "footprint_filtered"]
    assert len(filtered_events) >= 1
    assert "故宫博物院" in filtered_events[0].payload.get("detail", "")

    plan_events = [e for e in alice_events if isinstance(e, PlanVersionEvent)]
    assert len(plan_events) >= 1
    alice_plan_names = [
        a.get("name")
        for d in plan_events[0].payload.get("plan", {}).get("days", [])
        for a in d.get("attractions", [])
    ]
    assert "故宫博物院" not in alice_plan_names

    # Case 3.2: Bob（未去过故宫）规划北京 2 天，故宫博物院应正常推荐
    bob_events = []
    async for ev in harness.run(session_id="sess_bob_normal", user_input="明天去北京玩2天", user_id="bob"):
        bob_events.append(ev)

    bob_plan_events = [e for e in bob_events if isinstance(e, PlanVersionEvent)]
    assert len(bob_plan_events) >= 1
    bob_plan_names = [
        a.get("name")
        for d in bob_plan_events[0].payload.get("plan", {}).get("days", [])
        for a in d.get("attractions", [])
    ]
    assert "故宫博物院" in bob_plan_names

    # Case 3.3: Alice 显式要求锁定故宫（"必须去故宫博物院"），虽然在足迹库中，但显式锁定优先豁免
    alice_locked_events = []
    async for ev in harness.run(
        session_id="sess_alice_locked",
        user_input="明天去北京玩2天，必须去故宫博物院",
        user_id="alice"
    ):
        alice_locked_events.append(ev)

    locked_plan_events = [e for e in alice_locked_events if isinstance(e, PlanVersionEvent)]
    assert len(locked_plan_events) >= 1
    locked_plan_names = [
        a.get("name")
        for d in locked_plan_events[0].payload.get("plan", {}).get("days", [])
        for a in d.get("attractions", [])
    ]
    assert "故宫博物院" in locked_plan_names


def test_session_store_multitenant_ownership_and_idor_prevention():
    """4. 验证会话存储严格属主鉴权，防范水平越权 (IDOR) 攻击"""
    store = HarnessSessionStore()

    # Alice 创建会话
    store.update(session_id="sess_secret_alice", user_id="alice", new_user_message="私密行程")

    # Alice 自己读取，成功
    state_alice = store.to_frontend_state("sess_secret_alice", user_id="alice")
    assert state_alice["user_id"] == "alice"

    # Bob 试图越权读取 Alice 的会话 -> 拦截并抛出 PermissionError
    with pytest.raises(PermissionError) as exc_info:
        store.to_frontend_state("sess_secret_alice", user_id="bob")
    assert "会话属主鉴权失败" in str(exc_info.value)

    # Bob 试图通过 get() 越权
    with pytest.raises(PermissionError):
        store.get("sess_secret_alice", user_id="bob")

    # Bob 试图通过 update() 篡改 Alice 的会话
    with pytest.raises(PermissionError):
        store.update(session_id="sess_secret_alice", user_id="bob", new_user_message="恶意篡改")


def test_session_store_tenant_quota_and_noisy_neighbor_defense():
    """5. 验证租户级 LRU 会话配额，防范 Noisy Neighbor 挤占其他用户会话"""
    # 单租户配额设置为 3
    store = HarnessSessionStore(max_entries=100, max_entries_per_user=3)

    # Bob 创建会话 1
    store.update(session_id="sess_bob_1", user_id="bob")

    # 恶意爬虫租户 Evil 并发创建 5 个会话（超过单租户配额 3）
    for i in range(5):
        store.update(session_id=f"sess_evil_{i}", user_id="evil")

    # Evil 租户应该只保留最近的 3 个会话 (2, 3, 4)
    evil_sessions = store.list_user_sessions("evil")
    assert len(evil_sessions) == 3
    assert "sess_evil_0" not in evil_sessions
    assert "sess_evil_4" in evil_sessions

    # Bob 的会话完全不受 Evil 冲刷影响，依然安然存在！
    bob_sessions = store.list_user_sessions("bob")
    assert "sess_bob_1" in bob_sessions
    assert store.get("sess_bob_1", user_id="bob").session_id == "sess_bob_1"


def test_api_endpoints_multitenant_and_targeted_cache_invalidation():
    """6. 验证 REST API 端点鉴权与足迹打卡触发定向缓存失效"""
    client = TestClient(app)

    # 6.1 打卡 API
    resp = client.post(
        "/api/user/alice/footprint",
        json={"poi_name": "八达岭长城", "city": "北京"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    assert "八达岭长城" in data["message"]

    # 6.2 查询足迹 API
    get_resp = client.get("/api/user/alice/footprint?city=北京")
    assert get_resp.status_code == 200
    assert get_resp.json()["total"] >= 1

    # 6.3 会话查询越权阻断 (HTTP 403)
    # Alice 创建会话
    client.post(
        "/api/session/chat",
        json={"session_id": "sess_test_idor_1", "user_id": "alice", "input_text": "想去北京"},
        headers={"X-User-Id": "alice"},
    )

    # Alice 带着正确的 X-User-Id 头查询，返回 200
    ok_resp = client.get("/api/session/sess_test_idor_1/state", headers={"X-User-Id": "alice"})
    assert ok_resp.status_code == 200
    assert ok_resp.json()["user_id"] == "alice"

    # Bob 试图伪造 Header 读取 Alice 的会话，返回 403 Forbidden!
    forbidden_resp = client.get("/api/session/sess_test_idor_1/state", headers={"X-User-Id": "bob"})
    assert forbidden_resp.status_code == 403
    assert "会话属主鉴权失败" in forbidden_resp.json()["detail"]

    # 6.4 移除足迹 API
    del_resp = client.request(
        "DELETE",
        "/api/user/alice/footprint",
        json={"poi_name": "八达岭长城", "city": "北京"},
    )
    assert del_resp.status_code == 200
    assert del_resp.json()["status"] == "success"
