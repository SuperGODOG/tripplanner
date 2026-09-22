"""双工 RAG 与动态时效事实核验工具集 (Dual-Track RAG Tools)

实现职责物理分离：
1. search_guides_tool: 检索游玩心得、避坑贴士、拍照机位与美食攻略 (半静态，高信息密度)。
2. lookup_place_facts_tool: 核查营业时间、周一闭馆规则、门票实名抢票政策 (高时效，强规则)。
贯彻“否定证据严谨判定”准则：搜不到闭馆通知 != 正常营业，存疑打标 NEEDS_CONFIRMATION。
"""
from __future__ import annotations

from datetime import datetime, date
from typing import Any
from ..services.guide_rag import get_guide_rag
from ..models.rag_models import (
    VerificationStatus,
    PlaceFact,
    GuideReference,
)
from .cache_decorator import cached_tool_result

# ── 知名场馆周一闭馆规则库 (中国文博/历史景区标准规则) ──
MONDAY_CLOSED_VENUES = {
    "故宫": "08:30-17:00 (16:00止票，周一闭馆)",
    "故宫博物院": "08:30-17:00 (16:00止票，周一闭馆)",
    "中国国家博物馆": "09:00-17:00 (16:00停止入馆，周一闭馆)",
    "国家博物馆": "09:00-17:00 (16:00停止入馆，周一闭馆)",
    "天坛公园(祈年殿)": "08:00-17:30 (祈年殿等景点周一闭馆，公园大门正常开放)",
    "天坛": "08:00-17:30 (祈年殿联票景点周一闭馆)",
    "恭王府": "08:30-17:00 (16:10停止入园，周一闭馆)",
    "首都博物馆": "09:00-17:00 (16:00停止入馆，周一闭馆)",
    "中国美术馆": "09:00-17:00 (16:00停止入馆，周一闭馆)",
    "陕西历史博物馆": "08:30-18:00 (周一闭馆整修)",
    "南京博物院": "09:00-17:00 (周一闭馆)",
    "上海博物馆": "09:00-17:00 (周一闭馆)",
    "湖北省博物馆": "09:00-17:00 (周一闭馆)",
    "湖南省博物馆": "09:00-17:00 (周一闭馆)",
    "浙江省博物馆": "09:00-17:00 (周一闭馆)",
    "四川省博物院": "09:00-17:00 (周一闭馆)",
    "三星堆博物馆": "08:30-18:00 (除国家法定节假日外周一闭馆)",
    "金沙遗址博物馆": "09:00-18:00 (周一闭馆)",
}

# ── 官方实名抢票/预约窗口规则库 ──
BOOKING_RULES = {
    "故宫": "需提前7天20:00通过官方小程序实名抢票，现场无售票窗口，周一闭馆",
    "故宫博物院": "需提前7天20:00通过官方小程序实名抢票，现场无售票窗口，周一闭馆",
    "天安门广场": "需提前1-7天预约参观（含升旗与降旗仪式），实名刷身份证入场",
    "天安门": "需提前1-7天预约参观，实名刷身份证入场",
    "中国国家博物馆": "需提前7天通过官方公众号预约，实名入馆",
    "国家博物馆": "需提前7天通过官方公众号预约，实名入馆",
    "八达岭长城": "需提前实名购票，现场限流，推荐缆车票提前预约",
    "颐和园": "可提前通过官方公众号预约购票，刷二维码或身份证入园",
    "环球影城": "建议提前购买门票及优速通，入园需刷脸绑定身份证",
    "乐山大佛": "可提前通过公众号实名购票，游船票需视当日天气与水位现场或当日预约",
    "峨眉山": "需提前实名购买进山门票与全山观光车票，金顶索道现场或小程序购票",
    "峨眉山金顶": "进山需持峨眉山门票，高山区索道建议提前购买联程车票",
    "三星堆博物馆": "需提前通过官方微信小程序预约购票，刷身份证入园",
    "陕西历史博物馆": "需提前在官方公众号放票时段实名抢票入馆",
}

# ── 知名常态化全天开放景区 ──
KNOWN_OPEN_VENUES = {
    "八达岭长城": "07:30-16:00",
    "颐和园": "06:00-19:00",
    "天安门广场": "05:00-22:00",
    "天安门": "05:00-22:00",
    "环球影城": "09:00-21:00",
    "景山公园": "06:00-21:00",
    "北海公园": "06:00-21:00",
    "乐山大佛": "07:30-18:30",
    "峨眉山金顶": "06:00-18:00",
    "峨眉山": "06:00-18:00",
    "青城山": "08:00-17:30",
    "都江堰": "08:00-18:00",
    "西湖": "00:00-24:00 (全天常态开放)",
    "春熙路": "00:00-24:00 (全天商业街区)",
    "宽窄巷子": "00:00-24:00 (全天开放街区)",
    "锦里": "00:00-24:00 (全天开放街区)",
}


@cached_tool_result("search_guides", ttl=604800)
def search_guides_tool(
    poi_name: str,
    city: str = "北京",
    top_k: int = 2,
) -> list[GuideReference]:
    """攻略经验检索工具 (半静态 RAG)

    基于轻量 BM25 检索小红书风精选攻略，按【玩法】、【避坑】、【拍照】、【美食】细分。
    返回结构化 GuideReference 列表，附带可溯源标签。
    """
    if not poi_name or not poi_name.strip():
        return []

    rag = get_guide_rag()
    hits = rag.retrieve(name=poi_name.strip(), city=city or None, top_k=top_k)

    results = []
    for h in hits:
        results.append(
            GuideReference(
                attraction=poi_name.strip(),
                guide=h.get("guide", ""),
                city=h.get("city", ""),
                tag=h.get("tag", "玩法") or "玩法",
                text=h.get("text", ""),
            )
        )
    return results


@cached_tool_result("lookup_place_facts", ttl=7200)
def lookup_place_facts_tool(
    poi_name: str,
    target_date: str,
    city: str = "北京",
) -> PlaceFact:
    """动态时效事实核验工具 (实效时态与开放状态核查)

    严格执行否定证据逻辑：
    1. 若命中周一且属于法定周一闭馆场馆 -> CONFLICT (不可通行)
    2. 若属于知名常态开放场馆或非周一文博场馆 -> VERIFIED (已证实)
    3. 若为未知小众地点或缺乏权威日历凭据 -> NEEDS_CONFIRMATION (存疑预警，杜绝大模型脑补)
    """
    clean_name = (poi_name or "").strip()
    if not clean_name:
        return PlaceFact(
            place_name="",
            city=city,
            verification_status=VerificationStatus.UNKNOWN,
            evidence_snippet="地点名称为空，无法核查事实",
        )

    now_str = datetime.now().isoformat()

    # 尝试解析目标日期
    is_monday = False
    try:
        dt = date.fromisoformat(target_date)
        is_monday = (dt.weekday() == 0)
    except (ValueError, TypeError):
        pass

    # 查找预约政策
    booking_policy = None
    for k, v in BOOKING_RULES.items():
        if k in clean_name or clean_name in k:
            booking_policy = v
            break

    # 自然山水、名岳大川、开放街区与公园一律豁免周一闭馆规则
    is_nature_or_open = any(kw in clean_name for kw in ["山", "大佛", "峡谷", "公园", "街区", "步行街", "古镇", "温泉", "湖"]) and not any(kw in clean_name for kw in ["博物馆", "纪念馆", "美术馆", "展览馆", "祈年殿", "故宫", "博览", "院"])

    # 1. 检查是否周一闭馆场馆
    matched_monday_venue = None
    if not is_nature_or_open:
        for k, v in MONDAY_CLOSED_VENUES.items():
            if k in clean_name or clean_name in k:
                matched_monday_venue = (k, v)
                break

    if matched_monday_venue:
        venue_name, open_hours = matched_monday_venue
        if is_monday:
            return PlaceFact(
                place_id=f"fact_{clean_name}_{target_date}",
                place_name=clean_name,
                city=city,
                opening_hours=open_hours,
                booking_policy=booking_policy,
                is_open_on_date=False,
                verification_status=VerificationStatus.CONFLICT,
                source="official_calendar",
                retrieved_at=now_str,
                applicable_date=target_date,
                confidence_score=1.0,
                evidence_snippet=f"【闭馆冲突】{clean_name} 实行周一例行闭馆政策，{target_date} 为周一，场馆不开放。",
            )
        else:
            return PlaceFact(
                place_id=f"fact_{clean_name}_{target_date}",
                place_name=clean_name,
                city=city,
                opening_hours=open_hours,
                booking_policy=booking_policy,
                is_open_on_date=True,
                verification_status=VerificationStatus.VERIFIED,
                source="official_calendar",
                retrieved_at=now_str,
                applicable_date=target_date,
                confidence_score=0.95,
                evidence_snippet=f"{clean_name} 在 {target_date}（非周一）正常开放游览。",
            )

    # 2. 检查知名常态开放场馆
    for k, open_hours in KNOWN_OPEN_VENUES.items():
        if k in clean_name or clean_name in k:
            return PlaceFact(
                place_id=f"fact_{clean_name}_{target_date}",
                place_name=clean_name,
                city=city,
                opening_hours=open_hours,
                booking_policy=booking_policy,
                is_open_on_date=True,
                verification_status=VerificationStatus.VERIFIED,
                source="map_poi_data",
                retrieved_at=now_str,
                applicable_date=target_date,
                confidence_score=0.95,
                evidence_snippet=f"{clean_name} 为常态化开放景点，开放时段为 {open_hours}。",
            )

    # 3. 缺乏权威日历或小众民间地点 -> 严谨判定为 NEEDS_CONFIRMATION (无闭馆公告 != 正常开放)
    return PlaceFact(
        place_id=f"fact_{clean_name}_{target_date}",
        place_name=clean_name,
        city=city,
        opening_hours=None,
        booking_policy=booking_policy,
        is_open_on_date=None,
        verification_status=VerificationStatus.NEEDS_CONFIRMATION,
        source="search_unverified",
        retrieved_at=now_str,
        applicable_date=target_date,
        confidence_score=0.5,
        evidence_snippet=(
            f"未检索到 {clean_name} 针对 {target_date} 的官方闭馆通知，但也无权威开放日历。"
            "按严谨准则标记为待核实，不可擅自脑补断言正常开放。"
        ),
    )
