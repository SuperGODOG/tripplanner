"""会话三轨状态与需求模型

实现对话历史、当前生效需求与已提交行程的三轨解耦。
支持槽位来源追溯、改口版本追踪、显式锁定项保护与向既有 TripPlannerState 的向后兼容转换。
"""
from __future__ import annotations

from enum import Enum
from typing import Any
from pydantic import BaseModel, Field


class SlotOrigin(str, Enum):
    """槽位来源类型"""
    USER_EXPLICIT = "user_explicit"     # 用户直接自然语言输入或点击选项 (最高优先级)
    MODEL_INFERRED = "model_inferred"   # 模型依据上下文合理推断 (候选，易被覆盖)
    DEFAULT_VALUE = "default_value"     # 系统安全默认兜底值 (最低优先级)


class PreferenceScope(str, Enum):
    """偏好生命周期作用域"""
    TRIP_TRANSIENT = "trip_transient"   # 仅对本次行程有效 (如"这次想住好点")
    LONG_TERM_USER = "long_term_user"   # 长期用户画像偏好 (如"平时一直吃素")
    SYSTEM_DEFAULT = "system_default"   # 系统默认作用域


class RequirementSlot(BaseModel):
    """单条需求槽位状态"""
    key: str
    value: Any
    origin: SlotOrigin = SlotOrigin.DEFAULT_VALUE
    scope: PreferenceScope = PreferenceScope.TRIP_TRANSIENT
    confirmed_by_user: bool = False
    overridden_at_revision: int | None = None
    previous_values: list[Any] = Field(default_factory=list)


class EffectiveRequirements(BaseModel):
    """当前有效需求聚合根

    管理版本修订号 revision_id 与各槽位的最新值。
    用户每次明确改口时，自增 revision_id 并记录覆盖轨迹。
    """
    revision_id: int = 1
    slots: dict[str, RequirementSlot] = Field(default_factory=dict)
    locked_items: list[str] = Field(default_factory=list)  # 显式锁定的 POI 名称或酒店
    conflicts: list[str] = Field(default_factory=list)     # 待澄清的冲突说明

    def set_slot(
        self,
        key: str,
        value: Any,
        origin: SlotOrigin = SlotOrigin.USER_EXPLICIT,
        scope: PreferenceScope = PreferenceScope.TRIP_TRANSIENT,
        confirmed: bool = False,
    ) -> RequirementSlot:
        """更新槽位值，若发生改口则自增 revision_id 并归档旧值"""
        old_slot = self.slots.get(key)
        if old_slot is not None and old_slot.value != value:
            # 发生改口，自增修订版本
            self.revision_id += 1
            prev_history = list(old_slot.previous_values)
            prev_history.append(old_slot.value)
            new_slot = RequirementSlot(
                key=key,
                value=value,
                origin=origin,
                scope=scope,
                confirmed_by_user=confirmed,
                overridden_at_revision=self.revision_id,
                previous_values=prev_history,
            )
        else:
            new_slot = RequirementSlot(
                key=key,
                value=value,
                origin=origin,
                scope=scope,
                confirmed_by_user=confirmed,
                previous_values=old_slot.previous_values if old_slot else [],
            )
        self.slots[key] = new_slot
        return new_slot

    def get_slot_value(self, key: str, default: Any = None) -> Any:
        """安全获取槽位值"""
        slot = self.slots.get(key)
        return slot.value if slot is not None else default

    def to_trip_state_dict(self, user_id: str = "default_user") -> dict[str, Any]:
        """Adapter 适配方法：将三轨需求结构转化为与既有 TripPlannerState 兼容的字典"""
        prefs = self.get_slot_value("preferences", [])
        if isinstance(prefs, str):
            prefs = [p.strip() for p in prefs.split(",") if p.strip()]

        return {
            "user_id": user_id,
            "city": self.get_slot_value("city", "北京"),
            "days": int(self.get_slot_value("days", 3)),
            "start_date": self.get_slot_value("start_date", ""),
            "origin": self.get_slot_value("origin", ""),
            "transport_mode": self.get_slot_value("transport_mode", "高铁"),
            "preferences": prefs,
            "budget_total": self.get_slot_value("budget_total", None),
            "day_start_hour": int(self.get_slot_value("day_start_hour", 9)),
            "day_end_hour": int(self.get_slot_value("day_end_hour", 20)),
        }


class PlanVersion(BaseModel):
    """已提交的行程版本"""
    version_id: int = 1
    based_on_requirements_revision: int = 1
    days: list[dict[str, Any]] = Field(default_factory=list)
    locked_items: list[str] = Field(default_factory=list)
    algorithm_telemetry: dict[str, Any] = Field(default_factory=dict)
    status: str = "committed"  # "draft" | "committed" | "superseded"
    created_at: str = ""


class ClarificationOption(BaseModel):
    """供前端渲染的追问交互选项组件"""
    option_id: str
    label: str
    action_type: str  # "SET_SLOT" | "REMOVE_POI" | "EXTEND_TIME" | "CUSTOM_INPUT"
    payload: dict[str, Any] = Field(default_factory=dict)


class ClarificationPrompt(BaseModel):
    """澄清挂起事件载荷"""
    prompt_text: str
    missing_slots: list[str] = Field(default_factory=list)
    options: list[ClarificationOption] = Field(default_factory=list)
    allow_custom_input: bool = True
    can_use_default: bool = True


class SessionState(BaseModel):
    """全局会话三轨状态容器"""
    session_id: str
    user_id: str
    history: list[dict[str, str]] = Field(default_factory=list)  # [{"role": "user"|"assistant", "content": ...}]
    requirements: EffectiveRequirements = Field(default_factory=EffectiveRequirements)
    current_plan: PlanVersion | None = None
    pending_clarification: ClarificationPrompt | None = None
