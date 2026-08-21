"""v3 分日节点 — day_node 文案兜底 / JSON mode 透传 / merge 聚合 / 跨天互斥

v2: planner_node 单次生成全部天，解析失败 → retry_planner 自回环
v3: 景点集合/顺序/时间全部本地确定，LLM 只写单天文案；
    文案失败 → 本地模板兜底（不阻断全链路，不再需要解析失败回环）
"""
from conftest import base_state, make_plan_response
from app.graph import nodes as nodes_module
from app.services.clustering import LEISURE


def _day_state(**overrides):
    """day_node 的 Send payload 形态（共享上下文已由 _fan_out 显式注入）。"""
    s = {
        "day_index": 0, "day_kind": "normal", "day_date": "2026-08-21",
        "day_pois": [{"name": "故宫", "lng": 116.397, "lat": 39.917, "price": 60,
                      "district": "东城区", "category": "历史", "id": "a"},
                     {"name": "颐和园", "lng": 116.275, "lat": 39.999, "price": 30,
                      "district": "海淀区", "category": "公园", "id": "b"}],
        "city": "北京", "origin": "上海", "transport_mode": "高铁",
        "preferences": [], "user_profile": {},
        "day_start_hour": 9, "day_end_hour": 20, "budget_total": None,
        "weather_data": "【天气信息】\n- 2026-08-21: 晴转多云, 25°C~15°C, 南风",
        "hotel_candidates": [], "hotel_selected": {},
        "intercity_distance_km": 0, "intercity_duration_h": 0,
        "intercity_cost": 0, "distance_category": "", "planner_last_error": "",
    }
    s.update(overrides)
    return s


def test_day_node_llm_failure_uses_local_template(patch_nodes):
    """文案 LLM 失败 → 本地模板兜底 + error_log（不阻断全链路）。"""
    _, fake_planner, _ = patch_nodes
    fake_planner.response = "不是 JSON"
    out = nodes_module.day_node(_day_state(), None)
    day = out["plan_days"][0]
    assert day["attractions"], "景点由本地路径求解保证"
    assert "游览" in day["description"]  # 本地模板
    assert any("文案" in e for e in out["error_log"])


def test_day_node_json_mode_kwargs(patch_nodes):
    """JSON mode: response_format 透传到单天文案 LLM 调用。"""
    _, fake_planner, _ = patch_nodes
    fake_planner.response = make_plan_response()
    nodes_module.day_node(_day_state(), None)
    assert fake_planner.last_kwargs == {"response_format": {"type": "json_object"}}


def test_day_node_leisure_zero_llm(patch_nodes):
    """自由活动日零 LLM 调用。"""
    _, fake_planner, _ = patch_nodes
    out = nodes_module.day_node(_day_state(day_kind=LEISURE, day_pois=[]), None)
    assert fake_planner.prompts == []
    assert out["plan_days"][0]["kind"] == LEISURE


def test_day_node_sorts_by_route(patch_nodes):
    """路径求解: 景点带到达/离开时间（时间窗硬检查通过）。"""
    _, fake_planner, _ = patch_nodes
    fake_planner.response = make_plan_response()
    out = nodes_module.day_node(_day_state(), None)
    attrs = out["plan_days"][0]["attractions"]
    assert len(attrs) == 2
    assert all(a.get("arrive_time") for a in attrs)
    assert all(a.get("location", {}).get("longitude") for a in attrs)  # 坐标本地直出


def test_merge_aggregates_sorted_days(patch_nodes):
    """merge 聚合: 乱序 plan_days 按 day_index 排序组装 final_plan。"""
    state = base_state()
    state["plan_days"] = [
        {"date": "2026-08-22", "day_index": 1, "kind": "normal",
         "description": "d2",
         "attractions": [{"name": "B", "location": {"longitude": 116.4, "latitude": 39.9}}],
         "meals": []},
        {"date": "2026-08-21", "day_index": 0, "kind": "normal",
         "description": "d1",
         "attractions": [{"name": "A", "location": {"longitude": 116.4, "latitude": 39.9}}],
         "meals": []},
    ]
    state["hotel_selected"] = {"name": "H", "lng": 116.4, "lat": 39.9,
                               "price_range": "300-500元"}
    out = nodes_module.merge_node(state, None)
    fp = out["final_plan"]
    assert [d["day_index"] for d in fp["days"]] == [0, 1]
    assert fp["days"][0]["hotel"]["name"] == "H"
    assert "total" in fp["budget"]
    assert fp["status"] in ("success", "degraded")


def test_full_graph_cross_day_mutex(graph, patch_nodes):
    """全链路: 跨天景点互斥（聚类数据层保证，无 LLM 全局去重）+ 全程酒店填充。"""
    result = graph.invoke(base_state(days=2), {"configurable": {"thread_id": "test-thread"}})
    days = result["final_plan"]["days"]
    assert days
    all_names = [a["name"] for d in days for a in d.get("attractions", [])]
    assert len(all_names) == len(set(all_names)), "跨天景点重复！"
    assert result["final_plan"]["weather_info"], "天气本地解析应有产出"
    # v3: hotel_node around 检索 → 本地选全程酒店 → merge 填充每天
    assert days[0]["hotel"].get("name") == "核心酒店", "全程酒店未填充"
