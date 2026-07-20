"""Phase 3 验证: LangGraph 图编排

对比 Phase 2:
  Phase 2 调用: planner.plan_trip("北京", 3, ["历史文化"])
  Phase 3 调用: graph.invoke(initial_state)

对 API 层的影响（Phase 5）:
  只需改一行: planner.plan_trip(...) → graph.invoke(state)
"""
import sys
sys.path.insert(0, ".")

from app.graph.builder import get_trip_graph


def test_langgraph():
    print()
    print("╔══════════════════════════════════════════════════════╗")
    print("║     Phase 3 验证: LangGraph 图编排                   ║")
    print("╚══════════════════════════════════════════════════════╝")
    print()

    graph = get_trip_graph()

    # 初始 State——和 Phase 2 的 plan_trip() 参数一一对应
    initial_state = {
        "city": "北京",
        "days": 3,
        "preferences": ["历史文化", "美食"],
        "attraction_data": "",
        "weather_data": "",
        "hotel_data": "",
        "attraction_status": "",
        "weather_status": "",
        "hotel_status": "",
        "final_plan": {},
        "error_log": [],
    }

    print("🚀 graph.invoke(state) 开始...")
    print(f"   城市: {initial_state['city']}")
    print(f"   天数: {initial_state['days']}天")
    print(f"   偏好: {initial_state['preferences']}")
    print()

    # 一行调用——LangGraph 自动按 Edge 顺序执行 4 个 Node
    result = graph.invoke(initial_state)

    # 验证结果
    plan = result.get("final_plan", {})
    status = {
        "景点": result.get("attraction_status"),
        "天气": result.get("weather_status"),
        "酒店": result.get("hotel_status"),
    }
    errors = result.get("error_log", [])

    print("=" * 60)
    print("📊 执行结果")
    print("=" * 60)
    print(f"  Node 状态: {status}")
    print(f"  错误日志: {len(errors)} 条")
    print(f"  城市: {plan.get('city')}")
    print(f"  天数: {len(plan.get('days', []))} 天")

    if plan.get("budget"):
        b = plan["budget"]
        print(f"  预算: ¥{b.get('total', '?')}")

    for day in plan.get("days", []):
        print(f"    {day.get('date', '?')}: {len(day.get('attractions', []))} 个景点")

    print()

    # 验证要求
    assert plan.get("city") == "北京", "城市应该匹配"
    assert len(plan.get("days", [])) == 3, "应该是3天"
    assert status["景点"] == "success", f"景点搜索应该成功，实际: {status['景点']}"
    assert status["天气"] == "success", f"天气查询应该成功，实际: {status['天气']}"
    assert status["酒店"] == "success", f"酒店搜索应该成功，实际: {status['酒店']}"

    return True


if __name__ == "__main__":
    try:
        test_langgraph()
        print("=" * 60)
        print("🎉 Phase 3 验证通过！")
        print("   LangGraph StateGraph + 4 Node + Edge 编排成功")
        print("=" * 60)
    except Exception as e:
        print(f"\n❌ 失败: {e}")
        import traceback
        traceback.print_exc()
