"""热门名胜地标预约时效与售罄预警引擎 (Reservation Policy Engine)

真实国内旅游核心痛点解决方案：
解决大模型规划中“数学路线完美，落地名胜因未提前抢票导致进不去”的致命软肋。
规则化沉淀全国重点 5A、文博场馆与名山大川的实名放票周期、每日放票时刻与替代名胜推荐。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any


@dataclass(frozen=True)
class ReservationRule:
    """名胜预约规则实体"""
    poi_name: str
    match_keywords: tuple[str, ...]
    lead_days: int             # 需提前天数放票
    release_time: str          # 每日放票时刻 (如 "20:00")
    booking_channel: str       # 官方预约渠道
    is_hard_barrier: bool      # 是否完全不设现场窗口（硬门槛）
    backup_pois: tuple[str, ...]  # 备选平替名胜推荐
    special_tips: str          # 抢票与参观避坑关键注意事项


# ────────────────────────────────────────────────────────────
# 重点名胜预约规则知识库 (覆盖全国热门 5A 与核心文博)
# ────────────────────────────────────────────────────────────
RESERVATION_RULES: list[ReservationRule] = [
    ReservationRule(
        poi_name="故宫博物院",
        match_keywords=("故宫", "紫禁城", "故宫博物院"),
        lead_days=7,
        release_time="20:00",
        booking_channel="故宫博物院官方小程序",
        is_hard_barrier=True,
        backup_pois=("恭王府", "景山公园", "北海公园"),
        special_tips="现场不设购票窗口！每日20:00整准时放第7天门票，通常数分钟内售罄；周一全天闭馆。",
    ),
    ReservationRule(
        poi_name="中国国家博物馆",
        match_keywords=("国家博物馆", "国博"),
        lead_days=7,
        release_time="17:00",
        booking_channel="国家博物馆官方App/小程序",
        is_hard_barrier=True,
        backup_pois=("首都博物馆", "中国美术馆", "北京鲁迅博物馆"),
        special_tips="全员实名免票预约，每日17:00开放第7天预约，极其难约；入馆必须携带身份证原件；周一闭馆。",
    ),
    ReservationRule(
        poi_name="莫高窟",
        match_keywords=("莫高窟", "敦煌莫高窟"),
        lead_days=30,
        release_time="07:00",
        booking_channel="莫高窟参观预约网/官方微信",
        is_hard_barrier=True,
        backup_pois=("西千佛洞", "榆林窟"),
        special_tips="A类正常票（看8个洞窟+2场数字电影）提前30天发售，旺季秒空；若未约到可退选B类应急票（看4个洞窟）。",
    ),
    ReservationRule(
        poi_name="秦始皇帝陵博物院(兵马俑)",
        match_keywords=("兵马俑", "秦始皇兵马俑", "秦始皇帝陵"),
        lead_days=3,
        release_time="08:30",
        booking_channel="秦始皇帝陵博物院官方微信公众号",
        is_hard_barrier=True,
        backup_pois=("汉阳陵国家考古遗址公园", "华清宫"),
        special_tips="实名制分时段预约入园，迟到超过时段无法入园；现场无散客窗口售票。",
    ),
    ReservationRule(
        poi_name="陕西历史博物馆",
        match_keywords=("陕西历史博物馆", "陕历博"),
        lead_days=3,
        release_time="18:00",
        booking_channel="陕西历史博物馆微信公众号",
        is_hard_barrier=True,
        backup_pois=("西安博物院", "西安碑林博物馆", "陕历博秦汉馆"),
        special_tips="每日18:00、19:00、20:00、21:00整点分批放票，被称为全国最难约博物馆之一；周一闭馆。",
    ),
    ReservationRule(
        poi_name="布达拉宫",
        match_keywords=("布达拉宫", "布宫"),
        lead_days=7,
        release_time="08:30",
        booking_channel="布达拉宫官方微信小程序",
        is_hard_barrier=True,
        backup_pois=("大昭寺", "罗布林卡", "色拉寺"),
        special_tips="提前7天实名预约次日参观批次与准确时间段，按预约票面时间提前1小时抵达安全检查第一关口。",
    ),
    ReservationRule(
        poi_name="三星堆博物馆",
        match_keywords=("三星堆", "广汉三星堆"),
        lead_days=5,
        release_time="20:00",
        booking_channel="三星堆博物馆微信公众号/官方小程序",
        is_hard_barrier=True,
        backup_pois=("金沙遗址博物馆", "成都博物馆"),
        special_tips="提前5天晚上20:00开放门票预约，新馆落成后极受欢迎；退票会在每日上午统一回池。",
    ),
    ReservationRule(
        poi_name="成都大熊猫繁育研究基地",
        match_keywords=("大熊猫基地", "熊猫基地", "大熊猫繁育"),
        lead_days=7,
        release_time="19:00",
        booking_channel="成都大熊猫繁育研究基地官方公众号",
        is_hard_barrier=False,
        backup_pois=("都江堰熊猫谷", "成都动物园"),
        special_tips="分上午场(07:30-12:00)和下午场(12:01-17:00)，看顶流熊猫'花花'务必抢上午场且开园前排队。",
    ),
    ReservationRule(
        poi_name="拙政园",
        match_keywords=("拙政园",),
        lead_days=7,
        release_time="08:00",
        booking_channel="君到苏州微信小程序/官方分时预约系统",
        is_hard_barrier=True,
        backup_pois=("留园", "网师园", "狮子林"),
        special_tips="实名制分时段入园，严格按照预约时间段检票，上下午各限流，过号作废。",
    ),
    ReservationRule(
        poi_name="南京总统府",
        match_keywords=("南京总统府", "总统府"),
        lead_days=3,
        release_time="08:00",
        booking_channel="南京总统府官方微信公众号",
        is_hard_barrier=True,
        backup_pois=("美龄宫", "梅园新村纪念馆", "朝天宫"),
        special_tips="现场不售当日票，必须提前预约；每周一闭馆。",
    ),
    ReservationRule(
        poi_name="侵华日军南京大屠杀遇难同胞纪念馆",
        match_keywords=("大屠杀遇难同胞纪念馆", "江东门纪念馆"),
        lead_days=7,
        release_time="07:00",
        booking_channel="官方微信公众号实名预约",
        is_hard_barrier=True,
        backup_pois=("雨花台烈士陵园", "南京抗日航空烈士纪念馆"),
        special_tips="全员实名免费预约，安检极为严格，请务必衣着得体并携带身份证；周一闭馆。",
    ),
]


def _match_rule(poi_name: str) -> ReservationRule | None:
    """模糊匹配名胜对应的规则"""
    if not poi_name:
        return None
    for rule in RESERVATION_RULES:
        if rule.poi_name == poi_name:
            return rule
        for kw in rule.match_keywords:
            if kw in poi_name:
                return rule
    return None


def evaluate_poi_reservation(
    poi_name: str,
    visit_date: str | date,
    planning_date: str | date | None = None,
) -> dict[str, Any] | None:
    """评估特定名胜在指定出行日期的预约风险与状态。

    返回:
    - None: 该景点无需提前抢票或无特殊预约限制；
    - dict: 结构化预约风险与告警详情。
    """
    rule = _match_rule(poi_name)
    if not rule:
        return None

    # 解析日期
    if isinstance(visit_date, str):
        try:
            v_date = datetime.strptime(visit_date.strip(), "%Y-%m-%d").date()
        except Exception:
            v_date = date.today()
    else:
        v_date = visit_date

    if planning_date is None:
        p_date = date.today()
    elif isinstance(planning_date, str):
        try:
            p_date = datetime.strptime(planning_date.strip(), "%Y-%m-%d").date()
        except Exception:
            p_date = date.today()
    else:
        p_date = planning_date

    days_ahead = (v_date - p_date).days

    # 1. 极高风险 (CRITICAL): 距离出行天数 < 提前放票周期，现场无售票，大概率已售罄！
    if days_ahead < rule.lead_days and rule.is_hard_barrier:
        primary_backup = rule.backup_pois[0] if rule.backup_pois else "周边历史街区"
        backup_list = list(rule.backup_pois)
        return {
            "risk_level": "critical",  # critical | urgent | notice
            "rule_poi": rule.poi_name,
            "lead_days": rule.lead_days,
            "days_ahead": days_ahead,
            "release_time": rule.release_time,
            "booking_channel": rule.booking_channel,
            "alert_title": f"⚠️ {rule.poi_name} 需提前{rule.lead_days}天实名预约 · 当前可能已售罄",
            "alert_detail": f"{rule.poi_name}现场不设购票处，每日{rule.release_time}通过【{rule.booking_channel}】放第{rule.lead_days}天门票。当前距出行仅 {days_ahead} 天，如官方余票已空，强烈建议改道游览备选名胜【{primary_backup}】。",
            "special_tips": rule.special_tips,
            "backup_poi": primary_backup,
            "backup_pois": backup_list,
        }

    # 2. 紧急抢票期 (URGENT): 当前正是放票窗口，提示用户立即定闹钟或前往抢票
    if days_ahead == rule.lead_days:
        return {
            "risk_level": "urgent",
            "rule_poi": rule.poi_name,
            "lead_days": rule.lead_days,
            "days_ahead": days_ahead,
            "release_time": rule.release_time,
            "booking_channel": rule.booking_channel,
            "alert_title": f"🔥 {rule.poi_name} 门票今日放票中",
            "alert_detail": f"今日正值出行门票开放窗口！请于今日 {rule.release_time} 准时前往【{rule.booking_channel}】实名预约抢票。",
            "special_tips": rule.special_tips,
            "backup_poi": rule.backup_pois[0] if rule.backup_pois else "",
            "backup_pois": list(rule.backup_pois),
        }

    # 3. 提示期 (NOTICE): 出行尚早，提醒定闹钟
    if days_ahead > rule.lead_days:
        return {
            "risk_level": "notice",
            "rule_poi": rule.poi_name,
            "lead_days": rule.lead_days,
            "days_ahead": days_ahead,
            "release_time": rule.release_time,
            "booking_channel": rule.booking_channel,
            "alert_title": f"📅 {rule.poi_name} 预约备忘: 需提前{rule.lead_days}天抢票",
            "alert_detail": f"出行前第 {rule.lead_days} 天 {rule.release_time} 开放预约，渠道: 【{rule.booking_channel}】。已为您设置日历提醒。",
            "special_tips": rule.special_tips,
            "backup_poi": rule.backup_pois[0] if rule.backup_pois else "",
            "backup_pois": list(rule.backup_pois),
        }

    return None
