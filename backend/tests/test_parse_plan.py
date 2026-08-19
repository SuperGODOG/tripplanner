"""Planner JSON 解析容错 — 缺失围栏 / 截断 / 文本包裹"""
import pytest

from conftest import FakePlanner


def parse(response: str) -> dict:
    return FakePlanner(response)._parse_plan(response)


def test_json_fence_ok():
    plan = parse("```json\n{\"city\": \"北京\"}\n```")
    assert plan["city"] == "北京"


def test_missing_closing_fence_raises():
    with pytest.raises(ValueError, match="未闭合"):
        parse("```json\n{\"city\": \"北京\"}")


def test_plain_json_without_fence():
    plan = parse("{\"city\": \"北京\"}")
    assert plan["city"] == "北京"


def test_text_wrapped_json():
    plan = parse("好的，这是您的计划：\n{\"city\": \"北京\", \"days\": []}\n希望您喜欢！")
    assert plan["city"] == "北京"


def test_truncated_json_raises():
    with pytest.raises(Exception):
        parse("{\"city\": \"北京\", \"days\": [{\"date\": \"2026-08-21\"")


def test_no_json_at_all_raises():
    with pytest.raises(ValueError, match="无法从响应中提取"):
        parse("抱歉，我无法生成计划。")
