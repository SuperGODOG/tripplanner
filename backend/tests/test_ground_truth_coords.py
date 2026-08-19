"""坐标溯源 — LLM 输出的坐标幻觉必须被候选真实坐标覆盖"""
from conftest import base_state, make_poi, make_hotel
from app.graph import nodes


def test_llm_hallucinated_coords_overwritten(graph, patch_nodes):
    """planner 输出错误坐标 → 用候选真实坐标覆盖（防 1300km 级软伤）。"""
    wrapper, fake_planner, _ = patch_nodes
    wrapper.pois = [
        make_poi("凤凰寺", 120.16, 30.25, "上城区", "历史", 0),
        make_poi("鼓楼", 120.17, 30.24, "上城区", "历史", 0),
        make_poi("胡雪岩旧居", 120.18, 30.23, "上城区", "历史", 0),
    ]
    wrapper.hotels = [make_hotel("金衙庄酒店", 120.19, 30.24)]

    # LLM 输出幻觉坐标（北京附近 116,39 —— 距杭州 ~1100km）
    fake_planner.response = """```json
{
  "city": "杭州", "start_date": "2026-08-25", "end_date": "2026-08-25",
  "days": [{
    "date": "2026-08-25", "day_index": 0, "description": "x",
    "hotel": {"name": "金衙庄酒店", "location": {"longitude": 116.4, "latitude": 39.9}},
    "attractions": [
      {"name": "凤凰寺", "location": {"longitude": 116.4, "latitude": 39.9}, "visit_duration": 90, "category": "历史", "ticket_price": 0},
      {"name": "鼓楼", "location": {"longitude": 116.4, "latitude": 39.9}, "visit_duration": 90, "category": "历史", "ticket_price": 0}
    ],
    "meals": []
  }],
  "weather_info": [], "overall_suggestions": "ok",
  "budget": {"total": 300}
}
```"""
    result = graph.invoke(base_state(), {"configurable": {"thread_id": "t"}})
    day = result["final_plan"]["days"][0]

    for a in day["attractions"]:
        loc = a["location"]
        assert abs(loc["longitude"] - 116.4) > 1.0, "幻觉坐标未被覆盖"
        assert abs(loc["longitude"] - 120.16) < 0.1

    hloc = day["hotel"]["location"]
    assert abs(hloc["longitude"] - 120.19) < 0.01
    # 坐标修正后酒店到景点距离恢复正常（不再触发 1300km 软伤）
    assert not any("1347" in e or "km" in e and "> 10km" in e for e in result["error_log"])


def test_unknown_attraction_keeps_llm_coords(graph, patch_nodes):
    """LLM 输出候选里没有的景点（幻觉景点名）→ 不覆盖（保留原样，交由校验兜底）。"""
    _, fake_planner, _ = patch_nodes
    fake_planner.response = """```json
{"city": "杭州", "start_date": "2026-08-25", "end_date": "2026-08-25",
 "days": [{"date": "2026-08-25", "day_index": 0, "description": "x",
   "hotel": {"name": "不存在的酒店", "location": {"longitude": 120.5, "latitude": 30.5}},
   "attractions": [
     {"name": "不存在的景点", "location": {"longitude": 120.1, "latitude": 30.1}, "visit_duration": 60, "category": "", "ticket_price": 0},
     {"name": "也不存在", "location": {"longitude": 120.2, "latitude": 30.2}, "visit_duration": 60, "category": "", "ticket_price": 0}
   ], "meals": []}],
 "weather_info": [], "overall_suggestions": "ok", "budget": {"total": 100}}
```"""
    result = graph.invoke(base_state(), {"configurable": {"thread_id": "t"}})
    day = result["final_plan"]["days"][0]
    assert day["attractions"][0]["location"]["longitude"] == 120.1  # 未被覆盖
