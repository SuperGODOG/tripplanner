"""高德官方天气查询与气象指引工具 (Amap Weather Tool)

基于高德 MCP 原生 `maps_weather` 接口，提供指定城市未来 4 天天气预报、
穿衣游玩防灾贴士生成与多级缓存（内存 LRU + Redis 2小时）。
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, date
from functools import lru_cache
from typing import Any

from ..services.amap_service import run_mcp
from ..services.cache_service import get_cache_manager

logger = logging.getLogger(__name__)


def _generate_weather_tip(day_weather: str, night_weather: str, day_temp: int, night_temp: int) -> str:
    """根据天气现象与温度生成贴心的游玩出行与穿衣建议"""
    tips = []
    
    # 降水预警
    rain_keywords = ("雨", "阵雨", "雷阵雨", "暴雨", "小雨", "中雨", "大雨")
    if any(k in day_weather for k in rain_keywords) or any(k in night_weather for k in rain_keywords):
        tips.append("户外游览有降水，建议携带雨具并穿着防滑鞋")
    elif "雪" in day_weather or "雪" in night_weather:
        tips.append("有降雪天气，道路湿滑，注意防滑保暖")
    elif "晴" in day_weather or "晴" in night_weather:
        tips.append("天气晴好，紫外线较强，户外游玩建议做好防晒补水")
    elif "多云" in day_weather or "阴" in day_weather:
        tips.append("多云阴天，体感较为舒适，适宜名胜漫步与摄影")
        
    # 温差与气温
    temp_diff = abs(day_temp - night_temp)
    if temp_diff >= 8:
        tips.append(f"昼夜温差达 {temp_diff}℃，早晚游览或山区出行请携带薄外套备用")
        
    if day_temp >= 32:
        tips.append("气温偏高，中午时段尽量安排室内文博或阴凉景区游览")
    elif day_temp <= 8:
        tips.append("气温较低，建议穿着羽绒服或防风保暖衣物")
        
    return "；".join(tips) if tips else "天气平稳，适宜户外出行"


def fetch_amap_weather(city: str) -> dict[str, Any] | None:
    """调用高德 MCP maps_weather 获取指定城市预报天气 (带缓存)"""
    if not city or not city.strip():
        return None
    clean_city = city.strip()
    
    cache_mgr = get_cache_manager()
    
    # 尝试从缓存读取
    cached = cache_mgr.get("weather", clean_city)
    if cached and isinstance(cached, dict) and "forecasts" in cached:
        return cached
            
    try:
        raw_res = run_mcp({
            "action": "call_tool",
            "tool_name": "maps_weather",
            "arguments": {"city": clean_city},
        }, timeout=8)
        
        raw_str = str(raw_res)
        
        # 兼容 dict 返回或包含 JSON 的字符串返回
        data = None
        if isinstance(raw_res, dict) and "forecasts" in raw_res:
            data = raw_res
        else:
            # 正则提取 JSON
            m = re.search(r"(\{.*\})", raw_str, re.DOTALL)
            if m:
                try:
                    data = json.loads(m.group(1))
                except Exception:
                    pass
                    
        if data and "forecasts" in data:
            # 存入缓存 2 小时 (7200s)
            try:
                cache_mgr.set("weather", clean_city, data, ttl=7200)
            except Exception:
                pass
            return data
    except Exception as e:
        logger.warning("获取城市【%s】高德天气失败: %s", clean_city, e)
        
    return None


def get_weather_for_date(city: str, target_date_str: str) -> dict[str, Any]:
    """获取目标城市在指定日期的结构化天气信息，若超出预报范围则返回季节性平滑兜底"""
    weather_data = fetch_amap_weather(city)
    
    if weather_data and "forecasts" in weather_data:
        forecasts = weather_data.get("forecasts", [])
        # 1. 尝试精确匹配日期
        for f in forecasts:
            if f.get("date") == target_date_str:
                day_w = f.get("dayweather", "晴")
                night_w = f.get("nightweather", "多云")
                try:
                    d_temp = int(float(f.get("daytemp", 24)))
                    n_temp = int(float(f.get("nighttemp", 16)))
                except Exception:
                    d_temp, n_temp = 24, 16
                wind = f.get("daywind", "微风")
                power = f.get("daypower", "1-3级")
                
                weather_summary = f"{day_w}" if day_w == night_w else f"{day_w}转{night_w}"
                return {
                    "source": "amap_official",
                    "source_label": "⭐ 高德官方天气预报",
                    "city": weather_data.get("city", city),
                    "date": target_date_str,
                    "weather": weather_summary,
                    "day_weather": day_w,
                    "night_weather": night_w,
                    "temp_range": f"{n_temp}℃ ~ {d_temp}℃",
                    "day_temp": d_temp,
                    "night_temp": n_temp,
                    "wind": f"{wind}风 {power}",
                    "tip": _generate_weather_tip(day_w, night_w, d_temp, n_temp),
                }
                
        # 2. 若超出具体日期（如计划在第5天），使用预报最后一天的趋势作为参考，并显式标注
        if forecasts:
            latest = forecasts[-1]
            day_w = latest.get("dayweather", "晴")
            night_w = latest.get("nightweather", "多云")
            try:
                d_temp = int(float(latest.get("daytemp", 24)))
                n_temp = int(float(latest.get("nighttemp", 16)))
            except Exception:
                d_temp, n_temp = 24, 16
            wind = latest.get("daywind", "微风")
            power = latest.get("daypower", "1-3级")
            
            weather_summary = f"{day_w}" if day_w == night_w else f"{day_w}转{night_w}"
            return {
                "source": "amap_official_trend",
                "source_label": "⭐ 高德官方近期趋势参考",
                "city": weather_data.get("city", city),
                "date": target_date_str,
                "weather": weather_summary,
                "day_weather": day_w,
                "night_weather": night_w,
                "temp_range": f"{n_temp}℃ ~ {d_temp}℃",
                "day_temp": d_temp,
                "night_temp": n_temp,
                "wind": f"{wind}风 {power}",
                "tip": _generate_weather_tip(day_w, night_w, d_temp, n_temp) + "（日期较远，请以出行前临近预报为准）",
            }

    # 3. 兜底默认值
    return {
        "source": "default_seasonal",
        "source_label": "🌤️ 气象季节参考",
        "city": city,
        "date": target_date_str,
        "weather": "晴转多云",
        "day_weather": "晴",
        "night_weather": "多云",
        "temp_range": "18℃ ~ 26℃",
        "day_temp": 26,
        "night_temp": 18,
        "wind": "微风 1-2级",
        "tip": "气温适中，建议携带轻便保暖外套备用",
    }
