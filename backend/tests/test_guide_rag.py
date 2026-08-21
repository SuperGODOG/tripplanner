"""攻略知识库（轻量 RAG，手写 BM25）— 检索/过滤/排序/注入/降级

v3.1 新增:
- query 是确定性实体（景点名），BM25 段落级评分，无向量库
- 引用可溯源: day.guide_references 带 guide/city/tag
- 降级透明: 知识库缺失/未命中 → 空，不阻断规划
"""
import json

import pytest

from app.services.guide_rag import GuideRAG, get_guide_rag, _tokenize


@pytest.fixture
def sample_guides(tmp_path):
    """小型可控知识库（tmp_path，不依赖真实数据文件）。"""
    data = [
        {"name": "故宫", "city": "北京", "tags": ["历史", "拍照"],
         "content": "【玩法】8:30 开门就冲，午门进神武门出不回头。\n\n【避坑】周一闭馆，提前 7 天预约。\n\n【拍照】角楼咖啡窗边位绝了。"},
        {"name": "颐和园", "city": "北京", "tags": ["自然", "拍照"],
         "content": "【玩法】北宫门进，苏州街→佛香阁→长廊→十七孔桥。\n\n【避坑】旺季周末人多，工作日早 9 点前到。"},
        {"name": "外滩", "city": "上海", "tags": ["夜景"],
         "content": "【玩法】傍晚从南京东路步行到外滩，看万国建筑亮灯。"},
    ]
    p = tmp_path / "guides.json"
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return str(p)


def test_retrieve_exact_hit(sample_guides):
    """景点名精确匹配 → 返回该攻略段落（带标签前缀）。"""
    rag = GuideRAG(sample_guides)
    hits = rag.retrieve("故宫", city="北京", top_k=2)
    assert hits, "应命中故宫攻略"
    assert hits[0]["guide"] == "故宫"
    assert hits[0]["tag"] == "玩法"          # 段落标签前缀
    assert "8:30 开门就冲" in hits[0]["text"]
    assert hits[0]["city"] == "北京"


def test_retrieve_miss_returns_empty(sample_guides):
    """未知景点 → 空列表（降级透明）。"""
    rag = GuideRAG(sample_guides)
    assert rag.retrieve("火星基地") == []


def test_city_filter(sample_guides):
    """城市过滤: 上海城市下搜故宫 → 空（严格过滤）。"""
    rag = GuideRAG(sample_guides)
    assert rag.retrieve("故宫", city="上海") == []


def test_bm25_ranks_relevant_para_higher(sample_guides):
    """BM25 段落级评分: 查询词出现在内容中的段落排前面。"""
    rag = GuideRAG(sample_guides)
    # "拍照"同时是故宫和颐和园的 tag，但故宫内容含"拍照"字样（角楼拍照）
    hits = rag.retrieve("拍照", city="北京", top_k=2)
    assert hits and hits[0]["guide"] == "故宫"


def test_tags_fallback(sample_guides):
    """攻略名不匹配但 tags 命中 → 兜底返回。"""
    rag = GuideRAG(sample_guides)
    hits = rag.retrieve("夜景", city="上海", top_k=1)
    assert hits and hits[0]["guide"] == "外滩"


def test_coverage_metric(sample_guides):
    """覆盖率指标（RAG 效果评估的可落地指标）。"""
    rag = GuideRAG(sample_guides)
    cov = rag.coverage(["故宫", "颐和园", "火星基地"])
    assert cov["total"] == 3 and cov["hit"] == 2 and cov["rate"] == round(2 / 3, 2)


def test_missing_file_returns_empty(tmp_path):
    """知识库文件不存在 → 空检索器（不抛错）。"""
    rag = GuideRAG(str(tmp_path / "nope.json"))
    assert rag.retrieve("故宫") == []
    assert rag.coverage(["故宫"])["rate"] == 0.0


def test_tokenize_bigram():
    """中文 bigram 分词: '故宫' → ['故宫']（2 字整串）。"""
    toks = _tokenize("故宫")
    assert "故宫" in toks
    assert _tokenize("历史文化名城")[:2]  # bigram 有产出


def test_day_node_injects_guide_and_refs(patch_nodes):
    """day_node: 攻略片段进 prompt + guide_references 可溯源字段。"""
    _, fake_planner, _ = patch_nodes
    fake_planner.response = json.dumps(
        {"description": "d", "transportation": "t",
         "accommodation": "a", "overall_tips": "o"}, ensure_ascii=False)
    from app.graph import nodes as nodes_module
    out = nodes_module.day_node({
        "day_index": 0, "day_kind": "normal", "day_date": "2026-08-21",
        "day_pois": [{"name": "故宫", "lng": 116.397, "lat": 39.917,
                      "district": "东城区", "category": "历史", "price": 60, "id": "g"},
                     {"name": "颐和园", "lng": 116.275, "lat": 39.999,
                      "district": "海淀区", "category": "公园", "price": 30, "id": "y"}],
        "city": "北京", "origin": "上海", "transport_mode": "高铁",
        "preferences": [], "user_profile": {},
        "day_start_hour": 9, "day_end_hour": 20, "budget_total": None,
        "weather_data": "【天气信息】\n- 2026-08-21: 晴转多云, 25°C~15°C, 南风",
        "hotel_candidates": [], "hotel_selected": {},
        "intercity_distance_km": 0, "intercity_duration_h": 0,
        "intercity_cost": 0, "distance_category": "", "planner_last_error": "",
    }, None)
    day = out["plan_days"][0]
    # 真实知识库命中（故宫/颐和园攻略存在）
    assert day["guide_references"], "guide_references 应为空后被填充"
    assert {r["attraction"] for r in day["guide_references"]} <= {"故宫", "颐和园"}
    # prompt 含攻略片段
    assert "参考攻略片段" in fake_planner.prompts[0]
    assert any(r["guide"] == "故宫" or r["attraction"] == "故宫"
               for r in day["guide_references"])


def test_day_node_degrades_without_guide_file(patch_nodes, monkeypatch, tmp_path):
    """知识库缺失 → day_node 不崩，guide_references 空。"""
    _, fake_planner, _ = patch_nodes
    from app.graph import nodes as nodes_module
    from app.services import guide_rag as rag_module
    monkeypatch.setattr(rag_module, "GUIDES_PATH", str(tmp_path / "none.json"))
    monkeypatch.setattr(rag_module, "_rag", None)  # 重置单例
    out = nodes_module.day_node({
        "day_index": 0, "day_kind": "normal", "day_date": "2026-08-21",
        "day_pois": [{"name": "故宫", "lng": 116.397, "lat": 39.917, "id": "g"}],
        "city": "北京", "day_start_hour": 9, "day_end_hour": 20,
        "preferences": [], "user_profile": {}, "hotel_selected": {},
    }, None)
    assert out["plan_days"][0]["guide_references"] == []
    assert out["plan_days"][0]["attractions"]  # 计划不受影响
