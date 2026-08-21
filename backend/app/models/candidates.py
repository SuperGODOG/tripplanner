"""结构化 POI 候选模型 — 数据从 MCP 到 Planner 全程保持字段化，不过字符串协议。

设计原则:
- id: 稳定哈希（name+district+坐标），用于多偏好搜索去重与结果溯源
- source: 数据来源标记，支持"POI 可溯源率"指标
- PoiCandidate → HotelCandidate 继承扩展，不另起炉灶
"""
from hashlib import md5

from pydantic import BaseModel, Field


def _stable_id(name: str, district: str, lng: float, lat: float) -> str:
    raw = f"{name}|{district}|{round(lng, 4)}|{round(lat, 4)}"
    return md5(raw.encode("utf-8")).hexdigest()[:12]


class PoiCandidate(BaseModel):
    """景点/美食等普通 POI 候选"""

    name: str
    lng: float = 0.0
    lat: float = 0.0
    address: str = ""
    district: str = ""          # 区县（adname）
    category: str = ""          # 景点类别
    price: float | None = None  # 参考价（门票/人均），高德提供则填
    source: str = "amap"        # 数据来源
    id: str = Field(default="", description="稳定 ID，构造时自动生成")

    def model_post_init(self, __context) -> None:
        if not self.id:
            self.id = _stable_id(self.name, self.district, self.lng, self.lat)


class HotelCandidate(PoiCandidate):
    """酒店候选"""

    rating: str = ""
    price_range: str = ""
    hotel_type: str = ""        # 经济型/舒适型/高档/豪华
