"""Pi 风格上下文管理与历史事实压缩器 (Pi-Style Context Compactor)

借鉴 Pi 架构精髓，实现多轮会话中的四层记忆治理与上下文压缩：
1. Level 1 (Structured Slots): 核心槽位（城市、天数、预算、锁定实体）由 EffectiveRequirements 专管，永不丢失；
2. Level 2 (Working Scratchpad): 当前轮次的用户输入与即时推理；
3. Level 3 (Sliding Window): 仅保留最近 K 轮（默认 3 轮）原始对白；
4. Level 4 (Observation Masking & Fact Summarization): 
   - 超过 K 轮的早期对话自动提炼为简短的事实摘要（[历史对话背景事实]）；
   - 历史消息中冗长工具返回（如几千字符的原始经纬度、高德底表 JSON）在跨轮次存储时自动脱敏裁剪，防止 Token 爆炸与“迷失在中间”。
"""
from __future__ import annotations

import re
import json
from typing import Any


def mask_observation_payload(text: str, max_chars: int = 200) -> str:
    """观察值脱敏与裁剪：截断长 JSON 字典或列表，保留关键实体信息"""
    if not text or len(text) <= max_chars:
        return text

    # 检测并裁剪长 JSON
    if text.strip().startswith(("{", "[")) and text.strip().endswith(("}", "]")):
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                names = [item.get("name", "") for item in parsed if isinstance(item, dict) and item.get("name")]
                if names:
                    return f"[包含 {len(parsed)} 处实体: {', '.join(names[:5])}{' 等' if len(names) > 5 else ''}]"
            elif isinstance(parsed, dict):
                keys = list(parsed.keys())
                return f"[结构体包含键: {', '.join(keys[:6])}]"
        except Exception:
            pass

    return text[:max_chars] + f"... (已对超长历史观察值进行 Pi 风格精简，共截断 {len(text) - max_chars} 字符)"


def compact_conversation_history(
    messages: list[dict[str, str]],
    keep_recent_turns: int = 3,
) -> list[dict[str, str]]:
    """将多轮对话历史进行 Pi 风格滑动窗口压缩与观察值脱敏

    入参: 原始消息列表 [{"role": "user"|"assistant", "content": "..."}]
    出参: 压缩后的消息列表（前置事实摘要 + 最近 K 轮原始对白）
    """
    if not messages:
        return []

    # 提取系统消息与普通对话
    system_msgs = [m for m in messages if m.get("role") == "system"]
    chat_msgs = [m for m in messages if m.get("role") != "system"]

    # 计算最近 K 轮（1 轮 = 1 user + 1 assistant = 2 msgs）
    max_recent_msgs = keep_recent_turns * 2
    if len(chat_msgs) <= max_recent_msgs:
        # 未超过阈值，仅执行单消息脱敏
        cleaned = []
        for m in chat_msgs:
            cleaned.append({
                "role": m.get("role", "user"),
                "content": mask_observation_payload(m.get("content", ""), max_chars=800),
            })
        return system_msgs + cleaned

    # 超过阈值：早期消息压缩，近期消息保留
    older_msgs = chat_msgs[:-max_recent_msgs]
    recent_msgs = chat_msgs[-max_recent_msgs:]

    # 提炼早期对话的事实要点
    facts: list[str] = []
    for m in older_msgs:
        role_label = "用户" if m.get("role") == "user" else "顾问"
        content = m.get("content", "").strip()
        # 清理多余空行与长标记
        clean_content = re.sub(r"\s+", " ", content)
        if len(clean_content) > 100:
            clean_content = clean_content[:100] + "..."
        if clean_content:
            facts.append(f"{role_label}: {clean_content}")

    summary_text = "；".join(facts)
    compacted_history_msg = {
        "role": "system",
        "content": f"[早期对话历史事实摘要 (Pi-Style Compacted)]: {summary_text}",
    }

    # 近期消息轻量脱敏
    cleaned_recent = []
    for m in recent_msgs:
        cleaned_recent.append({
            "role": m.get("role", "user"),
            "content": mask_observation_payload(m.get("content", ""), max_chars=1200),
        })

    return system_msgs + [compacted_history_msg] + cleaned_recent
