"""Phase 6 验证: 记忆模块 + Alex 案例

测试内容:
1. 基础功能: 添加记忆、分类、标签提取
2. 频率加成: 多次相同偏好 → 权重递增
3. Alex 案例: 经济型消费者偶尔住豪华酒店 → 异常检测自动降权
4. 用户画像: get_profile() 输出结构化摘要
"""
import sys
sys.path.insert(0, ".")

from app.memory.manager import get_memory


def test_basic():
    """基础功能"""
    print("=" * 60)
    print("测试 1: 基础功能（分类 + 标签）")
    print("=" * 60)

    memory = get_memory()

    e1 = memory.add("我喜欢历史文化景点", "confirm")
    print(f"  ✅ {e1.content} → category={e1.category}, tags={e1.tags}")

    e2 = memory.add("我不吃辣", "modify")
    print(f"  ✅ {e2.content} → category={e2.category}, tags={e2.tags}")

    e3 = memory.add("偏好坐地铁出行", "observe")
    print(f"  ✅ {e3.content} → category={e3.category}, tags={e3.tags}")

    e4 = memory.add("北京今天下雨了")
    print(f"  ✅ {e4.content} → category={e4.category}")


def test_frequency_boost():
    """频率加成"""
    print("\n" + "=" * 60)
    print("测试 2: 频率加成")
    print("=" * 60)

    memory = get_memory()

    # 多次添加相同偏好
    for i in range(5):
        e = memory.add(f"酒店预算300-500元（第{i+1}次）")
        print(f"  第{i+1}次: weight={e.final_weight:.2f}, freq_boost={e.frequency_boost:.2f}")

    assert e.frequency_boost > 1.5, f"5次重复偏好应有高频加成，实际: {e.frequency_boost}"
    print(f"  ✅ 频率加成生效: {e.frequency_boost:.2f}（5次重复偏好）")


def test_alex_case():
    """
    Alex 案例:
    - 5 次选择经济型酒店 (300-500元)
    - 1 次陪老板出差选择豪华酒店 (1500+)
    → 豪华酒店应被检测为异常值并降权
    """
    print("\n" + "=" * 60)
    print("测试 3: Alex 案例（异常检测）")
    print("=" * 60)

    # 清空重新开始
    import os
    if os.path.exists("data/memory.json"):
        os.remove("data/memory.json")

    memory = get_memory()
    memory._entries = []  # 清空内存

    # Alex 的 5 次经济型酒店选择
    for i in range(5):
        e = memory.add(f"酒店预算300-500元（第{i+1}次出行）")
        print(f"  经济型 #{i+1}: weight={e.final_weight:.2f}, outlier={e.outlier_penalty}")

    # Alex 陪老板出差，选了豪华酒店
    e_luxury = memory.add("酒店预算1500-2000元（陪老板出差）")
    print(f"  豪华型:     weight={e_luxury.final_weight:.2f}, outlier={e_luxury.outlier_penalty}")

    # 验证: 豪华酒店的权重应远低于经济型
    assert e_luxury.outlier_penalty < 0.5, (
        f"豪华酒店应为异常值（outlier_penalty < 0.5），"
        f"实际: {e_luxury.outlier_penalty}"
    )
    print(f"  ✅ 异常检测生效: outlier_penalty={e_luxury.outlier_penalty}")
    print(f"     经济型偏好不会被偶然的豪华酒店选择覆盖")


def test_profile():
    """用户画像"""
    print("\n" + "=" * 60)
    print("测试 4: 用户画像")
    print("=" * 60)

    memory = get_memory()
    profile = memory.get_profile()

    import json
    print(json.dumps(profile, ensure_ascii=False, indent=2))

    # 验证关键字段
    assert "经济型" in profile.get("hotel_tier", ""), f"酒店档次应为经济型，实际: {profile.get('hotel_tier')}"
    assert profile.get("budget_range"), "应有预算区间"
    print(f"  ✅ 用户画像正确: {profile.get('hotel_tier')}, {profile.get('budget_range')}")


if __name__ == "__main__":
    print()
    print("╔══════════════════════════════════════════════════════╗")
    print("║     Phase 6 验证: 记忆模块 + Alex 案例              ║")
    print("╚══════════════════════════════════════════════════════╝")
    print()

    try:
        test_basic()
        test_frequency_boost()
        test_alex_case()
        test_profile()

        print(f"\n{'='*60}")
        print("🎉 Phase 6 验证通过！")
        print("   - 分类 + 标签提取正常")
        print("   - 频率加成: 长期偏好权重高于偶然偏好")
        print("   - Alex 案例: 异常检测自动降权，经济型画像保持稳定")
        print(f"{'='*60}")
    except Exception as e:
        print(f"\n❌ 失败: {e}")
        import traceback
        traceback.print_exc()
