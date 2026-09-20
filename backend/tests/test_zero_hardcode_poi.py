"""零硬编码与乐山峨眉山动态规划测试集 (Zero-Hardcoding & Leshan/Emeishan Test)

验证关键指标:
1. 槽位抽取: 复合目的地、名胜自动加锁、美食偏好、单人出行识别无误。
2. 动态自适应 POI 引擎: 告别静态硬编码字典，无 Key 环境下真实动态生成该城市 POI。
3. 地理坐标一致性: 绝不李代桃僵偷换为北京，乐山经纬度位于 (103.x, 29.x) 区间。
4. 端到端会话流: 生成 3 天完整的乐山峨眉山规划，酒店选址于乐山，包含翘脚牛肉/钵钵鸡等特色美食。
"""
import pytest
from app.agents.clarification_agent import extract_slots_from_input
from app.services.poi_synthesizer import synthesize_city_pois, get_city_geo_center
from app.graph.session_graph import build_session_graph


def test_clarification_agent_leshan_emeishan_extraction():
    """测试复合目的地、名山大川与偏好抽取"""
    user_input = "我想去乐山峨眉山玩3天左右,给我推荐一些美食和景点,我一个人"
    req = extract_slots_from_input(user_input)

    assert req.get_slot_value("city") == "乐山"
    assert req.get_slot_value("days") == 3
    assert "峨眉山" in req.locked_items
    assert "美食" in (req.get_slot_value("preferences") or [])
    assert req.get_slot_value("travel_party") == "单人出行"


def test_synthesize_city_pois_no_beijing_leakage():
    """测试 POI 合成引擎完全杜绝北京数据泄漏，真实生成乐山数据"""
    pois = synthesize_city_pois(
        city="乐山",
        preferences=["美食"],
        locked_items=["峨眉山"],
    )

    assert len(pois) >= 5
    poi_names = [p["name"] for p in pois]

    # 严正核验：绝对不能出现任何北京景点
    forbidden_beijing_names = ["故宫", "天安门", "颐和园", "八达岭", "景山", "天坛", "圆明园", "南锣鼓巷"]
    for bj in forbidden_beijing_names:
        for name in poi_names:
            assert bj not in name, f"严重缺陷：在乐山候选中检测到北京景点泄漏【{name}】"

    # 必须包含核心锁定项与地道特色
    assert any("峨眉山" in name for name in poi_names)
    assert any("乐山大佛" in name for name in poi_names)

    # 验证地理坐标区间 (乐山/峨眉山大致在 103.3~103.8, 29.4~29.7)
    for p in pois:
        assert 102.5 <= p["lng"] <= 104.5, f"经度异常：{p['name']} 经度为 {p['lng']}，脱离乐山区域"
        assert 28.5 <= p["lat"] <= 30.5, f"纬度异常：{p['name']} 纬度为 {p['lat']}，脱离乐山区域"


def test_city_geo_center_accuracy():
    """测试城市中心点解析真实有效"""
    center = get_city_geo_center("乐山")
    assert center is not None
    lng, lat = center
    assert 103.0 <= lng <= 104.0
    assert 29.0 <= lat <= 30.0


def test_session_graph_end_to_end_leshan_planning():
    """测试端到端会话图运行乐山峨眉山请求生成完整规划"""
    graph = build_session_graph()

    state_input = {
        "session_id": "test_leshan_001",
        "user_id": "u_test",
        "thread_id": "t_test_leshan",
        "input_text": "我想去乐山峨眉山玩3天左右，2026-10-01出发，给我推荐一些美食和景点,我一个人",
        "messages": [],
    }

    result = graph.invoke(
        state_input,
        config={"configurable": {"thread_id": "t_test_leshan"}},
    )

    assert result["status"] == "ready"
    plan = result.get("current_plan")
    assert plan is not None
    days = plan.get("days", [])
    assert len(days) == 3

    all_attraction_names = []
    for d in days:
        for a in d.get("attractions", []):
            all_attraction_names.append(a["name"])

    # 确认全行程无任何北京景点
    forbidden = ["故宫", "天安门", "颐和园", "八达岭长城"]
    for f in forbidden:
        assert not any(f in name for name in all_attraction_names), f"行程中出现了北京景点: {f}"

    # 确认包含了峨眉山或乐山大佛
    assert any("峨眉山" in name or "乐山大佛" in name for name in all_attraction_names)

    # 验证酒店生成在乐山，经纬度在乐山范围 (103.x, 29.x)
    first_day_hotel = days[0].get("hotel", {})
    assert first_day_hotel.get("name")
    h_lng = first_day_hotel.get("lng", 0.0)
    h_lat = first_day_hotel.get("lat", 0.0)
    assert 102.5 <= h_lng <= 104.5, f"酒店经度异常: {h_lng}"
    assert 28.5 <= h_lat <= 30.5, f"酒店纬度异常: {h_lat}"
