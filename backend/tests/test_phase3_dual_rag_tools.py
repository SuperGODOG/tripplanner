"""Phase 3 自动化单元测试集: 双工 RAG 工具与动态时效事实核验体系

覆盖目标:
1. 攻略经验检索工具 (search_guides_tool) 与引用可溯源标签
2. 动态事实核验工具 (lookup_place_facts_tool) 与周一闭馆冲突判定 (CONFLICT)
3. 知名常态开放景点核验 (VERIFIED) 与实名预约政策关联
4. 否定证据严谨判定: 小众未知地点打标待确认 (NEEDS_CONFIRMATION)，杜绝脑补
5. 空白地点容错判定 (UNKNOWN)
6. 既有底层 GuideRAG 检索单例向下兼容性保障
"""
import pytest
from datetime import date
from app.models.rag_models import VerificationStatus
from app.services.guide_rag import get_guide_rag
from app.tools.rag_tools import (
    search_guides_tool,
    lookup_place_facts_tool,
)


def test_search_guides_tool_retrieval():
    """测试攻略检索工具能够正常召回结构化 GuideReference 凭据"""
    refs = search_guides_tool(poi_name="故宫", city="北京", top_k=2)

    assert len(refs) > 0
    ref = refs[0]
    assert ref.attraction == "故宫"
    assert ref.city == "北京"
    assert ref.tag in ["玩法", "避坑", "拍照", "美食"]
    assert len(ref.text) > 0


def test_lookup_place_facts_monday_closure_conflict():
    """测试国家文博展馆遇到周一日程时，精准输出 CONFLICT 闭馆冲突"""
    monday_date = "2026-09-21"
    assert date.fromisoformat(monday_date).weekday() == 0  # 确保是周一

    fact = lookup_place_facts_tool(
        poi_name="故宫博物院",
        target_date=monday_date,
        city="北京",
    )

    assert fact.verification_status == VerificationStatus.CONFLICT
    assert fact.is_open_on_date is False
    assert "周一" in fact.evidence_snippet
    assert "闭馆" in fact.evidence_snippet
    assert fact.confidence_score == 1.0


def test_lookup_place_facts_verified_open():
    """测试非周一日程时，场馆被核验为 VERIFIED 正常开放，并携带抢票政策"""
    tuesday_date = "2026-09-22"
    assert date.fromisoformat(tuesday_date).weekday() == 1  # 确保是周二

    fact = lookup_place_facts_tool(
        poi_name="故宫博物院",
        target_date=tuesday_date,
        city="北京",
    )

    assert fact.verification_status == VerificationStatus.VERIFIED
    assert fact.is_open_on_date is True
    assert fact.booking_policy is not None
    assert "抢票" in fact.booking_policy or "预约" in fact.booking_policy


def test_lookup_place_facts_known_open_venue():
    """测试常态化无休景点（如长城、天安门）即便是周一也证实开放"""
    monday_date = "2026-09-21"
    fact = lookup_place_facts_tool(
        poi_name="八达岭长城",
        target_date=monday_date,
        city="北京",
    )

    assert fact.verification_status == VerificationStatus.VERIFIED
    assert fact.is_open_on_date is True
    assert fact.opening_hours is not None


def test_lookup_place_facts_needs_confirmation_on_obscure_venue():
    """测试否定证据核心准则：未搜到闭馆不等于正常开放，小众地点必须标记待核实"""
    fact = lookup_place_facts_tool(
        poi_name="某深巷隐秘非遗手作茶坊",
        target_date="2026-10-01",
        city="北京",
    )

    assert fact.verification_status == VerificationStatus.NEEDS_CONFIRMATION
    assert fact.is_open_on_date is None  # 严禁假定开放
    assert "待核实" in fact.evidence_snippet


def test_lookup_place_facts_empty_unknown():
    """测试空名称安全降级为 UNKNOWN"""
    fact = lookup_place_facts_tool(
        poi_name="   ",
        target_date="2026-10-01",
        city="北京",
    )
    assert fact.verification_status == VerificationStatus.UNKNOWN


def test_backward_compatibility_guide_rag():
    """确保底层 GuideRAG.retrieve 老接口完全保持不变"""
    rag = get_guide_rag()
    hits = rag.retrieve("故宫", city="北京", top_k=1)
    assert isinstance(hits, list)
    assert len(hits) == 1
    assert "guide" in hits[0]
    assert "tag" in hits[0]
    assert "text" in hits[0]
