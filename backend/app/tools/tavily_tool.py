"""Tavily 互联网实时检索工具 (Real Web RAG Tool)

基于 Tavily Search API 实现全网活数据检索：
1. 景点官方实名预约政策、门票价格与放票时段；
2. 真实游客避坑指南、游玩动线、拍照最佳机位；
3. 双重降噪提炼体系：LLM 语义结构化萃取为主 + 强力启发式降噪规则兜底；
4. 挂载 Redis 7 天指纹缓存，杜绝重复网络往返与开销；
5. 弹性降级：网络异常或配额耗尽时透明保底，不阻断行程规划。
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any
import requests

from ..config import get_settings
from .cache_decorator import cached_tool_result

logger = logging.getLogger(__name__)

TAVILY_API_ENDPOINT = "https://api.tavily.com/search"

NOISE_PATTERNS = [
    "企业文化", "广告服务", "关于我们", "联系我们", "诚聘英才", "意见建议",
    "本地宝app", "本地宝", "客户端下载", "下载app", "app下载", "版权所有",
    "免责声明", "icp备", "公网安备", "相关推荐", "热门推荐", "猜你喜欢",
    "最新资讯", "【导语】", "导语：", "未经授权", "严禁转载", "返回顶部",
    "分享到", "扫一扫", "友情链接", "商务合作", "法律声明", "用户协议", "隐私政策",
]


def make_tavily_cache_key(city: str, poi_name: str, **kwargs: Any) -> dict[str, Any]:
    """构建 Tavily 检索的确定性指纹键"""
    return {
        "city": (city or "").strip(),
        "poi_name": (poi_name or "").strip(),
    }


def is_noise_line(line: str) -> bool:
    """过滤网页页脚、导航栏、广告、面包屑、SEO 标签等垃圾信息"""
    cleaned = line.strip()
    if not cleaned or len(cleaned) < 6:
        return True

    # 1. 结构性噪音：管道符分隔的导航/页脚条、面包屑路径
    if cleaned.count("|") >= 2 or cleaned.count(">") >= 2 or " > " in cleaned:
        return True

    # 2. 纯问句导语或促销吸睛文案 (例如: "门票多少钱？怎么预约？")
    if cleaned.count("？") >= 2 or cleaned.count("?") >= 2 or "【导语】" in cleaned or "导语：" in cleaned:
        return True

    # 3. 常见网页底栏、广告、法务与版权噪音黑名单
    lower_line = cleaned.lower()
    for kw in NOISE_PATTERNS:
        if kw in lower_line:
            return True

    # 4. SEO 关键词堆叠检测：例如 "北京明十三陵购票入口 北京明十三陵门票 北京明十三陵"
    words = cleaned.split()
    if len(words) >= 3 and len(set(words)) <= len(words) // 2:
        return True

    return False


def _heuristic_extract_booking_policy(text: str) -> str:
    """从文本中启发式提取预约与门票关键信息（带强力降噪）"""
    raw_lines = re.split(r"[。\n；;]", text)
    booking_lines = []
    for line in raw_lines:
        line_clean = line.strip()
        if is_noise_line(line_clean):
            continue
        if any(kw in line_clean for kw in ["预约", "提前", "抢票", "放票", "门票", "小程序", "身份证", "公众号", "限流", "购票"]):
            if 10 <= len(line_clean) <= 120 and line_clean not in booking_lines:
                booking_lines.append(line_clean)
                if len(booking_lines) >= 2:
                    break
    return "；".join(booking_lines) if booking_lines else "建议提前关注官方微信公众号或小程序查询实名预约政策"


def _heuristic_extract_tips(text: str) -> list[str]:
    """从文本中启发式提取避坑与游玩贴士（带强力降噪）"""
    raw_lines = re.split(r"[。\n！!；;]", text)
    tips = []
    for line in raw_lines:
        line_clean = line.strip()
        if is_noise_line(line_clean):
            continue
        if any(kw in line_clean for kw in ["避坑", "建议", "注意", "拍照", "机位", "最好", "早点", "排队", "错峰", "游览"]):
            if 10 <= len(line_clean) <= 120 and line_clean not in tips:
                tips.append(line_clean)
                if len(tips) >= 3:
                    break
    if not tips:
        tips = ["建议错峰出行，注意保管随身物品", "景区内部步行较多，建议穿着舒适运动鞋"]
    return tips


# 别名兼容原有接口
_extract_booking_policy = _heuristic_extract_booking_policy
_extract_tips = _heuristic_extract_tips


def _llm_extract_guide_tips(city: str, poi_name: str, text: str) -> tuple[str, list[str]] | None:
    """利用轻量级 LLM 结构化萃取干净专业的预约政策与避坑建议"""
    if not text or len(text.strip()) < 30:
        return None

    try:
        from ..services.llm_service import get_llm
        llm = get_llm()

        trimmed_text = text[:1500].strip()

        prompt = (
            f"你是一位资深旅游规划专家。请根据以下关于「{city} {poi_name}」的网页检索内容，提炼准确、精炼、实用的游玩指南。\n"
            f"【核心要求】\n"
            f"1. 坚决剔除网页导航、广告、页脚（如企业文化/广告服务/关于我们/意见建议等）、SEO 关键词堆叠与空话套话；\n"
            f"2. booking_policy：用一至两句话总结真实的门票价格、实名预约渠道（公众号/小程序/官网）与提前放票时间；\n"
            f"3. tips：输出 1 到 3 条真正有实用价值的避坑指南、游玩动线、错峰攻略或拍照机位提示；\n"
            f"4. 严格直接输出合法 JSON 字典，严禁任何思考推理过程，严禁 markdown 代码块：\n"
            f'{{"booking_policy": "...", "tips": ["...", "..."]}}\n\n'
            f"【检索片段】\n"
            f"{trimmed_text}"
        )

        resp = llm.invoke([{"role": "user", "content": prompt}], max_tokens=350)
        content = resp.content if hasattr(resp, "content") else str(resp)
        content = content.strip()

        if content.startswith("```"):
            lines = content.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip().startswith("```"):
                lines = lines[:-1]
            content = "\n".join(lines).strip()

        data = json.loads(content)
        policy = str(data.get("booking_policy", "")).strip()
        raw_tips = data.get("tips", [])
        tips = [
            str(t).strip() for t in raw_tips
            if str(t).strip() and not is_noise_line(str(t))
        ]

        if policy and tips:
            return policy, tips
    except Exception as e:
        logger.debug("LLM 提取 Tavily 攻略摘要降级到启发式: %s", e)

    return None


def _fetch_tavily_search_impl(
    city: str,
    poi_name: str,
    api_key: str,
    max_results: int = 2,
) -> dict[str, Any]:
    """执行 Tavily API 检索"""
    clean_city = (city or "").strip()
    clean_poi = (poi_name or "").strip()
    if not clean_poi:
        return {}

    query = f"{clean_city} {clean_poi} 门票预约 开放时间 避坑指南 游玩攻略"
    payload = {
        "api_key": api_key,
        "query": query,
        "search_depth": "basic",
        "include_answer": False,
        "max_results": max_results,
    }

    try:
        resp = requests.post(
            TAVILY_API_ENDPOINT,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=8,
        )
        if resp.status_code != 200:
            logger.warning("Tavily API 响应状态异常 [%s]: %s", resp.status_code, resp.text[:200])
            return {}

        data = resp.json()
        results = data.get("results", [])
        if not results:
            return {}

        combined_text = "\n".join([r.get("content", "") for r in results])
        urls = [r.get("url", "") for r in results if r.get("url")]

        # 优先执行高性能本地启发式降噪提取 (0.01ms)，杜绝大模型长考能耗与网络延迟
        h_policy = _heuristic_extract_booking_policy(combined_text)
        h_tips = _heuristic_extract_tips(combined_text)

        # 启发式提取出真实门票信息与有效避坑时，直接采用
        is_heuristic_sufficient = (
            h_policy and "请以景区" not in h_policy and
            h_tips and len(h_tips) >= 1 and "建议错峰出行" not in h_tips[0]
        )

        if is_heuristic_sufficient:
            booking_policy, tips = h_policy, h_tips
        else:
            # 仅在无具体事实时才尝试轻量 LLM 辅助提炼
            llm_res = _llm_extract_guide_tips(clean_city, clean_poi, combined_text)
            if llm_res and llm_res[0]:
                booking_policy, tips = llm_res
            else:
                booking_policy = h_policy
                tips = h_tips

        # 挑选首条最相关摘要并做降噪处理
        first_content = results[0].get("content", "")
        first_lines = [line.strip() for line in first_content.split("\n") if not is_noise_line(line)]
        clean_first_text = " ".join(first_lines) if first_lines else first_content
        # 清理作者、纠错、发布时间等网页杂质
        clean_summary = re.sub(r"\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}(:\d{2})?", "", clean_first_text)
        clean_summary = re.sub(r"作者[：:][^\s]+", "", clean_summary)
        clean_summary = re.sub(r"【[^】]+】", "", clean_summary).strip()
        summary = clean_summary[:200].strip() + ("..." if len(clean_summary) > 200 else "")

        return {
            "poi_name": clean_poi,
            "city": clean_city,
            "booking_policy": booking_policy,
            "tips": tips,
            "summary": summary,
            "source_urls": urls,
            "source": "tavily_web_search",
        }

    except Exception as e:
        logger.warning("Tavily 检索网络异常或超时 (%s - %s): %s", clean_city, clean_poi, e)
        return {}


@cached_tool_result("search_tavily", key_builder=make_tavily_cache_key, ttl=604800)
def _cached_search_tavily_poi(city: str, poi_name: str, api_key: str) -> dict[str, Any]:
    return _fetch_tavily_search_impl(city=city, poi_name=poi_name, api_key=api_key)


def search_tavily_poi_guides(
    city: str,
    poi_name: str,
    api_key: str | None = None,
    use_cache: bool = True,
) -> dict[str, Any]:
    """统一公开入口：检索指定景点的互联网实时攻略、预约政策与避坑指南"""
    try:
        settings = get_settings()
        key = api_key or (settings.tavily_api_key if settings else "")
    except Exception:
        key = api_key or ""

    if not key:
        logger.debug("未配置 TAVILY_API_KEY，跳过网络 RAG 检索")
        return {}

    if not use_cache:
        return _fetch_tavily_search_impl(city=city, poi_name=poi_name, api_key=key)

    return _cached_search_tavily_poi(city=city, poi_name=poi_name, api_key=key)
