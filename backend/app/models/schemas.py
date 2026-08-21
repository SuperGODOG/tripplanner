"""Pydantic 数据模型"""
from datetime import date
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class TripRequest(BaseModel):
    """旅行规划请求"""
    user_id: UUID = Field(..., description="前端持久化的匿名用户标识")
    origin: str = Field(default="", description="出发城市", example="上海")
    city: str = Field(..., description="目标城市", example="北京")
    days: int = Field(..., ge=1, le=14, description="旅行天数", example=3)
    start_date: str = Field(default="", description="出发日期 YYYY-MM-DD")
    transport_mode: str = Field(default="高铁", description="高铁 / 飞机 / 自驾")
    preferences: list[str] = Field(default_factory=list, example=["历史文化", "美食"])
    budget_total: int | None = Field(default=None, gt=0, description="总预算；提供后作为硬约束")
    day_start_hour: int = Field(default=9, ge=6, le=12, description="每日最早开始小时")
    day_end_hour: int = Field(default=20, ge=16, le=23, description="每日最晚结束小时")

    @field_validator("start_date")
    @classmethod
    def validate_start_date(cls, value: str) -> str:
        if not value:
            return value
        try:
            parsed = date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("start_date 必须是 YYYY-MM-DD 格式的有效日期") from exc
        if parsed < date.today():
            raise ValueError("start_date 不能早于今天")
        return parsed.isoformat()


class IntercityTransport(BaseModel):
    """城际交通"""
    mode: str = "高铁"                           # 高铁/飞机/自驾
    distance_km: float = 0                       # 两地距离（公里）
    distance_category: str = ""                  # 短途/中途/长途
    estimated_cost: int = 0                      # 预估费用（元）
    duration_hours: float = 0                    # 预估时间（小时）


class TripPlan(BaseModel):
    """旅行计划响应"""
    city: str
    origin: str = ""
    start_date: str = ""
    days: list[dict] = []
    weather_info: list[dict] = []
    overall_suggestions: str = ""
    budget: dict = Field(default_factory=dict)
    intercity_transport: IntercityTransport | None = None
    user_profile: dict = Field(default_factory=dict)
    is_fallback: bool = False
    errors: list[str] = []
