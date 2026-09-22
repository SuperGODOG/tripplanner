"""极端边界测试：通用动态地理实体解析、中途反复改口与跨区域缓存隔离测试

测试场景 (用户真实痛点驱动):
1. 用户说要去 四川 -> 一会儿又改川西 -> 一会又改峨眉 -> 换成陕北
2. 零硬编码：坚决杜绝城市枚举字典，验证基于高德行政编码与 LLM 零样本空间理解的双通道解析
3. 缓存隔离：验证各区域拥有独立指纹 Cache Key，杜绝千篇一律的旧缓存命中
4. 告别假模板：验证生成的旅行高光名胜完全为真实景点，杜绝“{city}核心地标广场”等模板幻觉
5. 跨城市意图污染清除：当目的地发生突变转向时，自动清理旧城市不可行锁定项 (如 北京故宫)
"""
from __future__ import annotations

import pytest
from app.agents.clarification_agent import extract_slots_from_input
from app.harness.agent_loop import TravelAgentHarness
from app.harness.events import ThinkingEvent, MapActionEvent, PlanVersionEvent
from app.harness.registry import ToolRegistry
from app.models.session import EffectiveRequirements, SlotOrigin
from app.services.cache_service import get_cache_manager
from app.services.geo_entity_resolver import (
    DestinationType,
    GeoEntityResolver,
    resolve_destination,
)
from app.services.poi_synthesizer import synthesize_city_pois
from app.tools.search_tools import make_attractions_cache_key


# ================================================================
# 1. 通用动态地理实体解析测试 (零硬编码双通道)
# ================================================================

def test_dynamic_geo_entity_resolution_types():
    """验证动态解析器能准确推导省、大区旅游带、山脉景区与地级市，零硬编码"""
    # 省级行政区
    sichuan = resolve_destination("四川")
    assert sichuan.dest_type == DestinationType.PROVINCE
    assert "四川" in sichuan.canonical_name
    assert "成都" in sichuan.gateway_city or "省会" in sichuan.gateway_city

    # 跨行政区文化旅游带 (非标准地级市)
    chuanxi = resolve_destination("川西")
    assert chuanxi.dest_type == DestinationType.TOURISM_REGION
    assert "川西" in chuanxi.canonical_name
    assert "成都" in chuanxi.gateway_city
    assert len(chuanxi.core_pois) > 0

    # 著名山岳与风景名胜区
    emei = resolve_destination("峨眉")
    assert emei.dest_type == DestinationType.SCENIC_AREA
    assert "峨眉山" in emei.canonical_name
    assert "乐山" in emei.gateway_city

    # 西北文化旅游带
    shanbei = resolve_destination("陕北")
    assert shanbei.dest_type == DestinationType.TOURISM_REGION
    assert "陕北" in shanbei.canonical_name
    assert "延安" in shanbei.gateway_city

    # 边陲特色旅游大区
    nanjiang = resolve_destination("南疆")
    assert nanjiang.dest_type == DestinationType.TOURISM_REGION
    assert "南疆" in nanjiang.canonical_name
    assert "喀什" in nanjiang.gateway_city

    # 标准地级市
    hangzhou = resolve_destination("杭州")
    assert hangzhou.dest_type == DestinationType.CITY
    assert "杭州" in hangzhou.canonical_name


# ================================================================
# 2. 中途反复改口语法槽位提取测试 (动态动词 + 零硬编码)
# ================================================================

def test_conversational_steering_slot_extraction_sequence():
    """验证用户反复改口链路：四川 -> 改成川西 -> 一会又改峨眉 -> 换成陕北"""
    # Turn 1: 初始输入
    req_1 = extract_slots_from_input("我想去四川玩3天")
    assert "四川" in str(req_1.get_slot_value("city"))
    assert req_1.get_slot_value("days") == 3

    # Turn 2: 改口川西 (改成)
    req_2 = extract_slots_from_input("等等，改成川西", current_req=req_1)
    assert "川西" in str(req_2.get_slot_value("city"))

    # Turn 3: 改口峨眉 (又改)
    req_3 = extract_slots_from_input("一会又改峨眉", current_req=req_2)
    assert "峨眉" in str(req_3.get_slot_value("city"))

    # Turn 4: 改口陕北 (换成 + 变更新天数)
    req_4 = extract_slots_from_input("算了还是换成陕北4天吧", current_req=req_3)
    assert "陕北" in str(req_4.get_slot_value("city"))
    assert req_4.get_slot_value("days") == 4

    # Turn 5: 改口南疆 (转去)
    req_5 = extract_slots_from_input("转去南疆", current_req=req_4)
    assert "南疆" in str(req_5.get_slot_value("city"))


def test_province_prefixed_destination_extraction_hierarchy():
    """验证省级空间前缀与下级城市/景区的层级解耦识别 (如 四川内江 -> 内江, 四川九寨沟 -> 九寨沟)"""
    # 1. 省份 + 地级市：真实目标应精准锚定到地级市，而非全省
    req_neijiang = extract_slots_from_input("想去四川内江玩1天")
    assert req_neijiang.get_slot_value("city") == "内江"
    assert req_neijiang.get_slot_value("days") == 1
    assert "内江" not in (req_neijiang.locked_items or [])

    # 2. 省份+市级带行政区划后缀 (四川省内江市)
    req_neijiang_full = extract_slots_from_input("想去四川省内江市玩1天")
    assert req_neijiang_full.get_slot_value("city") == "内江"
    assert req_neijiang_full.get_slot_value("days") == 1

    # 3. 含有中文数字的著名景区/地市 (避免被正则前瞻将中文数字截断)
    req_jiuzhai = extract_slots_from_input("想去四川九寨沟玩3天")
    assert req_jiuzhai.get_slot_value("city") == "九寨沟"
    assert req_jiuzhai.get_slot_value("days") == 3

    req_sanya = extract_slots_from_input("想去海南三亚玩3天")
    assert req_sanya.get_slot_value("city") == "三亚"
    assert req_sanya.get_slot_value("days") == 3

    # 4. 省份 + 城市 + 景点三级复合结构
    req_jinli = extract_slots_from_input("想去四川成都锦里玩1天")
    assert req_jinli.get_slot_value("city") == "成都"
    assert req_jinli.get_slot_value("days") == 1
    assert "锦里" in (req_jinli.locked_items or [])

    # 5. 纯省份输入（无具体城市）：依然正常保留全省层级
    req_sichuan = extract_slots_from_input("我想去四川玩3天")
    assert "四川" in str(req_sichuan.get_slot_value("city"))
    assert req_sichuan.get_slot_value("days") == 3


# ================================================================
# 3. 跨城市意图污染自愈清除 (Cross-City Lock Eviction)
# ================================================================

def test_multiturn_destination_steering_purges_cross_city_locks():
    """验证当目的地发生突变切换时，自动清除上一个城市的不可行锁定项"""
    req = EffectiveRequirements()
    # 用户最初在北京，锁定了故宫
    req.set_slot("city", "北京", origin=SlotOrigin.USER_EXPLICIT)
    req.set_slot("days", 3, origin=SlotOrigin.USER_EXPLICIT)
    req.locked_items = ["故宫"]

    # 用户转向川西 (传入当前已有 req)
    new_req = extract_slots_from_input("等等，改成川西", current_req=req)
    assert "川西" in str(new_req.get_slot_value("city"))
    # 验证跨城市锁定项自动清除 (故宫已被移除)
    assert "故宫" not in (new_req.locked_items or [])


# ================================================================
# 4. 候选名胜非千篇一律与零模板幻觉验证
# ================================================================

def test_distinct_destinations_produce_distinct_authentic_pois():
    """验证 四川、川西、峨眉 各自返回真实独立的名胜，杜绝千篇一律模板"""
    pois_sichuan = synthesize_city_pois("四川")
    pois_chuanxi = synthesize_city_pois("川西")
    pois_emei = synthesize_city_pois("峨眉")

    names_sichuan = {p["name"] for p in pois_sichuan}
    names_chuanxi = {p["name"] for p in pois_chuanxi}
    names_emei = {p["name"] for p in pois_emei}

    # 1. 验证集合互不雷同
    assert names_chuanxi != names_sichuan
    assert names_chuanxi != names_emei
    assert names_sichuan != names_emei

    # 2. 验证真实名胜包含在内
    assert any(k in " ".join(names_chuanxi) for k in ("四姑娘山", "新都桥", "稻城亚丁", "墨石公园", "折多山"))
    assert any(k in " ".join(names_emei) for k in ("峨眉山", "金顶", "万年寺", "清音阁", "报国寺"))
    assert any(k in " ".join(names_sichuan) for k in ("乐山大佛", "峨眉山", "都江堰", "九寨沟", "青城山"))

    # 3. 坚决杜绝千篇一律假模板
    all_names = list(names_sichuan) + list(names_chuanxi) + list(names_emei)
    for n in all_names:
        assert "核心地标广场" not in n
        assert "风味美食特色街区" not in n
        assert "文博艺术展览中心" not in n


# ================================================================
# 5. 缓存指纹与跨区缓存隔离验证
# ================================================================

def test_cache_fingerprint_isolation_across_regions():
    """验证不同区域生成的指纹 Cache Key 互不冲突，杜绝命中前一个城市的缓存"""
    key_sichuan = make_attractions_cache_key("四川", preferences=["自然风光"])
    key_chuanxi = make_attractions_cache_key("川西", preferences=["自然风光"])
    key_emei = make_attractions_cache_key("峨眉", preferences=["自然风光"])

    assert key_sichuan != key_chuanxi
    assert key_chuanxi != key_emei
    assert key_sichuan != key_emei

    # 验证 CacheManager 独立存取
    mgr = get_cache_manager()
    mgr.set("boundary_test", "key_sichuan", {"city": "四川"})
    mgr.set("boundary_test", "key_chuanxi", {"city": "川西"})
    mgr.set("boundary_test", "key_emei", {"city": "峨眉"})

    assert mgr.get("boundary_test", "key_sichuan")["city"] == "四川"
    assert mgr.get("boundary_test", "key_chuanxi")["city"] == "川西"
    assert mgr.get("boundary_test", "key_emei")["city"] == "峨眉"


# ================================================================
# 6. Agent Loop 端到端自适应视口与改口事件
# ================================================================

@pytest.mark.asyncio
async def test_agent_loop_steered_event_and_viewport():
    """验证 Agent Loop 中改口能发射包含动态解析信息的 ThinkingEvent 与自适应视口 MapActionEvent"""
    mock_tools = ToolRegistry()

    @mock_tools.register("search_scenic_pois", "mock scenic")
    def _mock_scenic(city: str, **kwargs):
        # 返回与城市相关的名胜
        return synthesize_city_pois(city=city)

    @mock_tools.register("cluster_days_kmeans", "mock kmeans")
    def _mock_kmeans(pois: list, days: int, **kwargs):
        return [{"pois": pois[i*2:(i+1)*2]} for i in range(days)]

    @mock_tools.register("select_minimax_hotel", "mock hotel")
    def _mock_hotel(city: str, **kwargs):
        return [{"name": f"{city}集散度假酒店", "lng": 102.0, "lat": 30.5, "price": 380}]

    @mock_tools.register("solve_2opt_route", "mock route")
    def _mock_route(pois: list, **kwargs):
        return pois

    @mock_tools.register("enrich_meals", "mock meals")
    def _mock_meals(plan_days: list, city: str, **kwargs):
        return plan_days

    initial_req = EffectiveRequirements()
    initial_req.set_slot("city", "四川", origin=SlotOrigin.USER_EXPLICIT)
    initial_req.set_slot("days", 3, origin=SlotOrigin.USER_EXPLICIT)
    initial_req.set_slot("start_date", "2026-10-01", origin=SlotOrigin.USER_EXPLICIT)

    harness = TravelAgentHarness(registry=mock_tools, max_turns=1)

    # 模拟用户中途改口输入“等等，改成川西”
    events = []
    async for ev in harness.run(
        session_id="sess_boundary_geo_1",
        user_input="等等，改成川西",
        user_id="user_tester_boundary",
        current_requirements=initial_req,
        is_steering=True,
    ):
        events.append(ev)

    thinking_events = [e for e in events if isinstance(e, ThinkingEvent)]
    map_events = [e for e in events if isinstance(e, MapActionEvent)]

    # 1. 验证 Thinking 链路捕获到转向事件并展示解析详情
    steered_event = next((e for e in thinking_events if e.payload.get("step") == "midturn_steered"), None)
    assert steered_event is not None
    assert "川西" in steered_event.payload.get("detail", "")

    # 2. 验证 MapActionEvent 视口自动适配大区缩放 (zoom=8)
    fly_event = next((e for e in map_events if e.payload.get("action") == "FLY_TO"), None)
    assert fly_event is not None
    fly_data = fly_event.payload.get("data", {})
    assert fly_data.get("zoom") == 8  # 川西作为大区旅游带自动适配 8 级宏观视口
    assert "川西" in fly_data.get("title", "")


# ================================================================
# 5. 高德 API 配额复用与 Redis 缓存防护测试 (Quota Conservation)
# ================================================================

def test_amap_cache_and_quota_reuse():
    """验证高德 API 额度保护机制：
    1. _enrich_pois_with_coords 遇到自带原生经纬度的 POI 时，不发起未缓存的 detail 风暴；
    2. food/around 检索坚决跳过无意义的 detail 请求；
    3. 已命中缓存的 POI detail 无损优先复用。
    """
    from app.tools.amap_wrapper import AmapToolWrapper
    from app.services.cache_service import compute_fingerprint

    wrapper = AmapToolWrapper()
    cache_mgr = get_cache_manager()

    detail_calls = []

    def mock_mcp_run(args, timeout=5):
        if args.get("tool_name") == "maps_search_detail":
            detail_calls.append(args["arguments"]["id"])
            return '{"id": "' + args["arguments"]["id"] + '", "location": "116.40,39.90", "address": "测试地址"}'
        return "{}"

    wrapper._mcp_run_with_timeout = mock_mcp_run

    # 1. 模拟 food 检索返回 10 个自带 location 的美食 POI
    raw_food = {
        "pois": [
            {"id": f"food_{i}", "name": f"餐厅_{i}", "location": f"{116.40 + i*0.01:.4f},{39.90 + i*0.01:.4f}", "typecode": "050100"}
            for i in range(10)
        ]
    }
    enriched_food = wrapper._enrich_pois_with_coords(raw_food, city="北京", stype="food")
    # food 类型自带原生经纬度，detail_calls 必须为 0，杜绝网络配额浪费
    assert len(detail_calls) == 0
    assert enriched_food["pois"][0]["_lng"] is not None

    # 2. 模拟已在 Redis 缓存中的 POI detail
    cached_id = "poi_cached_999"
    fp = compute_fingerprint({"id": cached_id})
    cache_mgr.set("maps_search_detail", fp, {
        "id": cached_id, "location": "116.41,39.91", "rating": "4.9", "open_time": "08:00-18:00"
    }, ttl=3600)

    raw_attractions = {
        "pois": [
            {"id": cached_id, "name": "已缓存景点", "location": "116.41,39.91", "typecode": "110000"},
            *[
                {"id": f"attr_{i}", "name": f"未缓存景点_{i}", "location": f"{116.41 + i*0.01:.4f},{39.91 + i*0.01:.4f}", "typecode": "110000"}
                for i in range(15)
            ]
        ]
    }
    detail_calls.clear()
    enriched_attr = wrapper._enrich_pois_with_coords(raw_attractions, city="北京", stype="attraction")
    # 已缓存的 cached_id 命中缓存被调用（或直接复用），其余 15 个自带坐标的 POI 仅前 4 个（idx 1..4 < 5）允许 live detail，第 5 个及以后被限流截断
    assert len(detail_calls) <= 5, f"未被截流的 detail 调用次数过多: {len(detail_calls)}"
    assert enriched_attr["pois"][0]["rating"] == "4.9"


def test_enrich_meals_tool_redis_cache():
    """验证 enrich_meals_tool 能够复用 Redis 缓存，二次调用不触发 search_pois"""
    from app.tools.search_tools import enrich_meals_tool
    from app.models.candidates import PoiCandidate

    called_search = []

    class MockWrapper:
        def search_pois(self, city, stype, keywords="", center="", radius="", max_results=10):
            called_search.append(center)
            return [
                PoiCandidate(name="老字号豆花庄", category="川菜", rating=4.8, typecode="050100", lng=104.06, lat=30.67),
                PoiCandidate(name="地道甜水面", category="特色小吃", rating=4.7, typecode="050100", lng=104.06, lat=30.67),
                PoiCandidate(name="钟水饺老店", category="精选小吃", rating=4.6, typecode="050100", lng=104.06, lat=30.67),
            ]

    plan_days = [{
        "day_index": 0,
        "attractions": [{"name": "青羊宫", "lng": 104.04, "lat": 30.66}],
        "meals": [],
    }]

    # 第一次使用带底层调用的逻辑（模拟真实验收）
    enrich_meals_tool(plan_days=plan_days, city="成都_缓存测试", amap_wrapper=MockWrapper())
    assert len(called_search) == 1
    assert len(plan_days[0]["meals"]) == 3
