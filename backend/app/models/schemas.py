"""Pydantic 数据模型"""
from pydantic import BaseModel, Field


class TripRequest(BaseModel):
    """旅行规划请求"""
    origin: str = Field(default="", description="出发城市", example="上海")
    city: str = Field(..., description="目标城市", example="北京")
    days: int = Field(..., ge=1, le=14, description="旅行天数", example=3)
    start_date: str = Field(default="", description="出发日期 YYYY-MM-DD")
    transport_mode: str = Field(default="高铁", description="高铁 / 飞机 / 自驾")
    preferences: list[str] = Field(default_factory=list, example=["历史文化", "美食"])


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
