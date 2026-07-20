"""记忆分类器与标签提取

维度设计:
  饮食偏好 — 不吃辣/爱吃辣/清淡/重口味/当地特色/国际美食
  交通方式 — 地铁优先/打车优先/自驾/公共交通
  旅行节奏 — 悠闲慢游/适中/紧凑高效
  住宿类型 — 经济型/中端型/高端型/豪华型
  预算偏好 — 穷游/经济适用/舒适享受/奢华体验
  景点偏好 — 历史文化/自然风光/美食/购物/亲子
"""
import re

DOMAIN_WEIGHTS = {
    "attraction": 2.0,
    "hotel": 1.5,
    "preference": 1.5,
    "weather": 1.0,
    "general": 1.0,
}

KEYWORD_MAP = {
    "attraction": ["景点", "景区", "公园", "博物馆", "故宫", "长城", "游览", "参观", "爬山", "海边", "历史文化", "自然风光"],
    "hotel": ["酒店", "宾馆", "住宿", "民宿", "入住", "退房", "经济型", "中端型", "高端型", "豪华型"],
    "weather": ["天气", "温度", "下雨", "晴天", "多云", "穿衣", "外套", "防晒"],
    "preference": ["喜欢", "不喜欢", "偏好", "推荐", "不要", "想", "希望", "怕辣", "吃辣", "不吃", "地铁", "打车", "自驾", "穷游", "预算"],
}

# ── 维度标签映射 ──
DIET_TAGS = {
    "不吃辣": "饮食:不吃辣", "怕辣": "饮食:不吃辣", "忌辣": "饮食:不吃辣",
    "爱吃辣": "饮食:爱吃辣", "吃辣": "饮食:爱吃辣",
    "清淡": "饮食:清淡", "重口味": "饮食:重口味",
    "当地特色": "饮食:当地特色", "国际美食": "饮食:国际美食",
}
TRANSPORT_TAGS = {
    "地铁优先": "交通:地铁优先", "地铁": "交通:地铁优先",
    "打车优先": "交通:打车优先", "打车": "交通:打车优先",
    "自驾": "交通:自驾", "公共交通": "交通:公共交通",
}
PACE_TAGS = {
    "悠闲慢游": "节奏:悠闲慢游", "适中": "节奏:适中", "紧凑高效": "节奏:紧凑高效",
}
HOTEL_TAGS = {
    "经济型酒店": "住宿:经济型", "经济型": "住宿:经济型",
    "中端型酒店": "住宿:中端型", "中端型": "住宿:中端型",
    "高端型酒店": "住宿:高端型", "高端型": "住宿:高端型",
    "豪华型酒店": "住宿:豪华型", "豪华型": "住宿:豪华型",
}
BUDGET_TAGS = {
    "穷游": "预算:穷游", "经济适用": "预算:经济适用",
    "舒适享受": "预算:舒适享受", "奢华体验": "预算:奢华体验",
}
INTEREST_TAGS = {
    "历史文化": "景点:历史文化", "自然风光": "景点:自然风光",
    "美食": "景点:美食", "购物": "景点:购物", "亲子": "景点:亲子",
}


def classify(text: str) -> str:
    scores = {cat: 0 for cat in DOMAIN_WEIGHTS}
    for category, keywords in KEYWORD_MAP.items():
        for kw in keywords:
            if kw in text:
                scores[category] += 1
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "general"


def extract_tags(text: str) -> list[str]:
    """从文本中提取结构化标签（多维度）"""
    tags = []

    # ── 城市 ──
    cities = ["北京", "上海", "广州", "深圳", "杭州", "成都", "重庆", "西安", "南京", "武汉", "苏州", "长沙"]
    for city in cities:
        if city in text:
            tags.append(f"城市:{city}")

    # ── 饮食 ──
    for key, tag in DIET_TAGS.items():
        if key in text:
            tags.append(tag)
            break

    # ── 交通 ──
    for key, tag in TRANSPORT_TAGS.items():
        if key in text:
            tags.append(tag)
            break

    # ── 出行方式（城际） ──
    for mode in ["高铁", "飞机", "自驾"]:
        if mode in text:
            tags.append(f"出行方式:{mode}")
            break

    # ── 距离分类 ──
    for cat in ["短途", "中途", "长途"]:
        if cat in text:
            tags.append(f"距离:{cat}")
            break

    # ── 节奏 ──
    for key, tag in PACE_TAGS.items():
        if key in text:
            tags.append(tag)
            break

    # ── 住宿 ──
    for key, tag in HOTEL_TAGS.items():
        if key in text:
            tags.append(tag)
            break

    # ── 预算 ──
    for key, tag in BUDGET_TAGS.items():
        if key in text:
            tags.append(tag)
            break

    # ── 景点偏好 ──
    for key, tag in INTEREST_TAGS.items():
        if key in text:
            tags.append(tag)
            break

    # ── 价格区间（数值型） ──
    price_patterns = [
        (r"(\d+)\s*-\s*(\d+)\s*元", lambda m: (int(m.group(1)), int(m.group(2)))),
        (r"预算\s*(\d+)", lambda m: (int(m.group(1)), int(m.group(1)))),
        (r"(\d+)\s*元\s*以[上下]", lambda m: (int(m.group(1)), int(m.group(1)))),
    ]
    for pattern, extractor in price_patterns:
        match = re.search(pattern, text)
        if match:
            lo, hi = extractor(match)
            tags.append(f"价格:{lo}-{hi}")
            break

    return tags
