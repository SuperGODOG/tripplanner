"""多偏好召回 / 去重 / 远郊标记 — 确定性节点行为"""
from conftest import base_state, make_poi
from app.graph import nodes


def test_multi_pref_recalls_all_prefs(patch_nodes):
    """每个偏好独立召回（并行），不再 prefs[0] 截断。"""
    wrapper, _, _ = patch_nodes
    state = base_state(prefs=["历史", "美食"])
    result = nodes.attraction_node(state)

    assert result["attraction_status"] == "success"
    # 两个偏好 → 两次 around 召回
    around_calls = [c for c in wrapper.calls if c[0] == "around"]
    assert len(around_calls) == 2
    kws = {c[1] for c in around_calls}
    assert kws == {"历史", "美食"}
    assert result["attraction_candidates"]


def test_no_prefs_falls_back_to_default(patch_nodes):
    wrapper, _, _ = patch_nodes
    result = nodes.attraction_node(base_state(prefs=[]))
    assert result["attraction_status"] == "success"
    around_calls = [c for c in wrapper.calls if c[0] == "around"]
    assert len(around_calls) == 1
    assert around_calls[0][1] == "景点"


def test_duplicate_pois_deduped_by_stable_id(patch_nodes):
    """同一 POI 被多偏好命中时只保留一份（稳定 id 去重）。"""
    wrapper, _, _ = patch_nodes
    dup = make_poi("故宫", 116.397, 39.917, "东城区", "历史", 60)
    wrapper.pois = [dup, dup, make_poi("天坛", 116.406, 39.882, "东城区", "历史", 15)]
    result = nodes.attraction_node(base_state(prefs=["历史", "古迹"]))
    names = [c["name"] for c in result["attraction_candidates"]]
    assert len(names) == len(set(names))
    assert names.count("故宫") == 1


def test_far_poi_marked_excursion_not_deleted(patch_nodes):
    """>80km 远郊景点：标记 excursion 一日游，不删除、不进市区质心。"""
    wrapper, _, _ = patch_nodes
    wrapper.pois = [
        make_poi("市区A", 116.4, 39.9, "东城区", "历史", 0),
        make_poi("市区B", 116.5, 39.95, "朝阳区", "公园", 0),
        make_poi("长城", 115.9, 40.6, "延庆区", "自然", 40),   # 距市中心 ~87km
    ]
    result = nodes.attraction_node(base_state(prefs=["景点"]))

    assert result["attraction_status"] == "success"
    names = [c["name"] for c in result["attraction_candidates"]]
    assert "长城" in names                      # 不删除
    assert "长城" in [e["name"] for e in result["excursion_pois"]]   # 标记远郊
    # 市区质心只由市区点计算
    urban_lng = result["urban_lng"]
    assert urban_lng < 116.5 and urban_lng > 116.3


def test_excursion_distance_in_state(patch_nodes):
    wrapper, _, _ = patch_nodes
    wrapper.pois = [
        make_poi("近点", 116.4, 39.9),
        make_poi("远点", 115.5, 40.5),   # 约 100km
    ]
    result = nodes.attraction_node(base_state(prefs=["景点"]))
    exc = result["excursion_pois"]
    assert exc and exc[0]["name"] == "远点"
    assert exc[0]["dist_km"] > 80


def test_city_center_failure_falls_back_to_text_search(patch_nodes, monkeypatch):
    """maps_geo 失败 → 退化全城 text_search（attraction 类型调用）。"""
    wrapper, _, _ = patch_nodes
    monkeypatch.setattr(nodes, "_city_center", lambda city: None)
    result = nodes.attraction_node(base_state(prefs=["历史"]))
    assert result["attraction_status"] == "success"
    stypes = {c[0] for c in wrapper.calls}
    assert "around" not in stypes
    assert "attraction" in stypes
