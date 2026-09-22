"""Pi 风格上下文压缩与观察值脱敏单测"""
from app.memory.context_compactor import (
    compact_conversation_history,
    mask_observation_payload,
)


def test_mask_observation_payload():
    short_text = "你好，我想去成都"
    assert mask_observation_payload(short_text) == short_text

    long_json = '[{"name": "故宫", "lng": 116.397, "lat": 39.917}, {"name": "天坛", "lng": 116.4, "lat": 39.8}]'
    masked = mask_observation_payload(long_json, max_chars=30)
    assert "包含 2 处实体" in masked
    assert "故宫" in masked


def test_compact_conversation_history_short():
    msgs = [
        {"role": "user", "content": "我想去成都玩3天"},
        {"role": "assistant", "content": "好的，预算大概多少？"},
    ]
    compacted = compact_conversation_history(msgs, keep_recent_turns=2)
    assert len(compacted) == 2
    assert compacted[0]["content"] == "我想去成都玩3天"


def test_compact_conversation_history_long():
    # 模拟 5 轮对话（10 条消息）
    msgs = []
    for i in range(1, 6):
        msgs.append({"role": "user", "content": f"第{i}轮提问：关于行程约束{i}"})
        msgs.append({"role": "assistant", "content": f"第{i}轮回答：为您调整了参数{i}"})

    # 保留最近 2 轮（即最后 4 条消息），前 6 条应被压缩为 1 条系统摘要
    compacted = compact_conversation_history(msgs, keep_recent_turns=2)
    
    # 结果应为 1 条系统摘要 + 4 条最近消息 = 5 条
    assert len(compacted) == 5
    assert compacted[0]["role"] == "system"
    assert "Pi-Style Compacted" in compacted[0]["content"]
    assert "第1轮提问" in compacted[0]["content"]
    assert compacted[-1]["content"] == "第5轮回答：为您调整了参数5"
