"""标准 RFC 5545 iCalendar (.ics) 日程导出引擎 (Calendar Exporter)

将 TripPlanner 算法生成的行程结构体转换为全球通用的标准 .ics 日历文件，
支持一键批量导入 Apple Calendar、Google Calendar、华为/小米日历及 Microsoft Outlook。
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


def _escape_ics_text(text: str) -> str:
    """按 RFC 5545 标准转义特殊字符 (; , \\ 换行)"""
    if not text:
        return ""
    text = text.replace("\\", "\\\\")
    text = text.replace(";", "\\;")
    text = text.replace(",", "\\,")
    text = text.replace("\r\n", "\\n").replace("\n", "\\n")
    return text


def export_itinerary_to_ics(
    plan: dict[str, Any],
    city: str = "",
    calendar_title: str = "",
) -> str:
    """将旅行规划导出为标准 RFC 5545 .ics 文本内容。

    参数:
    - plan: 包含 days 列表的完整行程规划字典
    - city: 目的地城市名称
    - calendar_title: 日历标题自定义
    """
    days = plan.get("days", [])
    now_stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    target_city = city or plan.get("city") or "目的地"
    cal_name = calendar_title or f"{target_city} {len(days)}日智能旅行路书 [TripPlanner]"

    lines: list[str] = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//TripPlanner AI//Smart Travel Itinerary//CN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{_escape_ics_text(cal_name)}",
        "X-WR-TIMEZONE:Asia/Shanghai",
    ]

    for d_idx, day in enumerate(days):
        day_num = day.get("day_number") or (d_idx + 1)
        day_date_str = day.get("date")  # "YYYY-MM-DD"
        if not day_date_str:
            continue

        clean_date = day_date_str.replace("-", "")

        # 遍历当天景点
        for a_idx, attr in enumerate(day.get("attractions", [])):
            name = attr.get("name", "精选景点")
            arr_time = attr.get("arrive_time") or "09:00"
            dep_time = attr.get("depart_time") or "11:00"

            # 格式化时间为 YYYYMMDDTHHMMSS
            arr_h, arr_m = [int(x) for x in arr_time.split(":")[:2]] if ":" in arr_time else (9, 0)
            dep_h, dep_m = [int(x) for x in dep_time.split(":")[:2]] if ":" in dep_time else (arr_h + 2, arr_m)

            dtstart = f"{clean_date}T{arr_h:02d}{arr_m:02d}00"
            dtend = f"{clean_date}T{dep_h:02d}{dep_m:02d}00"

            lng = attr.get("lng")
            lat = attr.get("lat")
            price = attr.get("price") or attr.get("ticket_price") or 0.0
            category = attr.get("category", "")
            visit_mins = attr.get("visit_minutes", 120)

            # 构造备忘录内容 (游玩时长、门票参考、避坑指南、预约预警)
            desc_parts = [
                f"【行程节点】Day {day_num} · 推荐游玩 {visit_mins} 分钟",
                f"【门票参考】¥{float(price):.0f} 元" if price else "【门票参考】免费入园",
            ]
            if category:
                desc_parts.append(f"【类型分类】{category}")

            # 注入预约时效与售罄预警
            res_alert = attr.get("reservation_alert")
            if res_alert:
                desc_parts.append("────────────────")
                desc_parts.append(f"【预约注意】{res_alert.get('alert_title', '')}")
                if res_alert.get("alert_detail"):
                    desc_parts.append(f"【抢票攻略】{res_alert.get('alert_detail')}")
                if res_alert.get("backup_poi"):
                    desc_parts.append(f"【满票备选】建议改道平替: {res_alert.get('backup_poi')}")

            # 注入 Tavily 避坑 Tips
            guide = attr.get("tavily_guide") or {}
            tips = guide.get("tips") or []
            if tips:
                desc_parts.append("────────────────")
                desc_parts.append("【避坑贴士】" + "；".join(tips[:3]))

            desc_text = "\\n".join(desc_parts)
            summary_text = f"📍 Day {day_num} · {name}"

            uid = f"tp-{clean_date}-{d_idx}-{a_idx}-{uuid4().hex[:8]}@tripplanner.ai"

            lines.extend([
                "BEGIN:VEVENT",
                f"UID:{uid}",
                f"DTSTAMP:{now_stamp}",
                f"DTSTART;TZID=Asia/Shanghai:{dtstart}",
                f"DTEND;TZID=Asia/Shanghai:{dtend}",
                f"SUMMARY:{_escape_ics_text(summary_text)}",
                f"DESCRIPTION:{_escape_ics_text(desc_text)}",
                f"LOCATION:{_escape_ics_text(name)}",
            ])

            if lat is not None and lng is not None:
                # RFC 5545 规定 GEO:latitude;longitude
                lines.append(f"GEO:{float(lat):.6f};{float(lng):.6f}")

            # 注入提前 1 小时出行弹窗提醒
            lines.extend([
                "BEGIN:VALARM",
                "TRIGGER:-PT1H",
                "ACTION:DISPLAY",
                f"DESCRIPTION:{_escape_ics_text(f'出行提醒: 即将前往 {name}')}",
                "END:VALARM",
                "END:VEVENT",
            ])

        # 如果当天有精选酒店，且是该酒店第一晚，生成酒店入住日程
        hotel = day.get("hotel") or {}
        if hotel and hotel.get("name") and d_idx == 0:
            h_name = hotel.get("name")
            h_dtstart = f"{clean_date}T140000"
            h_dtend = f"{clean_date}T150000"
            h_uid = f"tp-hotel-{clean_date}-{uuid4().hex[:8]}@tripplanner.ai"
            h_desc = f"【商圈酒店】{h_name}\\n【Minimax 最优通勤选址】距各主要名胜通勤距离极值最小"
            lines.extend([
                "BEGIN:VEVENT",
                f"UID:{h_uid}",
                f"DTSTAMP:{now_stamp}",
                f"DTSTART;TZID=Asia/Shanghai:{h_dtstart}",
                f"DTEND;TZID=Asia/Shanghai:{h_dtend}",
                f"SUMMARY:{_escape_ics_text(f'🏨 办理入住 · {h_name}')}",
                f"DESCRIPTION:{_escape_ics_text(h_desc)}",
                f"LOCATION:{_escape_ics_text(h_name)}",
                "END:VEVENT",
            ])

    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"
