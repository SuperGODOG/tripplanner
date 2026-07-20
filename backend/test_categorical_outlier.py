"""Phase 6 扩展测试: 分类型异常检测

测试: 5 次"不吃辣" → 1 次"爱吃辣" → 爱吃辣应被降权
"""
import sys, os
sys.path.insert(0, ".")

# 清空
if os.path.exists("data/memory.json"):
    os.remove("data/memory.json")

from app.memory.manager import get_memory

memory = get_memory()
memory._entries = []

print("=" * 60)
print("测试: 分类型 Alex 案例")
print("=" * 60)

# 5 次不吃辣
for i in range(5):
    e = memory.add(f"偏好: 不吃辣（第{i+1}次）")
    print(f"  不吃辣 #{i+1}: weight={e.final_weight:.2f}, outlier={e.outlier_penalty}")

# 1 次爱吃辣（异常）
e_spicy = memory.add("偏好: 爱吃辣（偶然尝试）")
print(f"  爱吃辣:     weight={e_spicy.final_weight:.2f}, outlier={e_spicy.outlier_penalty}")

assert e_spicy.outlier_penalty < 0.5, f"爱吃辣应为异常，实际 outlier={e_spicy.outlier_penalty}"
print(f"\n✅ 分类型异常检测生效: outlier_penalty={e_spicy.outlier_penalty}")

# 验证画像
profile = memory.get_profile()
print(f"\n画像: diet={profile.get('diet')}")
assert "不吃辣" in str(profile.get("diet", [])), "不吃辣应在画像中"
print("✅ 画像保持: 不吃辣")

print(f"\n🎉 分类型 Alex 案例通过！")
