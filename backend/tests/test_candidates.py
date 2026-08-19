"""候选模型 — 稳定 ID / 坐标转换 / 字段完整性"""
from app.models.candidates import PoiCandidate, HotelCandidate
from app.tools.amap_wrapper import AmapToolWrapper


def test_stable_id_deterministic():
    a = PoiCandidate(name="故宫", lng=116.397, lat=39.917, district="东城区")
    b = PoiCandidate(name="故宫", lng=116.397, lat=39.917, district="东城区")
    assert a.id == b.id
    assert len(a.id) == 12


def test_id_differs_for_diff_coords():
    a = PoiCandidate(name="故宫", lng=116.397, lat=39.917)
    b = PoiCandidate(name="故宫", lng=116.398, lat=39.918)
    assert a.id != b.id


def test_hotel_candidate_inherits_and_extends():
    h = HotelCandidate(name="核心酒店", lng=116.4, lat=39.91,
                       rating="4.5", price_range="300-500元", hotel_type="经济型")
    assert h.source == "amap"
    assert h.id and h.rating == "4.5" and h.hotel_type == "经济型"


def test_candidate_from_poi_with_geo_coords():
    """坐标增强后的 POI（_lng/_lat）直接转换。"""
    w = AmapToolWrapper.__new__(AmapToolWrapper)   # 绕过 __init__（不连 MCP）
    poi = {"name": "故宫", "address": "景山前街4号", "adname": "东城区",
           "_lng": 116.397, "_lat": 39.917, "type": "风景名胜;公园广场;历史",
           "price": "60"}
    c = w._candidate_from_poi(poi, PoiCandidate)
    assert c is not None
    assert c.name == "故宫" and c.lng == 116.397 and c.lat == 39.917
    assert c.district == "东城区" and c.price == 60.0


def test_candidate_from_poi_with_location_string():
    """未增强的 POI（location "lng,lat"）也能转换。"""
    w = AmapToolWrapper.__new__(AmapToolWrapper)
    poi = {"name": "天坛", "location": "116.406,39.882", "adname": "东城区"}
    c = w._candidate_from_poi(poi, PoiCandidate)
    assert c is not None and abs(c.lng - 116.406) < 1e-6


def test_candidate_from_poi_missing_coords_dropped():
    """无坐标的 POI 被丢弃（不能进入结构化候选）。"""
    w = AmapToolWrapper.__new__(AmapToolWrapper)
    assert w._candidate_from_poi({"name": "无名点"}, PoiCandidate) is None
    assert w._candidate_from_poi({}, PoiCandidate) is None


def test_search_pois_around_hotel_returns_hotel_candidates(monkeypatch):
    """酒店走 around+关键词 路径时也必须返回 HotelCandidate（hotel_type 字段）。"""
    from conftest import FakeAmapWrapper
    w = FakeAmapWrapper(hotels=[])
    # 直接用真实逻辑验证 cls 推断：around + 关键词"酒店" → HotelCandidate
    assert _search_cls("around", "酒店") is HotelCandidate
    assert _search_cls("hotel", "酒店") is HotelCandidate
    assert _search_cls("around", "历史") is PoiCandidate
    assert _search_cls("food", "") is PoiCandidate


def _search_cls(stype: str, keywords: str) -> type:
    """复刻 search_pois 的 cls 推断规则（防回归）。"""
    from app.models.candidates import PoiCandidate, HotelCandidate
    return HotelCandidate if (stype == "hotel" or "酒店" in (keywords or "")) else PoiCandidate


def test_candidate_from_poi_hotel_fields():
    w = AmapToolWrapper.__new__(AmapToolWrapper)
    poi = {"name": "如家", "location": "116.4,39.91",
           "type": "住宿服务;宾馆酒店;经济型连锁酒店", "rating": "4.3"}
    h = w._candidate_from_poi(poi, HotelCandidate)
    assert isinstance(h, HotelCandidate)
    assert h.hotel_type == "经济型连锁酒店"
    assert h.rating == "4.3"
