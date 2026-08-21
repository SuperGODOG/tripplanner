"""酒店目标函数选址（v3）— minimax 通勤 + 远郊排除 + 经济型偏好过滤

v2: 市区质心最近（几何平均，离群敏感、无业务语义）
v3: 直接对候选酒店打分——score(h) = max over 市区景点 dist(h, p)（minimax），
    保证"最远景点不远"；远郊点不参与（excursion 日默认长通勤）；经济型偏好前置过滤。
"""
from conftest import make_hotel, make_poi
from app.graph import nodes
from app.services.clustering import EXCURSION


def _state_with_clusters(hotels=None, pois=None, profile=None):
    """构造 hotel_node 所需 state: 城市中心 + day_clusters + 画像。"""
    state = {
        "city": "北京",
        "day_clusters": [{
            "day_index": 0, "kind": "normal",
            "pois": pois or [
                {"name": "故宫", "lng": 116.397, "lat": 39.917, "id": "g"},
                {"name": "颐和园", "lng": 116.275, "lat": 39.999, "id": "y"},
            ],
        }],
        "excursion_pois": [],
        "user_profile": profile or {},
        "hotel_candidates": [],
    }
    return state


def test_minimax_selects_central_hotel(monkeypatch):
    """minimax: 景点群中央的酒店胜出（vs 边缘酒店）。"""
    state = _state_with_clusters()
    central = make_hotel("中央酒店", 116.33, 39.95)      # 距故宫 ~6km, 距颐和园 ~7km
    edge = make_hotel("边缘酒店", 116.9, 40.2)           # 距所有景点 45km+
    best = nodes._select_hotel([central, edge], state)
    assert best["name"] == "中央酒店"


def test_excursion_poi_excluded_from_scoring(monkeypatch):
    """远郊点不参与打分（否则会惩罚所有酒店——excursion 日默认长通勤）。"""
    state = _state_with_clusters()
    state["day_clusters"].append({
        "day_index": 1, "kind": EXCURSION,
        "pois": [{"name": "长城", "lng": 115.9, "lat": 40.6, "id": "cw"}],  # ~87km
    })
    # 若长城参与打分，minimax 距离 ~90km；不参与则 ~7km
    central = make_hotel("中央酒店", 116.33, 39.95)
    far = make_hotel("远郊酒店", 115.9, 40.5)  # 离长城近、离市区远
    best = nodes._select_hotel([central, far], state)
    assert best["name"] == "中央酒店", "远郊点不应参与 minimax 打分"


def test_economic_preference_filters_pool(monkeypatch):
    """经济型偏好: 候选池前置过滤到经济型酒店，再 minimax。"""
    state = _state_with_clusters(profile={"accommodation": "经济型"})
    luxury = make_hotel("豪华酒店", 116.33, 39.95)   # 位置最优但不是经济型
    econ_near = make_hotel("经济酒店A", 116.35, 39.93, hotel_type="经济型")
    econ_far = make_hotel("经济酒店B", 116.5, 40.0, hotel_type="经济型")
    best = nodes._select_hotel([luxury, econ_near, econ_far], state)
    assert best["name"] == "经济酒店A", "应优先经济型池内的 minimax 最优"


def test_no_urban_pois_falls_back_first_candidate(monkeypatch):
    """无市区景点数据（聚类/坐标缺失）→ 退化取第一个候选，不崩溃。"""
    state = _state_with_clusters(pois=[])
    state["day_clusters"] = []
    h = make_hotel("兜底酒店", 116.4, 39.9)
    best = nodes._select_hotel([h], state)
    assert best["name"] == "兜底酒店"


def test_hotel_node_uses_city_center_radius_10km(patch_nodes):
    """搜索中心 = 城市中心（geocode），半径 10km；minimax 选址落进 hotel_selected。"""
    wrapper, _, _ = patch_nodes
    result = nodes.hotel_node({
        "city": "北京",
        "day_clusters": [{"day_index": 0, "kind": "normal", "pois": [
            {"name": "故宫", "lng": 116.397, "lat": 39.917, "id": "g"}]}],
        "excursion_pois": [], "user_profile": {},
    }, None)
    assert result["hotel_status"] == "success"
    around_calls = [c for c in wrapper.calls if c[0] == "around"]
    assert around_calls and around_calls[0][3] == "10000", "半径应为 10km"
    assert result["hotel_selected"]["name"] == "核心酒店"
