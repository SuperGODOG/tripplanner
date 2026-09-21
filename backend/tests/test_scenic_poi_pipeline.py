"""风景名胜与商业场景严格物理隔离专项测试 (Scenic vs Commercial Isolation Test)

验证核心目标:
1. 用户偏好严格解耦: 景点偏好 (scenic_preferences) vs 美食偏好 (food_preferences);
2. 高德 POI 白名单守门员: 严格放行人文/自然名胜 (11/1412/1413)，一票否决餐饮 (05) 与商场专柜 (06);
3. 搜索引擎职责定位: 仅为最终确立的风景名胜检索注意事项，绝不为火锅店或商场检索攻略。
"""
from __future__ import annotations

import pytest
from app.models.candidates import PoiCandidate
from app.models.session import EffectiveRequirements
from app.agents.clarification_agent import extract_slots_from_input
from app.tools.search_tools import is_valid_scenic_poi, search_attractions_tool


def test_is_valid_scenic_poi_strict_filtering():
    """测试高德 POI 守门员：准确放行风景名胜/文博古迹，坚决拦截火锅/餐饮/商场工厂店"""
    # 典型真实风景名胜
    valid_pois = [
        PoiCandidate(name="成都大熊猫繁育研究基地", category="风景名胜", typecode="110202"),
        PoiCandidate(name="成都武侯祠博物馆", category="文博古迹", typecode="141200"),
        PoiCandidate(name="成都杜甫草堂博物馆", category="文博古迹", typecode="141200"),
        PoiCandidate(name="青城山景区", category="国家级风景名胜", typecode="110201"),
        PoiCandidate(name="都江堰景区", category="国家级风景名胜", typecode="110201"),
        PoiCandidate(name="大慈寺", category="宗教场所", typecode="141300"),
        PoiCandidate(name="海合安成都极地海洋公园", category="公园", typecode="110100"),
        PoiCandidate(name="锦里古街", category="风景名胜", typecode="110200"),
        PoiCandidate(name="宽窄巷子景区", category="风景名胜", typecode="110202"),
        PoiCandidate(name="故宫博物院", category="历史文化", typecode="141200"),
        PoiCandidate(name="天坛公园", category="城市公园", typecode="110101"),
    ]

    for p in valid_pois:
        assert is_valid_scenic_poi(p) is True, f"真实景点应被放行: {p.name}"

    # 典型被误认的商业/餐饮/工厂店
    invalid_pois = [
        PoiCandidate(name="烫火锅(环球购物中心店)", category="餐饮服务", typecode="050100"),
        PoiCandidate(name="冯四孃跷脚牛肉(环球中心店)", category="餐饮服务", typecode="050100"),
        PoiCandidate(name="悦百味·品质川菜(大魔方店)", category="餐饮服务", typecode="050100"),
        PoiCandidate(name="烤匠麻辣烤鱼(环球中心店)", category="餐饮服务", typecode="050100"),
        PoiCandidate(name="管与楠鸡公煲(成都环球中心店)", category="餐饮服务", typecode="050100"),
        PoiCandidate(name="蜀绣.蜀锦.熊猫.工厂店", category="购物服务", typecode="060000"),
        PoiCandidate(name="鲲曲·满晴川·传家宴", category="餐饮服务", typecode="050100"),
        PoiCandidate(name="菁蓉汇5A座", category="商务住宅", typecode="120201"),
        PoiCandidate(name="南城都汇5A期内部停车场", category="交通设施", typecode="150909"),
        PoiCandidate(name="5A电竞明湖网咖", category="体育休闲", typecode="080308"),
    ]

    for p in invalid_pois:
        assert is_valid_scenic_poi(p) is False, f"商业/餐饮/非景点应被拦截: {p.name}"


def test_clarification_agent_decouples_food_and_scenic():
    """测试意图偏好解耦：川菜流入 food_preferences，大熊猫流入 scenic_preferences"""
    text = "我想去成都玩3天，一个人，想看大熊猫和吃川菜"
    req = extract_slots_from_input(text)

    assert req.get_slot_value("city") == "成都"
    assert req.get_slot_value("days") == 3
    assert req.get_slot_value("travel_party") == "单人出行"

    # 验证物理隔离
    food_prefs = req.get_slot_value("food_preferences")
    scenic_prefs = req.get_slot_value("scenic_preferences")
    all_prefs = req.get_slot_value("preferences")

    assert food_prefs == ["川菜"], f"美食应准确识别: {food_prefs}"
    assert scenic_prefs == ["大熊猫"], f"景点应准确识别: {scenic_prefs}"
    assert "川菜" in all_prefs and "大熊猫" in all_prefs


def test_search_attractions_filters_out_food_and_commercial():
    """测试 search_attractions_tool 在存在混杂偏好时绝不召回餐饮，只返回真正风景名胜"""
    class MockMixedWrapper:
        def __init__(self):
            self.calls = []

        def search_pois(self, city, stype, keywords="", center="", radius="", max_results=10):
            self.calls.append((stype, keywords))
            # 模拟返回混杂的 POI (部分为火锅店，部分为真实名胜)
            return [
                PoiCandidate(name="成都大熊猫繁育研究基地", category="风景名胜", typecode="110202"),
                PoiCandidate(name="烫火锅(环球购物中心店)", category="餐饮服务", typecode="050100"),
                PoiCandidate(name="成都武侯祠博物馆", category="文博古迹", typecode="141200"),
                PoiCandidate(name="蜀绣.蜀锦.熊猫.工厂店", category="购物服务", typecode="060000"),
                PoiCandidate(name="青城山景区", category="国家级风景名胜", typecode="110201"),
            ]

    mock = MockMixedWrapper()
    cands = search_attractions_tool(
        city="成都",
        preferences=["大熊猫", "川菜"],
        amap_wrapper=mock,
        use_cache=False,
    )

    names = [c.name for c in cands]
    # 餐饮与商业项目必须 100% 被剔除
    assert "烫火锅(环球购物中心店)" not in names
    assert "蜀绣.蜀锦.熊猫.工厂店" not in names

    # 真实人文自然景观必须保留
    assert "成都大熊猫繁育研究基地" in names
    assert "成都武侯祠博物馆" in names
    assert "青城山景区" in names


def test_enrich_meals_respects_food_preferences():
    """测试餐饮富化根据用户的 food_preferences 定向召回美食"""
    from app.tools.search_tools import enrich_meals_tool

    class MockFoodWrapper:
        def search_pois(self, city, stype, keywords="", center="", radius="", max_results=10):
            assert stype == "food"
            assert "川菜" in keywords
            return [
                PoiCandidate(name="陈麻婆豆腐(旗舰店)", category="川菜", rating=4.8, typecode="050100"),
                PoiCandidate(name="蜀九香火锅", category="火锅", rating=4.6, typecode="050100"),
                PoiCandidate(name="地道钟水饺", category="特色小吃", rating=4.5, typecode="050100"),
            ]

    plan_days = [{
        "day_index": 0,
        "attractions": [{"name": "武侯祠", "lng": 104.05, "lat": 30.65}],
        "meals": [],
    }]

    enrich_meals_tool(
        plan_days=plan_days,
        city="成都",
        amap_wrapper=MockFoodWrapper(),
        food_preferences=["川菜"],
    )

    meals = plan_days[0]["meals"]
    assert len(meals) == 3
    meal_names = [m["name"] for m in meals]
    assert "陈麻婆豆腐(旗舰店)" in meal_names
    for m in meals:
        assert float(m["rating"]) >= 4.0


def test_is_valid_scenic_poi_strictly_blocks_medical_and_accommodations():
    """验证医疗卫生机构、住宿酒店与普通学校绝不渗入景点候选池（即使地名含'山'/'湖'）"""
    medical_and_non_scenic = [
        # 医疗类 (Typecode 09xxxx 或名称含医院/门诊/急救)
        PoiCandidate(name="四川大学华西医院", category="医疗保健服务;综合医院;三级甲等医院", typecode="090101"),
        PoiCandidate(name="乐山市妇幼保健院", category="医疗保健服务;专科医院;妇幼保健院", typecode="090200"),
        PoiCandidate(name="乐山市人民医院", category="医疗保健服务;综合医院;综合医院", typecode="090100"),
        PoiCandidate(name="峨眉山市中医院", category="医疗保健服务;综合医院;中医院", typecode="090102"),
        PoiCandidate(name="华山医院", category="医疗保健服务;综合医院;三级甲等医院", typecode="090101"),
        PoiCandidate(name="西湖区人民医院", category="医疗保健", typecode="090100"),
        PoiCandidate(name="佛山市中医院", category="医疗保健服务", typecode="090102"),
        PoiCandidate(name="北京协和医院", category="综合医院", typecode="090101"),
        PoiCandidate(name="社区卫生服务中心", category="医疗保健服务", typecode="090400"),
        PoiCandidate(name="爱尔眼科医院", category="医疗专科", typecode="090200"),
        PoiCandidate(name="北京大学口腔医院", category="专科医院", typecode="090200"),
        PoiCandidate(name="百信大药房", category="药店", typecode="090600"),
        # 住宿酒店类 (Typecode 10xxxx 或名称含宾馆/酒店)
        PoiCandidate(name="乐山宾馆", category="住宿服务;宾馆酒店;三星级宾馆", typecode="100103"),
        PoiCandidate(name="峨眉山大酒店", category="住宿服务;宾馆酒店;五星级宾馆", typecode="100101"),
        PoiCandidate(name="如家快捷酒店(西湖店)", category="住宿服务", typecode="100100"),
        # 普通教育学校类 (Typecode 140/1410/1411/1414/1416/1420)
        PoiCandidate(name="乐山第一中学", category="科教文化服务;学校;中学", typecode="141100"),
        PoiCandidate(name="成都市实验小学", category="科教文化服务;学校;小学", typecode="141100"),
        PoiCandidate(name="东方时尚驾校", category="培训机构", typecode="141400"),
    ]

    for p in medical_and_non_scenic:
        assert is_valid_scenic_poi(p) is False, f"医疗/住宿/普通学校绝不可作为景点: {p.name} (typecode={p.typecode})"

    # 对照组：真正带有“山”/“湖”的风景名胜必须放行
    genuine_scenic = [
        PoiCandidate(name="乐山大佛景区", category="国家级风景名胜区", typecode="110201"),
        PoiCandidate(name="峨眉山金顶", category="风景名胜", typecode="110201"),
        PoiCandidate(name="杭州西湖风景名胜区", category="国家5A级景区", typecode="110201"),
        PoiCandidate(name="佛山祖庙", category="全国重点文物保护单位", typecode="141200"),
        PoiCandidate(name="黄山风景区", category="国家级风景名胜区", typecode="110201"),
    ]
    for p in genuine_scenic:
        assert is_valid_scenic_poi(p) is True, f"真正自然人文风景名胜必须放行: {p.name}"


def test_search_attractions_blocks_hospitals_in_amap_results():
    """测试 search_attractions_tool 在高德返回医疗机构时能 100% 过滤"""
    class MockMixedHospitalWrapper:
        def search_pois(self, city, stype, keywords="", center="", radius="", max_results=10):
            return [
                PoiCandidate(name="乐山大佛景区", category="国家级风景名胜区", typecode="110201"),
                PoiCandidate(name="乐山市妇幼保健院", category="医疗保健服务", typecode="090200"),
                PoiCandidate(name="乐山市人民医院", category="医疗保健服务", typecode="090100"),
                PoiCandidate(name="乐山第一中学", category="普通中学", typecode="141100"),
                PoiCandidate(name="乐山宾馆", category="住宿服务", typecode="100100"),
                PoiCandidate(name="东方佛都", category="风景名胜", typecode="110200"),
            ]

    mock = MockMixedHospitalWrapper()
    cands = search_attractions_tool(
        city="乐山",
        preferences=["自然风光"],
        amap_wrapper=mock,
        use_cache=False,
    )
    cand_names = [c.name for c in cands]
    assert "乐山大佛景区" in cand_names
    assert "东方佛都" in cand_names
    assert "乐山市妇幼保健院" not in cand_names
    assert "乐山市人民医院" not in cand_names
    assert "乐山第一中学" not in cand_names
    assert "乐山宾馆" not in cand_names

