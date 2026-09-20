"""Tavily 实时 Web RAG 工具单测"""
import pytest
from unittest.mock import patch, MagicMock
from app.tools.tavily_tool import (
    search_tavily_poi_guides,
    _extract_booking_policy,
    _extract_tips,
    make_tavily_cache_key,
    is_noise_line,
)


def test_tavily_cache_key():
    key = make_tavily_cache_key("成都", "杜甫草堂")
    assert key["city"] == "成都"
    assert key["poi_name"] == "杜甫草堂"


def test_is_noise_line_filters_web_artifacts():
    # 页脚/企业信息
    assert is_noise_line("企业文化 | 广告服务 | 关于我们 | 联系我们 | 诚聘英才 | 意见建议 | 本地宝APP")
    # 面包屑导航
    assert is_noise_line("北京本地宝 > 北京旅游 > 北京旅游景点 > 景点攻略 > 北京明十三陵开放时间")
    # SEO 关键词堆叠
    assert is_noise_line("相关推荐 北京明十三陵购票入口 北京明十三陵门票 北京明十三陵")
    # 导语纯问句
    assert is_noise_line("【导语】：北京明十三陵开放时间是什么时候？北京明十三陵怎么买票？价格是多少？")

    # 正常内容不应被判定为噪音
    assert not is_noise_line("成都大熊猫繁育研究基地需提前在官方小程序实名预约门票，当日现场不设售票窗口。")
    assert not is_noise_line("旺季期间定陵成人票60元，淡季40元，建议至少提前一天在公众号订票。")


def test_extract_booking_policy_and_tips():
    text = (
        "成都大熊猫繁育研究基地需提前在官方小程序实名预约门票，当日现场不设售票窗口。"
        "园区很大，步行较多，建议早点入园游览，大熊猫上午更活跃。"
        "在拍照打卡机位方面，月亮产房是最佳观赏点，随手出大片。"
    )
    policy = _extract_booking_policy(text)
    assert "预约" in policy or "小程序" in policy

    tips = _extract_tips(text)
    assert len(tips) > 0
    assert any("大熊猫" in t or "建议" in t or "机位" in t for t in tips)


def test_extract_noise_immunity():
    """验证极端网页垃圾噪音下的鲁棒免疫力"""
    raw_dirty_text = (
        "北京本地宝 > 北京旅游 > 北京旅游景点 > 景点攻略 > 北京明十三陵开放时间、门票价格及优惠购票方式\n"
        "【导语】：北京明十三陵开放时间是什么时候？北京明十三陵怎么买票？价格是多少？\n"
        "明十三陵定陵旺季门票60元，长陵45元，需提前在官方公众号实名预约入园。\n"
        "相关推荐 北京明十三陵购票入口 北京明十三陵门票 北京明十三陵\n"
        "游览定陵地下玄宫内部温差较大，建议携带薄外套并穿着防滑鞋。\n"
        "企业文化 | 广告服务 | 关于我们 | 联系我们 | 诚聘英才 | 意见建议 | 本地宝APP\n"
    )

    policy = _extract_booking_policy(raw_dirty_text)
    assert "企业文化" not in policy
    assert "意见建议" not in policy
    assert "本地宝" not in policy
    assert "60元" in policy or "预约" in policy

    tips = _extract_tips(raw_dirty_text)
    assert len(tips) > 0
    for tip in tips:
        assert "企业文化" not in tip
        assert "意见建议" not in tip
        assert "广告服务" not in tip
        assert "相关推荐" not in tip
        assert "|" not in tip
        assert ">" not in tip


def test_tavily_search_mock_success():
    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.json.return_value = {
        "results": [
            {
                "url": "https://example.com/guide/1",
                "content": "杜甫草堂博物馆需提前在微信公众号实名预约购票。避坑指南：雨后草堂景色最雅，建议携带雨具；红墙竹影拍照极美。",
            }
        ]
    }

    with patch("requests.post", return_value=fake_resp):
        res = search_tavily_poi_guides("成都", "杜甫草堂", api_key="fake_key", use_cache=False)
        assert res["poi_name"] == "杜甫草堂"
        assert res["city"] == "成都"
        assert len(res["tips"]) > 0
        assert "https://example.com/guide/1" in res["source_urls"]


def test_tavily_search_failure_degrades_gracefully():
    with patch("requests.post", side_effect=Exception("Network timeout")):
        res = search_tavily_poi_guides("成都", "杜甫草堂", api_key="fake_key", use_cache=False)
        assert res == {}
