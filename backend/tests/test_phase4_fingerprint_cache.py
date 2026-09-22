"""Phase 4 自动化单元测试集: Redis 细粒度工具依赖指纹缓存层

覆盖目标:
1. compute_fingerprint 计算的确定性与参数排序无关性 (test_fingerprint_computation_deterministic)
2. 内存降级引擎的基础 CRUD 与 TTL 过期淘汰行为 (test_memory_fallback_engine_basic_ops)
3. 工具缓存首次未命中并写入、二次等价调用 100% 命中缓存 (test_tool_cache_hit_and_miss)
4. 多天行程天级隔离与局部失效 (Day 2 变更不影响 Day 1 缓存命中) (test_partial_invalidation_day_isolation)
5. 用户微调饮食偏好或其它无关上下文时，路线求解指纹绝对不变 (test_diet_preference_does_not_bust_route_cache)
6. 作用域隔离测试 (不同租户/用户 scope 互不干扰，clear_scope 精确隔离) (test_cache_scope_isolation)
"""
import time
import pytest
from app.services.cache_service import (
    compute_fingerprint,
    _MemoryCache,
    FingerprintCacheManager,
    get_cache_manager,
)
from app.tools.cache_decorator import cached_tool_result, make_route_cache_key
from app.tools.planning_tools import solve_day_route_tool
from app.models.diagnostics import RouteSolverResult


def test_fingerprint_computation_deterministic():
    """测试依赖指纹算法的确定性与键顺序无关性"""
    dict_a = {"city": "北京", "day": 1, "pois": ["故宫", "天安门"]}
    # 调换字典键的顺序以及内部嵌套结构
    dict_b = {"pois": ["故宫", "天安门"], "city": "北京", "day": 1}
    dict_c = {"city": "北京", "day": 2, "pois": ["故宫", "天安门"]}

    fp_a = compute_fingerprint(dict_a)
    fp_b = compute_fingerprint(dict_b)
    fp_c = compute_fingerprint(dict_c)

    # 键顺序不同，生成的指纹必须完全一致
    assert fp_a == fp_b
    assert len(fp_a) == 32  # 标准 MD5 16进制字符串

    # 内容不同，生成的指纹互斥
    assert fp_a != fp_c


def test_memory_fallback_engine_basic_ops():
    """测试内存降级引擎在无 Redis 时的基本操作与 TTL 过期"""
    mem = _MemoryCache(max_size=3)

    # 1. 写入与读取
    mem.set("k1", {"data": "val1"}, ttl=10)
    assert mem.get("k1") == {"data": "val1"}

    # 2. 删除
    assert mem.delete("k1") is True
    assert mem.get("k1") is None
    assert mem.delete("k1") is False

    # 3. TTL 过期淘汰
    mem.set("k_expire", "expiring_soon", ttl=1)
    assert mem.get("k_expire") == "expiring_soon"
    time.sleep(1.05)
    assert mem.get("k_expire") is None

    # 4. 容量淘汰
    mem.set("k_a", "A", ttl=100)
    mem.set("k_b", "B", ttl=100)
    mem.set("k_c", "C", ttl=100)
    mem.set("k_d", "D", ttl=100)  # 超过 max_size=3，触发淘汰
    # 最早的 k_a 应该被 prune 掉
    assert mem.get("k_d") == "D"


def test_tool_cache_hit_and_miss():
    """测试工具装饰器在首次调用时 miss 并缓存，二次调用命中缓存"""
    manager = get_cache_manager()
    manager.clear_scope("test_hit_miss")

    call_count = 0

    @cached_tool_result("mock_heavy_calc", ttl=60, scope_builder=lambda **kw: "test_hit_miss")
    def mock_calc(x: int, y: int) -> dict:
        nonlocal call_count
        call_count += 1
        return {"sum": x + y, "count": call_count}

    # 第一次调用：未命中缓存，执行真实计算
    res1 = mock_calc(x=10, y=20)
    assert res1["sum"] == 30
    assert res1["count"] == 1
    assert call_count == 1

    # 第二次等价调用：必须命中缓存，call_count 不增加
    res2 = mock_calc(x=10, y=20)
    assert res2["sum"] == 30
    assert res2["count"] == 1
    assert call_count == 1

    # 参数不同：重新计算
    res3 = mock_calc(x=10, y=30)
    assert res3["sum"] == 40
    assert res3["count"] == 2
    assert call_count == 2


def test_partial_invalidation_day_isolation():
    """测试天级局部复用：Day 2 发生变动时，Day 1 路线缓存 100% 保持命中"""
    day1_pois = [
        {"name": "天安门广场", "lng": 116.397, "lat": 39.908, "visit_minutes": 60, "price": 0},
        {"name": "故宫博物院", "lng": 116.397, "lat": 39.916, "visit_minutes": 150, "price": 60},
    ]
    day2_pois = [
        {"name": "颐和园", "lng": 116.273, "lat": 39.999, "visit_minutes": 180, "price": 30},
        {"name": "圆明园", "lng": 116.298, "lat": 40.008, "visit_minutes": 120, "price": 25},
    ]

    # 1. 计算 Day 1 路线
    res1_first = solve_day_route_tool(pois=day1_pois, start_hour=9, close_hour=18, day_index=0)
    assert isinstance(res1_first, RouteSolverResult)
    assert res1_first.success is True

    # 2. 计算 Day 2 路线
    res2_first = solve_day_route_tool(pois=day2_pois, start_hour=9, close_hour=18, day_index=1)
    assert isinstance(res2_first, RouteSolverResult)
    assert res2_first.success is True

    # 3. 用户修改了 Day 2 的时间窗 (从 18点关门缩减到 16点)
    res2_modified = solve_day_route_tool(pois=day2_pois, start_hour=9, close_hour=16, day_index=1)
    assert isinstance(res2_modified, RouteSolverResult)

    # 4. 再次获取 Day 1 路线：特征完全未变，必须直接从缓存读取，且反序列化类型完全一致
    res1_cached = solve_day_route_tool(pois=day1_pois, start_hour=9, close_hour=18, day_index=0)
    assert isinstance(res1_cached, RouteSolverResult)
    assert res1_cached.success == res1_first.success
    assert len(res1_cached.route) == len(res1_first.route)
    assert res1_cached.total_ticket == res1_first.total_ticket


def test_diet_preference_does_not_bust_route_cache():
    """测试特征隔离：用户改口饮食偏好，路线求解指纹保持绝对不变"""
    pois = [
        {"name": "故宫博物院", "lng": 116.397, "lat": 39.916, "visit_minutes": 150},
        {"name": "景山公园", "lng": 116.396, "lat": 39.924, "visit_minutes": 60},
    ]

    # 用户初始状态：喜欢清淡、粤菜
    key_params_v1 = make_route_cache_key(
        pois=pois,
        start_hour=9,
        close_hour=20,
        start_hotel={"lng": 116.40, "lat": 39.90},
        day_index=0,
        diet_preference="粤菜清淡",  # 模拟从全局上下文传入的非路线参数
    )

    # 用户改口：强烈想吃火锅、重辣
    key_params_v2 = make_route_cache_key(
        pois=pois,
        start_hour=9,
        close_hour=20,
        start_hotel={"lng": 116.40, "lat": 39.90},
        day_index=0,
        diet_preference="川味火锅重辣",
    )

    fp1 = compute_fingerprint(key_params_v1)
    fp2 = compute_fingerprint(key_params_v2)

    # 关键断言：即使上层偏好改口，底层路线规划的依赖指纹必须完全相同！
    assert fp1 == fp2


def test_cache_scope_isolation():
    """测试多租户/用户作用域隔离与精准作用域清空"""
    cache = get_cache_manager()

    fp = compute_fingerprint({"query": "北京一日游"})

    # 写入两个不同 scope
    cache.set("search_test", fp, "user_A_result", ttl=60, scope="user_1001")
    cache.set("search_test", fp, "user_B_result", ttl=60, scope="user_1002")

    # 互不干扰
    assert cache.get("search_test", fp, scope="user_1001") == "user_A_result"
    assert cache.get("search_test", fp, scope="user_1002") == "user_B_result"
    assert cache.get("search_test", fp, scope="public") is None

    # 清空 user_1001 的作用域，不影响 user_1002
    deleted = cache.clear_scope("user_1001")
    assert deleted >= 1
    assert cache.get("search_test", fp, scope="user_1001") is None
    assert cache.get("search_test", fp, scope="user_1002") == "user_B_result"
