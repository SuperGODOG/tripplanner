"""高德 POI 详细字段完整透传、三餐美食严格防跨省漂移与搜索引擎标识专项测试
"""
from __future__ import annotations

import pytest
from app.models.candidates import PoiCandidate, HotelCandidate
from app.tools.amap_wrapper import AmapToolWrapper
from app.tools.search_tools import (
    is_valid_scenic_poi,
    _get_city_signature_meals,
    enrich_meals_tool,
    haversine_km,
)


def test_poi_candidate_rich_fields():
    """验证 PoiCandidate 具备营业时间、商圈、国家景区评级与门牌地址等丰富字段"""
    cand = PoiCandidate(
        name="峨眉山",
        lng=103.339,
        lat=29.547,
        address="景区路三段301号",
        district="峨眉山市",
        category="风景名胜;风景名胜;国家级景点",
        typecode="110202",
        rating=4.9,
        open_time="06:00-18:00",
        business_area="峨眉山-金顶",
        level="AAAAA",
        tel="0833-5533355",
    )
    assert cand.name == "峨眉山"
    assert cand.rating == 4.9
    assert cand.open_time == "06:00-18:00"
    assert cand.business_area == "峨眉山-金顶"
    assert cand.level == "AAAAA"
    assert cand.address == "景区路三段301号"
    assert cand.tel == "0833-5533355"


def test_amap_wrapper_candidate_from_poi_rich_extraction():
    """验证 AmapToolWrapper._candidate_from_poi 能够完整解析高德原生的丰富返回值"""
    wrapper = AmapToolWrapper()
    raw_poi = {
        "id": "B03410OH95",
        "name": "峨眉山",
        "location": "103.339087,29.547200",
        "address": "景区路三段301号",
        "adname": "峨眉山市",
        "type": "风景名胜;国家级景点",
        "typecode": "110202",
        "rating": "4.9",
        "open_time": "06:00-18:00",
        "opentime2": "周一至周日 06:00-18:00",
        "business_area": "峨眉山-金顶",
        "level": "AAAAA",
        "tel": "0833-5533355",
        "cost": "160.00",
    }
    cand = wrapper._candidate_from_poi(raw_poi, PoiCandidate)
    assert cand is not None
    assert cand.name == "峨眉山"
    assert cand.rating == 4.9
    assert cand.open_time == "06:00-18:00"
    assert cand.business_area == "峨眉山-金顶"
    assert cand.level == "AAAAA"
    assert cand.price == 160.0
    assert cand.district == "峨眉山市"
    assert cand.address == "景区路三段301号"


def test_is_valid_scenic_poi_blocks_government_agencies():
    """验证守门员坚决拦截 130000 政府机构与管委会/气象局"""
    # 政府/公共管理机构必须拦截
    gov_pois = [
        PoiCandidate(name="峨眉山市气象局", category="政府机构及社会团体", typecode="130000"),
        PoiCandidate(name="峨眉山·乐山大佛风景名胜区管理委员会凌云乌尤管理处", category="政府机构", typecode="130100"),
        PoiCandidate(name="乐山市市中区公安局派出所", category="公检法机构", typecode="130500"),
        PoiCandidate(name="峨眉山市人民法院", category="公检法机构", typecode="130501"),
    ]
    for p in gov_pois:
        assert is_valid_scenic_poi(p) is False, f"政府政务单位应被拦截: {p.name}"

    # 真正的名胜必须放行
    scenic = PoiCandidate(name="峨眉山", category="国家级景点", typecode="110202")
    assert is_valid_scenic_poi(scenic) is True


def test_city_alias_mapping_for_meals():
    """验证城市别名映射：输入「峨眉山」或「都江堰」正确映射到「乐山」或「成都」本地名店"""
    emei_meals = _get_city_signature_meals("峨眉山", 0)
    assert len(emei_meals) == 3
    # 必须是乐山/峨眉山地道美食，绝不能是陕西或西安菜
    names = [m["name"] for m in emei_meals]
    assert any("翘脚牛肉" in n or "烧麦" in n or "钵钵鸡" in n for n in names)
    assert not any("泡馍" in n or "糊辣汤" in n for n in names)

    djy_meals = _get_city_signature_meals("都江堰", 0)
    assert len(djy_meals) == 3
    djy_names = [m["name"] for m in djy_meals]
    assert any("麻婆豆腐" in n or "凉粉" in n or "火锅" in n for n in djy_names)


def test_enrich_meals_strict_distance_guard_prevents_shaanxi_drift():
    """测试三餐周边富化严格防跨省漂移：
    即便传入了 500km 外的陕西餐馆脏数据，守门员也必须依据 Haversine 距离彻底拦截并由本地名店兜底！
    """
    class MockDriftingWrapper:
        def search_pois(self, city, stype, keywords="", center="", radius="", max_results=10):
            # 故意返回包含 500km 外陕西西安的餐馆脏数据
            return [
                PoiCandidate(
                    name="老米家大雨泡馍总店",
                    district="西安市莲湖区",
                    address="回民街西羊市",
                    lng=108.939,  # 西安坐标，距峨眉山约 580km
                    lat=34.265,
                    rating=4.8,
                    price=48,
                    category="陕菜非遗",
                ),
                PoiCandidate(
                    name="峨眉山金顶美食林餐厅",
                    district="乐山市峨眉山市",
                    address="景区路三段301号峨眉山",
                    lng=103.337,  # 峨眉山真实坐标
                    lat=29.521,
                    rating=4.2,
                    price=77,
                    category="地道川菜",
                ),
            ]

    # 峨眉山景区 Day 1 (103.339, 29.547)
    plan_days = [
        {
            "day_index": 0,
            "attractions": [
                {
                    "name": "峨眉山",
                    "lng": 103.339,
                    "lat": 29.547,
                    "location": {"longitude": 103.339, "latitude": 29.547},
                }
            ],
            "meals": [],
        }
    ]

    enrich_meals_tool(
        plan_days=plan_days,
        city="峨眉山",
        amap_wrapper=MockDriftingWrapper(),
    )

    meals = plan_days[0]["meals"]
    assert len(meals) == 3, "必须确保早中晚三餐完备"

    for m in meals:
        m_lng = m["location"]["longitude"]
        m_lat = m["location"]["latitude"]
        # 计算餐厅到景点的实际距离
        dist_km = haversine_km(103.339, 29.547, m_lng, m_lat)
        # 守门员断言：距离必须 <= 20km，彻底杜绝跨省漂移！
        assert dist_km <= 20.0, f"餐厅「{m['name']}」距景点 {dist_km:.1f}km 严重超标！"
        assert "泡馍" not in m["name"], f"陕西泡馍绝不应出现在峨眉山行程中: {m['name']}"
        assert "西安" not in m.get("description", ""), f"西安描述不应出现: {m}"
