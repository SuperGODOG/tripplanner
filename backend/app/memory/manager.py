"""记忆管理器

核心算法:
1. 领域分类 + 标签提取
2. 频率加成: 同类偏好出现越多，权重越高
3. 异常检测 (Alex 案例): 偏离同类记忆统计分布的条目自动降权
4. 衰减更新 + Top-N 排序 + 去重持久化

面试亮点:
  "我们不是简单存/取记忆，而是做了统计信号处理——
   频率加成让长期偏好浮上来，异常检测让偶然行为沉下去。
   这保证了 Alex 陪老板住一次豪华酒店不会永久改变他的经济型画像。"
"""
import json
import os
from datetime import datetime
from collections import Counter
from .models import MemoryEntry
from .classifier import classify, extract_tags, DOMAIN_WEIGHTS


class MemoryManager:
    """
    记忆管理器。

    Top-N 策略: 只保留权重最高的 N 条记忆
    持久化: JSON 文件（data/memory.json）
    """

    def __init__(self, storage_path: str = "data/memory.json", top_n: int = 30):
        self.storage_path = storage_path
        self.top_n = top_n
        self._entries: list[MemoryEntry] = []
        self.trip_count: int = 0       # 行程计数（画像需 >= 5 次才显示）
        self._load()

    # ================================================================
    # 公共接口
    # ================================================================

    def add(self, text: str, interaction_type: str = "observe") -> MemoryEntry:
        """
        添加一条记忆。

        interaction_type:
          "observe" — 观察到的行为（权重 1.0）
          "confirm" — 用户确认过的（权重 +0.2）
          "modify"  — 用户主动修改的（权重 +0.5）
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
            entry.interaction_weight = 1.5
        elif interaction_type == "confirm":
            entry.interaction_weight = 1.2

        # ── 核心算法: 频率加成 + 异常检测 ──
        self._compute_frequency_boost(entry)
        self._compute_outlier_penalty(entry)

        self._entries.append(entry)
        self._update_decay_weights()
        self._prune_and_dedup()
        self._save()

        return entry

    def get_profile(self) -> dict:
        """
        获取用户画像。

        返回结构化摘要，可直接注入 LangGraph State
        供 Planner Agent 在生成行程时参考。
        """
        self._update_decay_weights()

        profile = {
            "cities": [],
            "diet": [],
            "transport": [],
            "intercity_mode": None,  # 城际出行方式（高铁/飞机/自驾）
            "distance_pref": None,   # 常出行的距离（短途/中途/长途）
            "pace": None,
            "accommodation": None,
            "budget_tier": None,
            "interests": [],
            "budget_range": None,
            "hotel_tier": None,
        }

        # 统计各标签的出现频率（仅高权重记忆）
        weighted_entries = sorted(self._entries, key=lambda e: e.final_weight, reverse=True)
        top_entries = [e for e in weighted_entries if e.final_weight >= 0.3]

        tag_counter = Counter()
        budget_values = []  # 收集所有价格标签用于计算预算区间

        for entry in top_entries:
            for tag in entry.tags:
                prefix = tag.split(":", 1)[0]
                value = tag.split(":", 1)[1] if ":" in tag else ""

                if prefix == "城市":
                    if value not in profile["cities"]:
                        profile["cities"].append(value)
                elif prefix == "饮食":
                    if value not in profile["diet"]:
                        profile["diet"].append(value)
                elif prefix == "交通":
                    if value not in profile["transport"]:
                        profile["transport"].append(value)
                elif prefix == "节奏":
                    if not profile["pace"]:
                        profile["pace"] = value
                elif prefix == "住宿":
                    if not profile["accommodation"]:
                        profile["accommodation"] = value
                        profile["hotel_tier"] = value
                elif prefix == "预算":
                    if not profile["budget_tier"]:
                        profile["budget_tier"] = value
                elif prefix == "景点":
                    if value not in profile["interests"]:
                        profile["interests"].append(value)
                elif prefix == "出行方式":
                    if not profile["intercity_mode"]:
                        profile["intercity_mode"] = value
                elif prefix == "距离":
                    if not profile["distance_pref"]:
                        profile["distance_pref"] = value
                elif prefix == "价格":
                    try:
                        parts = value.split("-")
                        lo, hi = int(parts[0]), int(parts[1])
                        budget_values.append((lo + hi) / 2)
                    except (ValueError, IndexError):
                        pass

            # 兼容旧格式
            if entry.category == "preference" and entry.content not in profile.get("_raw_prefs", []):
                pass  # 新系统不再需要文本偏好列表

        # 预算区间: 取所有价格标签的中位数附近
        if budget_values:
            budget_values.sort()
            median = budget_values[len(budget_values) // 2]
            profile["budget_range"] = f"{int(median * 0.7)}-{int(median * 1.3)}元"

        # 酒店档次推断
        if budget_values:
            median = budget_values[len(budget_values) // 2]
            if median <= 400:
                profile["hotel_tier"] = "经济型"
            elif median < 800:
                profile["hotel_tier"] = "舒适型"
            else:
                profile["hotel_tier"] = "豪华型"

        return profile

    # ================================================================
    # 核心算法
    # ================================================================

    def _compute_frequency_boost(self, new_entry: MemoryEntry):
        """
        频率加成: 同类标签出现次数越多，权重越高。

        公式: frequency_boost = 1.0 + min(count * 0.15, 1.0)
        效果:
          出现 1 次 → boost = 1.15
          出现 5 次 → boost = 1.75
          出现 7+ 次 → boost = 2.0 (封顶)
        """
        tag_counter = Counter()
        for entry in self._entries:
            for tag in entry.tags:
                tag_counter[tag] += 1

        max_count = 0
        for tag in new_entry.tags:
            if tag_counter[tag] > max_count:
                max_count = tag_counter[tag]

        # boost 随频次增长，但有上限
        new_entry.frequency_boost = 1.0 + min(max_count * 0.15, 1.0)

    def _compute_outlier_penalty(self, new_entry: MemoryEntry):
        """
        异常检测（数值型 + 分类型）。

        数值型（价格标签）: IQR 方法
          Alex 案例: 5 次 300-500 → 1 次 1500-2000 → outlier_penalty = 0.3

        分类型（饮食/交通/节奏/住宿/预算/景点）: 频率比方法
          如: 5 次"不吃辣" → 1 次"爱吃辣" → outlier_penalty = 0.3
          算法: 如果新标签的出现频次 < 同维度众数频次 × 0.3 → 异常
        """
        # ── 数值型: IQR 异常检测 ──
        price_tags = [t for t in new_entry.tags if t.startswith("价格:")]
        if price_tags:
            self._check_numerical_outlier(new_entry, price_tags)
            return

        # ── 分类型: 频率比异常检测 ──
        self._check_categorical_outlier(new_entry)

    def _check_numerical_outlier(self, new_entry: MemoryEntry, price_tags: list[str]):
        """数值型 IQR 异常检测（价格标签）"""
        same_cat_prices = []
        for entry in self._entries:
            if entry.category == new_entry.category:
                for tag in entry.tags:
                    if tag.startswith("价格:"):
                        try:
                            parts = tag.split(":", 1)[1].split("-")
                            same_cat_prices.append((int(parts[0]) + int(parts[1])) / 2)
                        except (ValueError, IndexError):
                            pass

        if len(same_cat_prices) < 3:
            return

        try:
            parts = price_tags[0].split(":", 1)[1].split("-")
            new_price = (int(parts[0]) + int(parts[1])) / 2
        except (ValueError, IndexError):
            return

        sorted_prices = sorted(same_cat_prices)
        n = len(sorted_prices)
        q1, q3 = sorted_prices[n // 4], sorted_prices[3 * n // 4]
        iqr = q3 - q1

        if iqr == 0:
            iqr = max(q1 * 0.1, 50)

        if new_price < q1 - 2 * iqr or new_price > q3 + 2 * iqr:
            new_entry.outlier_penalty = 0.3

    def _check_categorical_outlier(self, new_entry: MemoryEntry):
        """
        分类型异常检测: 频率比方法。

        维度前缀:
          饮食 / 交通 / 节奏 / 住宿 / 预算 / 景点

        算法:
          1. 找到新记忆每个标签所属的维度
          2. 统计该维度下所有历史标签的出现频次
          3. 找到众数（出现最多的值）的频次
          4. 如果新标签的频次 < 众数频次 × 0.3 → 标记为异常

        示例:
          历史: 5 次"饮食:不吃辣", 1 次"饮食:清淡"
          新标签: "饮食:爱吃辣"
          众数频次 = 5（不吃辣）
          新标签频次 = 0（爱吃辣从未出现）
          0 < 5 × 0.3 → 异常 → outlier_penalty = 0.3
        """
        CATEGORICAL_PREFIXES = ["饮食", "交通", "节奏", "住宿", "预算", "景点", "出行方式", "距离"]

        for tag in new_entry.tags:
            prefix = tag.split(":", 1)[0]
            if prefix not in CATEGORICAL_PREFIXES:
                continue

            # 统计该维度下所有值的历史频次
            dim_counter = Counter()
            for entry in self._entries:
                for t in entry.tags:
                    if t.startswith(prefix + ":"):
                        dim_counter[t] += 1

            if not dim_counter:
                return  # 该维度无历史数据，不检测

            # 众数频次
            mode_count = dim_counter.most_common(1)[0][1]

            # 新标签的频次
            new_count = dim_counter.get(tag, 0)

            # 阈值：频次低于众数的 30% → 异常
            threshold = max(mode_count * 0.3, 1)
            if new_count < threshold and mode_count >= 3:
                new_entry.outlier_penalty = 0.3
                return  # 一个维度检测到异常就够了

    # ================================================================
    # 维护
    # ================================================================

    def _update_decay_weights(self):
        """更新所有记忆的时间衰减权重"""
        now = datetime.now()
        for entry in self._entries:
            if entry.last_seen_at:
                last = datetime.fromisoformat(entry.last_seen_at)
                days_ago = max(0, (now - last).days)
                entry.decay_weight = pow(0.95, days_ago)

    def _prune_and_dedup(self):
        """排序、去重、裁剪到 Top-N"""
        self._entries.sort(key=lambda e: e.final_weight, reverse=True)

        seen = set()
        deduped = []
        for entry in self._entries:
            short = entry.content[:30]
            if short not in seen:
                seen.add(short)
                deduped.append(entry)

        self._entries = deduped[:self.top_n]

    def _save(self):
        """持久化到 JSON"""
        os.makedirs(os.path.dirname(self.storage_path), exist_ok=True)
        data = []
        for e in self._entries:
            data.append({
                "content": e.content,
                "category": e.category,
                "tags": e.tags,
                "domain_weight": e.domain_weight,
                "decay_weight": e.decay_weight,
                "interaction_weight": e.interaction_weight,
                "frequency_boost": e.frequency_boost,
                "outlier_penalty": e.outlier_penalty,
                "final_weight": e.final_weight,
                "created_at": e.created_at,
                "last_seen_at": e.last_seen_at,
            })
        with open(self.storage_path, "w", encoding="utf-8") as f:
            json.dump({"trip_count": self.trip_count, "entries": data}, f, ensure_ascii=False, indent=2)

    def _load(self):
        """从 JSON 恢复"""
        if not os.path.exists(self.storage_path):
            return
        with open(self.storage_path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        # 兼容旧格式
        if isinstance(raw, list):
            data = raw
            self.trip_count = 0
        else:
            data = raw.get("entries", [])
            self.trip_count = raw.get("trip_count", 0)
        for item in data:
            entry = MemoryEntry(
                content=item["content"],
                category=item["category"],
                tags=item.get("tags", []),
                domain_weight=item.get("domain_weight", 1.0),
                decay_weight=item.get("decay_weight", 1.0),
                interaction_weight=item.get("interaction_weight", 1.0),
                frequency_boost=item.get("frequency_boost", 1.0),
                outlier_penalty=item.get("outlier_penalty", 1.0),
                created_at=item.get("created_at", ""),
                last_seen_at=item.get("last_seen_at", ""),
            )
            self._entries.append(entry)


# 全局单例
_memory: MemoryManager | None = None


def get_memory() -> MemoryManager:
    global _memory
    if _memory is None:
        _memory = MemoryManager()
    return _memory
