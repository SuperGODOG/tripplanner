"""Phase 1 自动化单元测试集: 基础领域数据模型与防记忆污染体系

覆盖目标:
1. 三轨槽位创建、改口覆盖与版本追踪 (EffectiveRequirements)
2. 现有 TripPlannerState 兼容 Adapter 转换
3. 四级偏好优先级裁决引擎 (resolve_effective_slot)
4. 持久副词判定与长期记忆防污染门控 (MemoryManager.record_user_preference)
5. 结构化算法诊断模型 (DiagnosticSignal, RouteSolverResult)
6. 双工 RAG 时效凭据契约模型 (PlaceFact, VerificationStatus)
"""
import pytest
from app.models.session import (
    SlotOrigin,
    PreferenceScope,
    RequirementSlot,
    EffectiveRequirements,
    PlanVersion,
    SessionState,
)
from app.models.diagnostics import (
    ErrorCode,
    DiagnosticSeverity,
    DiagnosticSignal,
    RouteSolverResult,
)
from app.models.rag_models import (
    VerificationStatus,
    PlaceFact,
    GuideReference,
)
from app.memory.manager import (
    MemoryManager,
    is_persistent_preference,
    resolve_effective_slot,
)


def test_requirement_slot_creation_and_override():
    """测试需求槽位创建、改口覆盖与版本号追踪"""
    req = EffectiveRequirements(revision_id=1)

    # 1. 首次赋值
    s1 = req.set_slot("city", "北京", origin=SlotOrigin.USER_EXPLICIT)
    assert s1.value == "北京"
    assert s1.origin == SlotOrigin.USER_EXPLICIT
    assert req.revision_id == 1
    assert req.get_slot_value("city") == "北京"

    # 2. 改口赋值 (北京 -> 上海)
    s2 = req.set_slot("city", "上海", origin=SlotOrigin.USER_EXPLICIT)
    assert s2.value == "上海"
    assert req.revision_id == 2  # 版本自增
    assert s2.overridden_at_revision == 2
    assert s2.previous_values == ["北京"]  # 历史轨迹归档
    assert req.get_slot_value("city") == "上海"

    # 3. 赋值相同值不触发版本自增
    req.set_slot("city", "上海", origin=SlotOrigin.USER_EXPLICIT)
    assert req.revision_id == 2


def test_effective_requirements_adapter():
    """测试 EffectiveRequirements 向既有 TripPlannerState 的向后兼容转换"""
    req = EffectiveRequirements()
    req.set_slot("city", "成都", origin=SlotOrigin.USER_EXPLICIT)
    req.set_slot("days", 4, origin=SlotOrigin.USER_EXPLICIT)
    req.set_slot("preferences", "美食, 看熊猫", origin=SlotOrigin.USER_EXPLICIT)
    req.set_slot("budget_total", 3000, origin=SlotOrigin.USER_EXPLICIT)

    state_dict = req.to_trip_state_dict(user_id="test_user_001")

    assert state_dict["user_id"] == "test_user_001"
    assert state_dict["city"] == "成都"
    assert state_dict["days"] == 4
    assert state_dict["preferences"] == ["美食", "看熊猫"]
    assert state_dict["budget_total"] == 3000
    assert state_dict["day_start_hour"] == 9
    assert state_dict["day_end_hour"] == 20


def test_four_tier_preference_resolution():
    """测试四级偏好优先级裁决引擎"""
    long_term_profile = {
        "accommodation": "经济型酒店",
        "diet": ["清淡"],
    }

    # 场景 A: 本次显式指定 (USER_EXPLICIT) > 长期历史画像
    trip_slots_a = {
        "accommodation": RequirementSlot(
            key="accommodation",
            value="豪华型酒店",
            origin=SlotOrigin.USER_EXPLICIT,
            scope=PreferenceScope.TRIP_TRANSIENT,
        )
    }
    val_a, origin_a, scope_a = resolve_effective_slot(
        "accommodation", trip_slots_a, long_term_profile, default_val="中端型酒店"
    )
    assert val_a == "豪华型酒店"
    assert origin_a == SlotOrigin.USER_EXPLICIT
    assert scope_a == PreferenceScope.TRIP_TRANSIENT

    # 场景 B: 本次未显式指定，继承长期画像
    trip_slots_b = {}
    val_b, origin_b, scope_b = resolve_effective_slot(
        "accommodation", trip_slots_b, long_term_profile, default_val="中端型酒店"
    )
    assert val_b == "经济型酒店"
    assert origin_b == SlotOrigin.MODEL_INFERRED
    assert scope_b == PreferenceScope.LONG_TERM_USER

    # 场景 C: 本次与长期皆无，降级为默认值
    trip_slots_c = {}
    val_c, origin_c, scope_c = resolve_effective_slot(
        "pace", trip_slots_c, long_term_profile, default_val="适中"
    )
    assert val_c == "适中"
    assert origin_c == SlotOrigin.DEFAULT_VALUE
    assert scope_c == PreferenceScope.SYSTEM_DEFAULT


def test_memory_anti_poisoning_transient():
    """测试单次消费与临时诉求不污染长期记忆库"""
    mgr = MemoryManager(storage_path=None)

    # 1. 用户说临时性偏好（无持久副词）
    transient_text = "这次旅行我想住好一点，预算宽松点"
    assert is_persistent_preference(transient_text) is False

    entry, saved_to_long_term = mgr.record_user_preference(transient_text)
    assert entry is None
    assert saved_to_long_term is False
    assert len(mgr._entries) == 0  # 长期库保持干净，0 污染


def test_memory_persistent_adverb_promotion():
    """测试显式持久副词成功沉淀进长期记忆库"""
    mgr = MemoryManager(storage_path=None)

    # 2. 用户带有明确持久副词
    persistent_texts = [
        "我平时一直不吃辣，比较怕辣",
        "出门习惯地铁出行，总是喜欢坐地铁",
        "长年喜欢历史文化古迹",
    ]

    for text in persistent_texts:
        assert is_persistent_preference(text) is True
        entry, saved = mgr.record_user_preference(text)
        assert entry is not None
        assert saved is True

    assert len(mgr._entries) == 3
    profile = mgr.get_profile()
    assert "饮食:不吃辣" in profile["diet"] or any("不吃辣" in d for d in profile["diet"])


def test_diagnostic_and_rag_schemas():
    """测试结构化诊断信号与双工 RAG 凭据模型"""
    # 1. 诊断信号
    diag = DiagnosticSignal(
        error_code=ErrorCode.TIME_WINDOW_EXCEEDED,
        day_index=1,
        severity=DiagnosticSeverity.HARD_FAIL,
        summary="第2天游玩加通勤总计690分钟，超过日时间窗660分钟",
        details={"exceeded_minutes": 30, "conflicting_pois": ["八达岭长城", "颐和园"]},
        immutable_constraints=["如家快捷酒店(已预订)"],
        attempted_actions=["2-opt 逆序调序仍超限"],
        actionable_suggestions=["建议将八达岭长城拆分至独立一天", "建议移除颐和园"],
    )
    assert diag.error_code == ErrorCode.TIME_WINDOW_EXCEEDED
    assert diag.details["exceeded_minutes"] == 30

    result = RouteSolverResult(
        success=False,
        total_min=690,
        total_ticket=120,
        exceeds_day=True,
        diagnostics=diag,
    )
    assert result.success is False
    assert result.diagnostics is not None
    assert result.diagnostics.error_code == ErrorCode.TIME_WINDOW_EXCEEDED

    # 2. 双工 RAG 凭据
    fact = PlaceFact(
        place_id="amap_poi_bj_001",
        place_name="故宫博物院",
        city="北京",
        opening_hours="08:30-17:00",
        booking_policy="需提前7天20:00在官方小程序抢票",
        is_open_on_date=True,
        verification_status=VerificationStatus.VERIFIED,
        source="amap",
        applicable_date="2026-10-01",
        confidence_score=0.95,
        evidence_snippet="官方小程序预约日历显示 2026-10-01 正常开放预订",
    )
    assert fact.verification_status == VerificationStatus.VERIFIED

    # 3. 否定证据 (存疑未决)
    unsure_fact = PlaceFact(
        place_name="某小众古建展馆",
        city="北京",
        verification_status=VerificationStatus.NEEDS_CONFIRMATION,
        evidence_snippet="未搜到闭馆公告，但官方电话无人接听且无在线售票公示",
    )
    assert unsure_fact.verification_status == VerificationStatus.NEEDS_CONFIRMATION
