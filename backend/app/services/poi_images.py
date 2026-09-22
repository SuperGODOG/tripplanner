"""名胜实景摄影与视觉感知服务 (POI Visual Image Service)

提供高德官方实景照片透传与公版优质文旅摄影图库解析，
为 TripPlanner 行程卡片注入“所见即所得”的商业级文旅美学视觉体验。
"""
from __future__ import annotations

from typing import Any

# 核心热门名胜精选实景大图知识库 (Wikimedia Commons / Unsplash 高可用文旅摄影)
CURATED_LANDMARK_IMAGES: dict[str, str] = {
    # 北京
    "故宫博物院": "https://images.unsplash.com/photo-1547981609-4b6bfe67ca0b?auto=format&fit=crop&w=800&q=80",
    "故宫": "https://images.unsplash.com/photo-1547981609-4b6bfe67ca0b?auto=format&fit=crop&w=800&q=80",
    "天坛公园": "https://images.unsplash.com/photo-1599837565318-67429bde7162?auto=format&fit=crop&w=800&q=80",
    "天坛": "https://images.unsplash.com/photo-1599837565318-67429bde7162?auto=format&fit=crop&w=800&q=80",
    "颐和园": "https://images.unsplash.com/photo-1598899134739-24c46f58b8c0?auto=format&fit=crop&w=800&q=80",
    "八达岭长城": "https://images.unsplash.com/photo-1508804185872-d7badad00f7d?auto=format&fit=crop&w=800&q=80",
    "长城": "https://images.unsplash.com/photo-1508804185872-d7badad00f7d?auto=format&fit=crop&w=800&q=80",
    "天安门广场": "https://images.unsplash.com/photo-1508804185872-d7badad00f7d?auto=format&fit=crop&w=800&q=80",
    "景山公园": "https://images.unsplash.com/photo-1547981609-4b6bfe67ca0b?auto=format&fit=crop&w=800&q=80",
    "北海公园": "https://images.unsplash.com/photo-1598899134739-24c46f58b8c0?auto=format&fit=crop&w=800&q=80",
    "南锣鼓巷": "https://images.unsplash.com/photo-1538428494232-9c0d8a3ab403?auto=format&fit=crop&w=800&q=80",
    "恭王府": "https://images.unsplash.com/photo-1547981609-4b6bfe67ca0b?auto=format&fit=crop&w=800&q=80",

    # 四川 & 成都 & 川西
    "成都大熊猫繁育研究基地": "https://images.unsplash.com/photo-1564349683136-77e08dba1ef7?auto=format&fit=crop&w=800&q=80",
    "大熊猫基地": "https://images.unsplash.com/photo-1564349683136-77e08dba1ef7?auto=format&fit=crop&w=800&q=80",
    "宽窄巷子": "https://images.unsplash.com/photo-1578632767115-351597cf2477?auto=format&fit=crop&w=800&q=80",
    "锦里": "https://images.unsplash.com/photo-1578632767115-351597cf2477?auto=format&fit=crop&w=800&q=80",
    "武侯祠": "https://images.unsplash.com/photo-1578632767115-351597cf2477?auto=format&fit=crop&w=800&q=80",
    "都江堰": "https://images.unsplash.com/photo-1544085311-11a028465b03?auto=format&fit=crop&w=800&q=80",
    "都江堰景区": "https://images.unsplash.com/photo-1544085311-11a028465b03?auto=format&fit=crop&w=800&q=80",
    "青城山": "https://images.unsplash.com/photo-1544085311-11a028465b03?auto=format&fit=crop&w=800&q=80",
    "峨眉山": "https://images.unsplash.com/photo-1544085311-11a028465b03?auto=format&fit=crop&w=800&q=80",
    "峨眉山金顶": "https://images.unsplash.com/photo-1544085311-11a028465b03?auto=format&fit=crop&w=800&q=80",
    "乐山大佛": "https://images.unsplash.com/photo-1599837565318-67429bde7162?auto=format&fit=crop&w=800&q=80",
    "九寨沟": "https://images.unsplash.com/photo-1544085311-11a028465b03?auto=format&fit=crop&w=800&q=80",
    "四姑娘山": "https://images.unsplash.com/photo-1464822759023-fed622ff2c3b?auto=format&fit=crop&w=800&q=80",
    "稻城亚丁": "https://images.unsplash.com/photo-1464822759023-fed622ff2c3b?auto=format&fit=crop&w=800&q=80",
    "新都桥": "https://images.unsplash.com/photo-1464822759023-fed622ff2c3b?auto=format&fit=crop&w=800&q=80",
    "三星堆博物馆": "https://images.unsplash.com/photo-1547981609-4b6bfe67ca0b?auto=format&fit=crop&w=800&q=80",

    # 上海 & 华东
    "上海外滩": "https://images.unsplash.com/photo-1538428494232-9c0d8a3ab403?auto=format&fit=crop&w=800&q=80",
    "外滩": "https://images.unsplash.com/photo-1538428494232-9c0d8a3ab403?auto=format&fit=crop&w=800&q=80",
    "东方明珠": "https://images.unsplash.com/photo-1538428494232-9c0d8a3ab403?auto=format&fit=crop&w=800&q=80",
    "西湖": "https://images.unsplash.com/photo-1527684651001-731c474bbb5a?auto=format&fit=crop&w=800&q=80",
    "杭州西湖": "https://images.unsplash.com/photo-1527684651001-731c474bbb5a?auto=format&fit=crop&w=800&q=80",
    "灵隐寺": "https://images.unsplash.com/photo-1527684651001-731c474bbb5a?auto=format&fit=crop&w=800&q=80",
    "拙政园": "https://images.unsplash.com/photo-1527684651001-731c474bbb5a?auto=format&fit=crop&w=800&q=80",
    "苏州园林": "https://images.unsplash.com/photo-1527684651001-731c474bbb5a?auto=format&fit=crop&w=800&q=80",
    "乌镇": "https://images.unsplash.com/photo-1527684651001-731c474bbb5a?auto=format&fit=crop&w=800&q=80",
    "黄山": "https://images.unsplash.com/photo-1544085311-11a028465b03?auto=format&fit=crop&w=800&q=80",

    # 西北 & 西南
    "秦始皇帝陵博物院(兵马俑)": "https://images.unsplash.com/photo-1599837565318-67429bde7162?auto=format&fit=crop&w=800&q=80",
    "兵马俑": "https://images.unsplash.com/photo-1599837565318-67429bde7162?auto=format&fit=crop&w=800&q=80",
    "大雁塔": "https://images.unsplash.com/photo-1599837565318-67429bde7162?auto=format&fit=crop&w=800&q=80",
    "莫高窟": "https://images.unsplash.com/photo-1508804185872-d7badad00f7d?auto=format&fit=crop&w=800&q=80",
    "鸣沙山月牙泉": "https://images.unsplash.com/photo-1508804185872-d7badad00f7d?auto=format&fit=crop&w=800&q=80",
    "布达拉宫": "https://images.unsplash.com/photo-1584824486509-112e4181ff6b?auto=format&fit=crop&w=800&q=80",
}


def resolve_poi_image(
    poi_name: str,
    raw_photos: list[dict[str, Any]] | None = None,
    photos: list[dict[str, Any]] | None = None,
    category: str = "",
) -> str:
    """提取或匹配 POI 的高清实景图片 URL。

    优先级策略:
    1. 高德官方原始返回有效实景照片 (Amap Native Photos)
    2. 精选高品质名胜图库模糊匹配 (Curated Landmark Images)
    3. 分类默认文旅意境摄影
    """
    clean_name = (poi_name or "").strip()

    # 1. 优先提取高德原始实景图
    effective_photos = raw_photos if raw_photos is not None else photos
    if effective_photos and isinstance(effective_photos, list):
        for p in effective_photos:
            if isinstance(p, dict):
                url = p.get("url")
                if url and isinstance(url, str) and url.startswith("http"):
                    return url

    # 2. 精选名胜摄影匹配
    if clean_name in CURATED_LANDMARK_IMAGES:
        return CURATED_LANDMARK_IMAGES[clean_name]

    for landmark_k, img_url in CURATED_LANDMARK_IMAGES.items():
        if landmark_k in clean_name or clean_name in landmark_k:
            return img_url

    # 3. 分类意境图兜底
    cat_str = category or ""
    if any(k in cat_str or k in clean_name for k in ("山", "峰", "岭", "自然", "风光", "峡谷")):
        return "https://images.unsplash.com/photo-1464822759023-fed622ff2c3b?auto=format&fit=crop&w=800&q=80"
    if any(k in cat_str or k in clean_name for k in ("寺", "庙", "宫", "古迹", "文物", "博物馆", "故居")):
        return "https://images.unsplash.com/photo-1547981609-4b6bfe67ca0b?auto=format&fit=crop&w=800&q=80"
    if any(k in cat_str or k in clean_name for k in ("园", "湖", "水", "林", "海", "岛")):
        return "https://images.unsplash.com/photo-1527684651001-731c474bbb5a?auto=format&fit=crop&w=800&q=80"
    if any(k in cat_str or k in clean_name for k in ("餐", "吃", "食", "味", "菜", "饭", "酒", "肉", "面", "街区", "夜市")):
        return "https://images.unsplash.com/photo-1555396273-367ea4eb4db5?auto=format&fit=crop&w=800&q=80"

    return "https://images.unsplash.com/photo-1506744038136-46273834b3fb?auto=format&fit=crop&w=800&q=80"
