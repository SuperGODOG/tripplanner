"""画像防御 — 记忆 JSON 中的 None 值不得击穿约束构建"""
from app.graph import nodes


def test_profile_with_none_values_no_crash():
    """真实记忆数据可能含 None 值键（宽松 JSON），约束构建必须容错。"""
    profile = {
        "accommodation": None,      # 键存在但为 None
        "budget_tier": None,
        "diet": None,
        "pace": None,
        "interests": None,
    }
    assert nodes._build_profile_constraints(profile) == ""


def test_profile_with_valid_values_builds_constraints():
    profile = {"budget_tier": "穷游", "diet": ["不吃辣"], "accommodation": "经济型", "pace": "紧凑高效"}
    out = nodes._build_profile_constraints(profile)
    assert "免费景点" in out and "辣味菜系" in out and "经济型酒店" in out and "3 个景点" in out


def test_profile_partial_none_mixed():
    """部分字段 None、部分有效。"""
    profile = {"budget_tier": None, "diet": ["不吃辣"], "accommodation": None, "pace": "紧凑高效"}
    out = nodes._build_profile_constraints(profile)
    assert "辣味菜系" in out and "3 个景点" in out
    assert "经济型" not in out
