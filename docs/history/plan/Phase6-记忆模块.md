# Phase 6: 自定义记忆模块（用户画像）

**目标**：实现跨会话的用户画像系统——记录偏好、加权排序、冲突检测、去重持久化。

**前置条件**：Phase 5 通过（API 能跑通）

**预计时间**：3-4 天 | **代码量**：~200 行

---

## 6.1 为什么不用框架的 MemoryTool？

HelloAgents 的 MemoryTool 提供了基础的记忆存储/检索。但我们要的是**用户画像**——不只是记住"用户说过什么"，而是：

1. 给不同类别的记忆不同权重（景点偏好比天气备注更重要）
2. 时间衰减（一周前的偏好权重低于昨天的）
3. 交叉验证（用户偶然说一次"吃辣"不算，多次确认才写入画像）
4. 冲突检测（新记忆和已有偏好矛盾时降低权重）

这 4 点是面试中的区分度——证明你理解"记忆不是简单的存/取，是信号处理问题"。

---

## 6.2 记忆数据模型

创建 `backend/app/memory/models.py`：

```python
"""记忆数据模型"""
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class MemoryEntry:
    """单条记忆"""
    content: str                # 记忆内容（如"偏好地铁出行"）
    category: str               # 领域: weather/attraction/hotel/preference/general
    tags: list[str] = field(default_factory=list)  # 标签: ["北京", "交通"]

    # 权重计算因子
    domain_weight: float = 1.0  # 领域权重
    decay_weight: float = 1.0   # 衰减权重（由时间计算）
    interaction_weight: float = 1.0  # 交互权重（修正+0.5/确认+0.2）

    # 时间
    created_at: str = ""        # 创建时间 ISO
    last_seen_at: str = ""      # 最后出现时间

    # 冲突
    conflict_flag: bool = False # 是否与已有偏好冲突

    @property
    def final_weight(self) -> float:
        """最终权重 = 领域 × 衰减 × 交互修正 × 冲突惩罚"""
        conflict_penalty = 0.5 if self.conflict_flag else 1.0
        return (
            self.domain_weight
            * self.decay_weight
            * self.interaction_weight
            * conflict_penalty
        )
```

---

## 6.3 领域分类器

创建 `backend/app/memory/classifier.py`：

```python
"""记忆分类器——按领域给对话内容打标签"""
from typing import Optional

# 领域权重表
DOMAIN_WEIGHTS = {
    "attraction": 2.0,   # 景点偏好最重要
    "hotel": 1.5,        # 酒店其次
    "preference": 1.5,   # 通用偏好
    "weather": 1.0,      # 天气备注权重低
    "general": 1.0,      # 通用
}

# 关键词 → 领域映射
KEYWORD_MAP = {
    "attraction": ["景点", "景区", "公园", "博物馆", "故宫", "长城", "游览", "参观"],
    "hotel": ["酒店", "宾馆", "住宿", "民宿", "入住", "退房"],
    "weather": ["天气", "温度", "下雨", "晴天", "多云", "穿衣", "外套", "防晒"],
    "preference": ["喜欢", "不喜欢", "偏好", "推荐", "不要", "想", "希望", "怕辣", "吃辣"],
}


def classify(text: str) -> str:
    """根据关键词给文本分类"""
    scores = {cat: 0 for cat in DOMAIN_WEIGHTS}

    for category, keywords in KEYWORD_MAP.items():
        for kw in keywords:
            if kw in text:
                scores[category] += 1

    # 返回得分最高的类别
    best = max(scores, key=scores.get)
    if scores[best] == 0:
        return "general"
    return best


def extract_tags(text: str) -> list[str]:
    """提取标签（城市、价格区间、饮食偏好等）"""
    tags = []

    # 城市提取（简单关键词匹配，生产环境可用 NER）
    cities = ["北京", "上海", "广州", "深圳", "杭州", "成都", "重庆", "西安", "南京", "武汉"]
    for city in cities:
        if city in text:
            tags.append(f"城市:{city}")

    # 饮食偏好
    if any(w in text for w in ["不吃辣", "怕辣", "忌辣"]):
        tags.append("饮食:不吃辣")
    elif any(w in text for w in ["吃辣", "爱吃辣", "辣"]):
        tags.append("饮食:吃辣")

    # 交通方式
    if "地铁" in text:
        tags.append("交通:地铁")
    elif "打车" in text or "出租车" in text:
        tags.append("交通:打车")
    elif "自驾" in text:
        tags.append("交通:自驾")

    # 价格区间
    import re
    price_match = re.search(r'(\d+)-(\d+)元', text)
    if price_match:
        tags.append(f"价格:{price_match.group(1)}-{price_match.group(2)}元")

    return tags
```

---

## 6.4 记忆管理器

创建 `backend/app/memory/manager.py`：

```python
"""记忆管理器——存储、查询、去重、图画像构建"""
import json
import os
from datetime import datetime, timedelta
from .models import MemoryEntry
from .classifier import classify, extract_tags, DOMAIN_WEIGHTS


class MemoryManager:
    """
    记忆管理器。

    存储路径: backend/data/memory.json
    Top-N 策略：只保留权重最高的 N 条记忆
    """

    def __init__(self, storage_path: str = "data/memory.json", top_n: int = 20):
        self.storage_path = storage_path
        self.top_n = top_n
        self._entries: list[MemoryEntry] = []
        self._load()

    # ===== 公共接口 =====

    def add(self, text: str, interaction_type: str = "observe") -> MemoryEntry:
        """
        添加一条记忆。

        interaction_type:
        - "observe": 观察到的用户行为
        - "confirm": 用户确认过的
        - "modify": 用户主动修改的
        """
        now = datetime.now().isoformat()

        entry = MemoryEntry(
            content=text,
            category=classify(text),
            tags=extract_tags(text),
            domain_weight=DOMAIN_WEIGHTS.get(classify(text), 1.0),
            created_at=now,
            last_seen_at=now,
        )

        # 交互权重
        if interaction_type == "modify":
            entry.interaction_weight = 1.5  # 修改过的记忆权重最高
        elif interaction_type == "confirm":
            entry.interaction_weight = 1.2

        # 冲突检测：新记忆是否与已有偏好冲突
        entry.conflict_flag = self._detect_conflict(entry)

        self._entries.append(entry)
        self._update_decay_weights()
        self._sort_and_prune()
        self._save()

        return entry

    def get_profile(self) -> dict:
        """
        获取用户画像——返回 Top-N 记忆的结构化摘要。
        供 Planner Agent 在生成行程时参考。
        """
        self._update_decay_weights()

        profile = {
            "preferences": [],
            "cities": [],
            "food": [],
            "transport": [],
            "budget": [],
        }

        for entry in sorted(self._entries, key=lambda e: e.final_weight, reverse=True)[:self.top_n]:
            if entry.final_weight < 0.3:  # 权重太低的忽略
                continue

            for tag in entry.tags:
                if tag.startswith("城市:"):
                    city = tag.split(":", 1)[1]
                    if city not in profile["cities"]:
                        profile["cities"].append(city)
                elif tag.startswith("饮食:"):
                    food = tag.split(":", 1)[1]
                    if food not in profile["food"]:
                        profile["food"].append(food)
                elif tag.startswith("交通:"):
                    t = tag.split(":", 1)[1]
                    if t not in profile["transport"]:
                        profile["transport"].append(t)
                elif tag.startswith("价格:"):
                    p = tag.split(":", 1)[1]
                    if p not in profile["budget"]:
                        profile["budget"].append(p)

            if entry.category == "preference":
                profile["preferences"].append(entry.content)

        return profile

    # ===== 内部方法 =====

    def _update_decay_weights(self):
        """更新所有记忆的衰减权重"""
        now = datetime.now()

        for entry in self._entries:
            if entry.last_seen_at:
                last = datetime.fromisoformat(entry.last_seen_at)
                days_ago = (now - last).days
                # 指数衰减: e^(-0.05 * days)，约 14 天半衰
                entry.decay_weight = pow(0.95, days_ago)

    def _detect_conflict(self, new_entry: MemoryEntry) -> bool:
        """检测新记忆是否与已有高权重记忆冲突"""
        for old in self._entries:
            if old.final_weight < 1.0:
                continue

            # 饮食偏好冲突检测
            new_food = [t for t in new_entry.tags if t.startswith("饮食:")]
            old_food = [t for t in old.tags if t.startswith("饮食:")]
            if new_food and old_food:
                new_val = new_food[0].split(":", 1)[1]
                old_val = old_food[0].split(":", 1)[1]
                if new_val != old_val:
                    return True  # 冲突！

        return False

    def _sort_and_prune(self):
        """按最终权重降序排列，裁剪到 Top-N，去重"""
        # 排序
        self._entries.sort(key=lambda e: e.final_weight, reverse=True)

        # 去重：相似内容的只保留权重最高的
        seen_contents = set()
        deduped = []
        for entry in self._entries:
            # 简单去重：内容前 20 字符相同视为重复
            short = entry.content[:20]
            if short not in seen_contents:
                seen_contents.add(short)
                deduped.append(entry)

        # 裁剪
        self._entries = deduped[:self.top_n]

    def _save(self):
        """持久化到 JSON 文件"""
        os.makedirs(os.path.dirname(self.storage_path), exist_ok=True)

        data = []
        for entry in self._entries:
            data.append({
                "content": entry.content,
                "category": entry.category,
                "tags": entry.tags,
                "domain_weight": entry.domain_weight,
                "decay_weight": entry.decay_weight,
                "interaction_weight": entry.interaction_weight,
                "created_at": entry.created_at,
                "last_seen_at": entry.last_seen_at,
                "conflict_flag": entry.conflict_flag,
                "final_weight": entry.final_weight,
            })

        with open(self.storage_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def _load(self):
        """从 JSON 文件恢复记忆"""
        if not os.path.exists(self.storage_path):
            return

        with open(self.storage_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        for item in data:
            entry = MemoryEntry(
                content=item["content"],
                category=item["category"],
                tags=item.get("tags", []),
                domain_weight=item.get("domain_weight", 1.0),
                decay_weight=item.get("decay_weight", 1.0),
                interaction_weight=item.get("interaction_weight", 1.0),
                created_at=item.get("created_at", ""),
                last_seen_at=item.get("last_seen_at", ""),
                conflict_flag=item.get("conflict_flag", False),
            )
            self._entries.append(entry)


# 全局单例
_memory: MemoryManager | None = None


def get_memory() -> MemoryManager:
    global _memory
    if _memory is None:
        _memory = MemoryManager()
    return _memory
```

---

## 6.5 集成到 API

修改 `backend/app/api/trip.py`，在规划前注入用户画像：

```python
@router.post("/trip", response_model=TripPlan)
async def plan_trip(request: TripRequest):
    from ..memory.manager import get_memory

    memory = get_memory()

    # 记录本次请求到记忆
    memory.add(f"用户搜索{request.city},{request.days}天", "observe")
    if request.preferences:
        for pref in request.preferences:
            memory.add(f"偏好:{pref}", "observe")

    # 获取用户画像
    profile = memory.get_profile()

    # 将画像信息注入初始状态
    initial_state = {
        "city": request.city,
        "days": request.days,
        "preferences": request.preferences,
        "user_profile": profile,  # 新增
        # ... 其余字段不变
    }

    result = graph.invoke(initial_state)
    # ...
```

---

## 6.6 验证

```python
# test_memory.py
import sys
sys.path.insert(0, ".")

from app.memory.manager import get_memory

def test_memory():
    memory = get_memory()

    # 添加记忆
    memory.add("我不吃辣", "modify")
    memory.add("喜欢历史文化景点", "confirm")
    memory.add("偏好坐地铁出行", "observe")
    memory.add("酒店预算300-500元", "observe")

    # 测试冲突检测
    memory.add("其实我也能吃一点辣", "observe")  # 应该触发冲突

    # 获取画像
    profile = memory.get_profile()
    print("用户画像:", json.dumps(profile, ensure_ascii=False, indent=2))

    # 检查权重
    for entry in memory._entries[:5]:
        print(f"  [{entry.final_weight:.2f}] {entry.content} "
              f"(冲突:{entry.conflict_flag})")

if __name__ == "__main__":
    test_memory()
```

**Phase 6 通过标准**：
- [ ] 记忆能正确分类（景点/酒店/偏好/天气）
- [ ] 标签提取正确（城市、饮食、交通）
- [ ] 权重计算自洽（领域 × 衰减 × 交互 × 冲突）
- [ ] 冲突检测正确（"不吃辣" vs "能吃辣"）
- [ ] 持久化正常（重启后记忆不丢失）
- [ ] 用户画像能注入到行程规划中
