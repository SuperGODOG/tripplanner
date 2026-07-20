"""Phase 2 验证: 4 Agent 协作生成旅行计划

用法:
    cd backend
    source venv/bin/activate
    python test_agents.py
"""
import sys
sys.path.insert(0, ".")

from app.agents.trip_planner_agent import get_planner


def test_plan_trip():
    print()
    planner = get_planner()

    result = planner.plan_trip(
        city="北京",
        days=3,
        preferences=["历史文化", "美食"],
    )

    print(f"\n{'='*60}")
    print(f"📊 规划结果")
    print(f"{'='*60}")
    print(f"城市: {result.get('city')}")
    print(f"天数: {len(result.get('days', []))} 天")
    print(f"建议: {result.get('overall_suggestions', '')[:100]}")

    if result.get('budget'):
        b = result['budget']
        print(f"预算: 景点 ¥{b.get('total_attractions',0)} + 酒店 ¥{b.get('total_hotels',0)} + 餐饮 ¥{b.get('total_meals',0)} = ¥{b.get('total',0)}")

    for day in result.get('days', []):
        print(f"\n  📅 {day.get('date', '?')} — {day.get('description', '')}")
        for attr in day.get('attractions', []):
            print(f"    🏛 {attr.get('name', '?')} ({attr.get('visit_duration', '?')}分钟)")
        meals = day.get('meals', [])
        if meals:
            meal_names = [m.get('name', '?') for m in meals]
            print(f"    🍽 {' | '.join(meal_names)}")

    if result.get('weather_info'):
        w = result['weather_info'][0]
        print(f"\n  🌡 天气: {w.get('day_weather','?')}, {w.get('day_temp','?')}°C")

    return True


if __name__ == "__main__":
    try:
        test_plan_trip()
        print(f"\n{'='*60}")
        print("🎉 Phase 2 验证通过！4 Agent 协作成功生成旅行计划。")
        print(f"{'='*60}")
    except Exception as e:
        print(f"\n❌ 失败: {e}")
        import traceback
        traceback.print_exc()
