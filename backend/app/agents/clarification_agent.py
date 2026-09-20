"""意图澄清与人机协同 Agent (Clarification Agent)

核心职责:
1. 实时解析多轮对话上下文，提取旅行需求槽位（城市、天数、预算、交通、偏好与锁定项）。
2. 基于自然语言持久性副词，精准区分本次需求 (TRIP_TRANSIENT) 与长期画像 (LONG_TERM_USER)。
3. 检查必要槽位完备性；当关键信息缺失时，生成具象提问与预选卡片，并触发 LangGraph 原生 `interrupt` 挂起。
4. 从 Checkpoint 恢复后，无缝吸收用户选择或自定义输入，提交进入规划链路。
"""
from __future__ import annotations

import re
from datetime import datetime, date, timedelta
from typing import Any
from langgraph.types import interrupt
from ..models.session import (
    EffectiveRequirements,
    RequirementSlot,
    SlotOrigin,
    PreferenceScope,
    ClarificationOption,
    ClarificationPrompt,
)
from ..memory.manager import is_persistent_preference
from ..memory.context_compactor import compact_conversation_history

# 常见热门目的地城市库
COMMON_CITIES = [
    "北京", "上海", "广州", "深圳", "成都", "重庆", "杭州", "西安", "南京",
    "武汉", "苏州", "天津", "厦门", "三亚", "青岛", "长沙", "郑州", "大连",
    "昆明", "哈尔滨", "沈阳", "济南", "福州", "南宁", "贵阳", "兰州", "拉萨",
    "银川", "西宁", "乌鲁木齐", "桂林", "洛阳", "黄山", "张家界", "九寨沟", "大理", "丽江",
]

CN_NUM_MAP = {
    "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
    "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
}


def _parse_int(val_str: str) -> int | None:
    if not val_str:
        return None
    val_str = val_str.strip()
    if val_str.isdigit():
        return int(val_str)
    return CN_NUM_MAP.get(val_str)


def extract_slots_from_input(
    text: str,
    current_req: EffectiveRequirements | None = None,
) -> EffectiveRequirements:
    """从自然语言文本中提取槽位并更新 EffectiveRequirements"""
    req = current_req or EffectiveRequirements()
    if not text or not text.strip():
        return req

    # 1. 城市与名胜抽取 (支持复合目的地与名山大川)
    # 知名旅游名胜与所属行政区映射
    FAMOUS_LANDMARK_CITY_MAP = {
        "峨眉山": "乐山",
        "乐山大佛": "乐山",
        "都江堰": "成都",
        "青城山": "成都",
        "九寨沟": "阿坝",
        "黄山": "黄山",
        "张家界": "张家界",
        "西湖": "杭州",
        "兵马俑": "西安",
        "洱海": "大理",
        "玉龙雪山": "丽江",
        "鼓浪屿": "厦门",
        "泰山": "泰安",
        "华山": "渭南",
        "普陀山": "舟山",
        "武夷山": "南平",
    }

    extracted_city = None
    # 优先匹配长地名与名山大川
    matched_landmarks = []
    for lm, mapped_city in FAMOUS_LANDMARK_CITY_MAP.items():
        if lm in text:
            matched_landmarks.append(lm)
            if not extracted_city:
                extracted_city = mapped_city

    for city in COMMON_CITIES:
        if city in text:
            extracted_city = city
            break

    if not extracted_city:
        city_match = re.search(r"(?:去|到|想去|目的地[是为]?)\s*([\u4e00-\u9fa5]{2,6}?(?:市|区)?)", text)
        if city_match:
            candidate = city_match.group(1).replace("市", "").strip()
            excluded_words = {"旅游", "出游", "玩耍", "度假", "散心", "转转", "逛逛", "看看", "玩", "地方", "哪里"}
            if len(candidate) in (2, 3, 4) and candidate not in excluded_words:
                extracted_city = candidate

    if extracted_city:
        req.set_slot("city", extracted_city, origin=SlotOrigin.USER_EXPLICIT)

    # 提取到的名胜直接注入锁定项（如峨眉山、乐山大佛）
    for lm in matched_landmarks:
        if lm not in req.locked_items:
            req.locked_items.append(lm)

    # 2. 天数抽取 (匹配 "玩2天", "3天", "3天左右", 排除形如 "8月24日" 的日历日期)
    days_match = re.search(r"(?:玩|游玩|行程|呆|待|共|为期)?\s*([0-9一二两三四五六七八九十]+)\s*天(?:左右|上下)?", text)
    if not days_match:
        days_match = re.search(r"(?<![0-9月])([0-9一二两三四五六七八九十]+)\s*日(?:游|行程)?", text)
    if days_match:
        parsed_days = _parse_int(days_match.group(1))
        if parsed_days and 1 <= parsed_days <= 14:
            req.set_slot("days", parsed_days, origin=SlotOrigin.USER_EXPLICIT)

    # 3. 预算抽取
    budget_match = re.search(r"(?:预算|花费|控制在|大概)?\s*(\d+(?:\.\d+)?)\s*(?:元|块|w|万|千|k)", text)
    if budget_match:
        num = float(budget_match.group(1))
        matched_str = budget_match.group(0)
        if "万" in matched_str or "w" in matched_str.lower():
            num *= 10000
        elif "千" in matched_str or "k" in matched_str.lower():
            num *= 1000
        req.set_slot("budget_total", round(num, 2), origin=SlotOrigin.USER_EXPLICIT)

    # 4. 出发日期抽取 (支持绝对日期、月日格式与相对自然语言日期)
    today = datetime.now().date()
    extracted_date = None

    date_match = re.search(r"(\d{4}[-/年]\d{1,2}[-/月]\d{1,2}[日号]?)", text)
    if date_match:
        raw_date = date_match.group(1)
        clean_date = raw_date.replace("年", "-").replace("月", "-").replace("日", "").replace("号", "").replace("/", "-")
        parts = clean_date.split("-")
        if len(parts) == 3:
            extracted_date = f"{parts[0]}-{int(parts[1]):02d}-{int(parts[2]):02d}"
    else:
        # 尝试匹配 M月D日 (如 9月21日)
        md_match = re.search(r"(?<!\d)(\d{1,2})[月/-](\d{1,2})[日号]?", text)
        if md_match:
            m_val = int(md_match.group(1))
            d_val = int(md_match.group(2))
            if 1 <= m_val <= 12 and 1 <= d_val <= 31:
                extracted_date = f"{today.year}-{m_val:02d}-{d_val:02d}"

    # 相对日期匹配
    if not extracted_date:
        if re.search(r"(?:明天|次日)", text):
            extracted_date = (today + timedelta(days=1)).strftime("%Y-%m-%d")
        elif re.search(r"后天", text):
            extracted_date = (today + timedelta(days=2)).strftime("%Y-%m-%d")
        elif re.search(r"(?:今天|当日|现在|即刻)", text):
            extracted_date = today.strftime("%Y-%m-%d")
        elif re.search(r"(?:本周末|这周末|周末)", text):
            days_sat = (5 - today.weekday()) % 7
            if days_sat == 0:
                days_sat = 7
            extracted_date = (today + timedelta(days=days_sat)).strftime("%Y-%m-%d")
        elif re.search(r"下周一", text):
            days_mon = (7 - today.weekday()) % 7
            if days_mon == 0:
                days_mon = 7
            extracted_date = (today + timedelta(days=days_mon)).strftime("%Y-%m-%d")

    if extracted_date:
        req.set_slot("start_date", extracted_date, origin=SlotOrigin.USER_EXPLICIT)

    # 5. 显式锁定景点抽取 (仅截取到逗号/句号等标点，并按“和/与/及/顿号”分割，避开颐和园)
    lock_match = re.search(r"(?:必须去|一定要去|必去|锁定|不能少|非去不可)\s*([^，。！？\n]+)", text)
    if lock_match:
        raw_locks = lock_match.group(1)
        tokens = [t.strip() for t in re.split(r"(?<!颐)和|与|及|[、，,\s]+", raw_locks) if t.strip()]
        for token in tokens:
            if token not in req.locked_items and len(token) >= 2 and token not in ("地方", "景点"):
                req.locked_items.append(token)

    # 6. 出行人员/人数抽取 (单人、亲子、情侣等)
    if re.search(r"(?:我一个人|一个人|独自|单人|一人游|独自一人|独自出行)", text):
        req.set_slot("travel_party", "单人出行", origin=SlotOrigin.USER_EXPLICIT)

    # 7. 偏好风格与美食抽取 (严格解耦：景点向偏好 vs 美食向偏好)
    food_vocab = {
        "美食", "小吃", "特色小吃", "特色菜", "特产", "地道美食", "老字号",
        "清淡", "吃辣", "火锅", "素食", "烤鸭", "涮羊肉", "川菜", "粤菜", "湘菜",
        "鲁菜", "江浙菜", "烧烤", "海鲜", "早茶", "面食", "串串", "小酒馆",
    }
    scenic_vocab = {
        "大熊猫", "熊猫", "历史文化", "人文古迹", "自然风光", "亲子游", "拍照打卡",
        "特种兵", "休闲慢节奏", "博物馆", "古镇", "老街", "名胜古迹", "寺庙", "名山",
        "山水", "地标", "世界遗产", "主题公园",
    }

    matched_food: list[str] = [p for p in food_vocab if p in text]
    matched_scenic: list[str] = [p for p in scenic_vocab if p in text]

    # 动态匹配 "想吃xxx" / "喜欢吃xxx" / "吃xxx"
    food_matches = re.findall(r"(?:想吃|喜欢吃|爱吃|吃)\s*([\u4e00-\u9fa5]{2,6})", text)
    for fm in food_matches:
        if fm not in matched_food and fm not in ("北京", "上海", "早饭", "午饭", "晚饭", "饭", "东西", "好的"):
            matched_food.append(fm)

    # 动态匹配 "想看xxx" / "去看xxx" / "打卡xxx"
    scenic_matches = re.findall(r"(?:想看|去看|看|打卡|游览|逛|去)\s*([\u4e00-\u9fa5]{2,6})", text)
    for sm in scenic_matches:
        if sm in ("大熊猫", "熊猫", "古迹", "博物馆", "山水", "古镇", "老街", "夜景", "风景"):
            if sm not in matched_scenic:
                matched_scenic.append(sm)

    # 过滤掉较短的重叠子串 (例如同时命中 '大熊猫' 与 '熊猫' 时，只保留更精确的 '大熊猫')
    filtered_scenic: list[str] = []
    for s in sorted(matched_scenic, key=len, reverse=True):
        if not any(s != other and s in other for other in filtered_scenic):
            filtered_scenic.append(s)
    matched_scenic = filtered_scenic

    filtered_food: list[str] = []
    for f in sorted(matched_food, key=len, reverse=True):
        if not any(f != other and f in other for other in filtered_food):
            filtered_food.append(f)
    matched_food = filtered_food

    scope = PreferenceScope.LONG_TERM_USER if is_persistent_preference(text) else PreferenceScope.TRIP_TRANSIENT

    if matched_food:
        cur_food = req.get_slot_value("food_preferences", []) or []
        for f in matched_food:
            if f not in cur_food:
                cur_food.append(f)
        req.set_slot("food_preferences", cur_food, origin=SlotOrigin.USER_EXPLICIT, scope=scope)

    if matched_scenic:
        cur_scenic = req.get_slot_value("scenic_preferences", []) or []
        for s in matched_scenic:
            if s not in cur_scenic:
                cur_scenic.append(s)
        req.set_slot("scenic_preferences", cur_scenic, origin=SlotOrigin.USER_EXPLICIT, scope=scope)

    all_prefs = list(dict.fromkeys(matched_scenic + matched_food))
    if all_prefs:
        current_prefs = req.get_slot_value("preferences", []) or []
        for p in all_prefs:
            if p not in current_prefs:
                current_prefs.append(p)
        req.set_slot("preferences", current_prefs, origin=SlotOrigin.USER_EXPLICIT, scope=scope)

    return req


def check_clarification_needed(requirements: EffectiveRequirements) -> ClarificationPrompt | None:
    """检查核心必填项是否缺失，缺失时生成待决交互卡片"""
    city = requirements.get_slot_value("city")
    if not city:
        return ClarificationPrompt(
            prompt_text="请问您这次计划前往哪座城市旅行呢？",
            missing_slots=["city"],
            options=[
                ClarificationOption(option_id="city_bj", label="北京（经典古都）", action_type="SET_SLOT", payload={"key": "city", "value": "北京"}),
                ClarificationOption(option_id="city_sh", label="上海（摩登都市）", action_type="SET_SLOT", payload={"key": "city", "value": "上海"}),
                ClarificationOption(option_id="city_cd", label="成都（休闲美食）", action_type="SET_SLOT", payload={"key": "city", "value": "成都"}),
                ClarificationOption(option_id="city_xa", label="西安（盛唐风韵）", action_type="SET_SLOT", payload={"key": "city", "value": "西安"}),
            ],
            allow_custom_input=True,
            can_use_default=False,
        )

    days = requirements.get_slot_value("days")
    if not days or int(days) <= 0:
        return ClarificationPrompt(
            prompt_text=f"去【{city}】旅行，请问您打算游玩几天呢？",
            missing_slots=["days"],
            options=[
                ClarificationOption(option_id="days_2", label="2天（周末短途游）", action_type="SET_SLOT", payload={"key": "days", "value": 2}),
                ClarificationOption(option_id="days_3", label="3天（经典精华游）", action_type="SET_SLOT", payload={"key": "days", "value": 3}),
                ClarificationOption(option_id="days_5", label="5天（深度全景游）", action_type="SET_SLOT", payload={"key": "days", "value": 5}),
            ],
            allow_custom_input=True,
            can_use_default=True,
        )

    start_date = requirements.get_slot_value("start_date")
    if not start_date:
        today = datetime.now().date()
        tomorrow = today + timedelta(days=1)
        days_sat = (5 - today.weekday()) % 7
        if days_sat == 0:
            days_sat = 7
        weekend = today + timedelta(days=days_sat)
        days_mon = (7 - today.weekday()) % 7
        if days_mon == 0:
            days_mon = 7
        next_mon = today + timedelta(days=days_mon)

        return ClarificationPrompt(
            prompt_text=f"去【{city}】{days}天旅行，请问您计划哪天出发呢？（明确出发日期可精准对接高德未来4天天气预报与周一闭馆）：",
            missing_slots=["start_date"],
            options=[
                ClarificationOption(option_id="date_tomorrow", label=f"明天出发 ({tomorrow.strftime('%Y-%m-%d')})", action_type="SET_SLOT", payload={"key": "start_date", "value": tomorrow.strftime("%Y-%m-%d")}),
                ClarificationOption(option_id="date_weekend", label=f"本周末出发 ({weekend.strftime('%Y-%m-%d')})", action_type="SET_SLOT", payload={"key": "start_date", "value": weekend.strftime("%Y-%m-%d")}),
                ClarificationOption(option_id="date_monday", label=f"下周一出发 ({next_mon.strftime('%Y-%m-%d')})", action_type="SET_SLOT", payload={"key": "start_date", "value": next_mon.strftime("%Y-%m-%d")}),
                ClarificationOption(option_id="date_today", label=f"暂不确定，按近期规划 (今天 {today.strftime('%Y-%m-%d')})", action_type="SET_SLOT", payload={"key": "start_date", "value": today.strftime("%Y-%m-%d")}),
            ],
            allow_custom_input=True,
            can_use_default=True,
        )

    return None


def clarification_node(state: dict[str, Any]) -> dict[str, Any]:
    """LangGraph 意图澄清节点

    若信息不完备，调用 `interrupt(...)` 挂起；外部恢复后解析用户答案并继续。
    """
    input_text = state.get("input_text", "")
    req_dict = state.get("requirements")

    if isinstance(req_dict, dict):
        req = EffectiveRequirements.model_validate(req_dict)
    elif isinstance(req_dict, EffectiveRequirements):
        req = req_dict
    else:
        req = EffectiveRequirements()

    # 1. 抽取输入槽位
    req = extract_slots_from_input(input_text, current_req=req)

    # 2. 最多支持 3 轮人机协同意图澄清 (城市 -> 天数 -> 出发日期)
    for _ in range(3):
        prompt = check_clarification_needed(req)
        if prompt is None:
            break

        # 触发 LangGraph interrupt 挂起！等待外部恢复
        resume_data = interrupt(prompt.model_dump())

        # 恢复后解析用户提供的值
        if isinstance(resume_data, dict):
            if "key" in resume_data and "value" in resume_data:
                req.set_slot(resume_data["key"], resume_data["value"], origin=SlotOrigin.USER_EXPLICIT)
            elif "input_text" in resume_data:
                req = extract_slots_from_input(str(resume_data["input_text"]), current_req=req)
        elif isinstance(resume_data, str):
            req = extract_slots_from_input(resume_data, current_req=req)

    # Pi 风格上下文滑动窗口与观察值压缩
    raw_msgs = state.get("messages", [])
    compacted_msgs = compact_conversation_history(raw_msgs, keep_recent_turns=3) if raw_msgs else []

    return {
        "requirements": req.model_dump(),
        "locked_items": list(req.locked_items),
        "messages": compacted_msgs,
        "pending_clarification": None,
        "status": "planning",
    }
