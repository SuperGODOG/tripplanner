"""双工 RAG 与动态时效事实核验数据模型

解耦“半静态攻略游玩心得”与“高时效官方开放事实”。
贯彻“否定证据严谨判定”准则，防止大模型在缺乏闭馆公告时擅自脑补。
"""
from __future__ import annotations

from enum import Enum
from pydantic import BaseModel, Field


class VerificationStatus(str, Enum):
    """地点动态事实核验状态"""
    VERIFIED = "VERIFIED"                       # 官方/地图明确确认营业或可预约
    NEEDS_CONFIRMATION = "NEEDS_CONFIRMATION"   # 存疑或缺乏明确无误凭据 (软性黄色预警)
    CONFLICT = "CONFLICT"                       # 存在硬性冲突 (如遇周一闭馆或整修停业)
    UNKNOWN = "UNKNOWN"                         # 无法查证该地点任何有效事实


class PlaceFact(BaseModel):
    """地点动态事实结构化凭据"""
    place_id: str = ""
    place_name: str
    city: str
    opening_hours: str | None = None
    booking_policy: str | None = None           # 预约规则 (如"提前7天公众号实名抢票")
    is_open_on_date: bool | None = None
    verification_status: VerificationStatus = VerificationStatus.UNKNOWN
    source: str = "amap"                        # 数据来源 (amap / official / search)
    retrieved_at: str = ""                      # 抓取与核验时间戳
    applicable_date: str = ""                   # 目标游览日期 (YYYY-MM-DD)
    confidence_score: float = Field(default=1.0, ge=0.0, le=1.0)
    evidence_snippet: str = ""                  # 支撑判断的原始证据片段


class GuideReference(BaseModel):
    """攻略知识库引用凭据 (小红书风精选经验)"""
    attraction: str
    guide: str
    city: str
    tag: str = "玩法"                           # "玩法" | "避坑" | "拍照" | "美食"
    text: str = ""
