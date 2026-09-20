"""确定性算法诊断与自愈错误信号模型

为规划工具提供详细的结构化失败成因，打破“仅返回布尔失败”的传统局限，
驱动 Repair/Critic Agent 精准执行自愈动作或向用户清晰解释冲突。
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Literal
from pydantic import BaseModel, Field


class ErrorCode(str, Enum):
    """算法与物理规则错误代码"""
    TIME_WINDOW_EXCEEDED = "TIME_WINDOW_EXCEEDED"     # 单日行程游览与通勤总时长超过起止时间窗
    BUDGET_EXCEEDED = "BUDGET_EXCEEDED"               # 门票/酒店/城际交通总费用超出预算上限
    FACT_CONFLICT_CLOSED = "FACT_CONFLICT_CLOSED"     # 景点与日期发生物理闭馆冲突 (如周一闭馆)
    VENUE_CLOSED = "FACT_CONFLICT_CLOSED"             # 闭馆冲突别名 (向后兼容)
    DETOUR_TOO_LARGE = "DETOUR_TOO_LARGE"             # 景点间折返距离过大 (远郊或规划不合理)
    HOTEL_DISTANCE_EXCEEDED = "HOTEL_DISTANCE_EXCEEDED" # 酒店至景点超过最大通勤舒适圈
    TICKET_UNAVAILABLE = "TICKET_UNAVAILABLE"         # 门票售罄或需提前预约但窗口已过


class DiagnosticSeverity(str, Enum):
    """诊断信号严重程度"""
    HARD_FAIL = "HARD_FAIL"         # 硬伤：物理不可行，必须由 Repair Agent 修复或人工介入
    SOFT_WARNING = "SOFT_WARNING"   # 软伤：可降级或带黄色预警通过 (如事实存疑待核实)
    WARNING = "SOFT_WARNING"        # 别名兼容


class DiagnosticSignal(BaseModel):
    """强类型算法诊断信号"""
    error_code: ErrorCode
    day_index: int = 0
    severity: DiagnosticSeverity = DiagnosticSeverity.HARD_FAIL
    summary: str = ""
    details: dict[str, Any] = Field(default_factory=dict)
    conflicting_items: list[str] = Field(default_factory=list)      # 导致冲突的景点或酒店名称
    immutable_constraints: list[str] = Field(default_factory=list)  # 用户锁定的不可变项 (禁止自动删减)
    attempted_actions: list[str] = Field(default_factory=list)      # 算法层已尝试过的手段 (如 2-opt 逆序调换仍超限)
    actionable_suggestions: list[str] = Field(default_factory=list) # 建议的恢复动作 (如 "建议缩减景点" 或 "放宽起止时间")


class RouteSolverResult(BaseModel):
    """路径规划算法标准化返回载荷"""
    success: bool = True
    route: list[dict[str, Any]] = Field(default_factory=list)
    total_min: int = 0
    total_ticket: int = 0
    exceeds_day: bool = False
    diagnostics: DiagnosticSignal | None = None
