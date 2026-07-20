"""记忆数据模型

权重公式（修正版）:
  final_weight = domain × decay × interaction × frequency_boost × outlier_penalty

新增因子:
  frequency_boost: 该偏好在历史上出现的频次越高，权重越大
  outlier_penalty: 如果该记忆是统计异常值（偏离同类记忆的众数），自动降权

场景（Alex 案例）:
  Alex 通常选经济型酒店（300-500元，出现了 5 次）
  某次陪老板出差选了豪华酒店（1500+元，出现了 1 次）
  → 豪华酒店被检测为异常值 → outlier_penalty = 0.3
  → 最终权重远低于经济型偏好
  → 用户画像中经济型酒店占据主导
"""
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class MemoryEntry:
    """单条记忆"""

    content: str                    # 原始文本
    category: str                   # 领域: attraction/hotel/weather/preference/general
    tags: list[str] = field(default_factory=list)

    # 权重因子
    domain_weight: float = 1.0      # 领域权重（景点2x > 酒店1.5x > 天气1x）
    decay_weight: float = 1.0       # 时间衰减（指数衰减）
    interaction_weight: float = 1.0  # 交互修正（修改+0.5 / 确认+0.2）
    frequency_boost: float = 1.0    # 频率加成（同类偏好出现越多，权重越高）
    outlier_penalty: float = 1.0    # 异常惩罚（统计异常值时降权）

    # 元数据
    created_at: str = ""
    last_seen_at: str = ""

    @property
    def final_weight(self) -> float:
        """最终权重 = 领域 × 衰减 × 交互 × 频率 × 异常惩罚"""
        return (
            self.domain_weight
            * self.decay_weight
            * self.interaction_weight
            * self.frequency_boost
            * self.outlier_penalty
        )
