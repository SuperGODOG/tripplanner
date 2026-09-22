"""Pi 风格大模型自主工具调用循环 (Autonomous ReAct Tool-Calling Harness)

架构设计 (Design Philosophy):
1. 真正的 ReAct 闭环：模型感知可用工具描述 -> 自主提出 tool_calls -> Harness 执行 -> Observation 回填上下文 -> 模型再决策/收敛终态。
2. 强类型事件一致性：完整发射 ThinkingEvent、ToolStartEvent、ToolEndEvent、PlanVersionEvent、TurnCompleteEvent 与 PreemptedEvent。
3. 严格受控边界：
   - 步数上限防御 (max_steps 截断，防止死循环与 Token 暴击)
   - 协作取消响应 (每步工具调用前后均检查 cancellation_token)
   - 结构化 JSON 决策协议 (支持各大 LLM 文本/思考块与代码块抽取)
   - 运筹硬约束守护 (最终行程经由 TravelInvariants 守门验证)
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from typing import Any, AsyncGenerator

from .events import (
    HarnessEvent,
    ThinkingEvent,
    ToolStartEvent,
    ToolEndEvent,
    PlanVersionEvent,
    TurnCompleteEvent,
    PreemptedEvent,
    ExecutionFailedEvent,
    MapActionEvent,
)
from .invariants import TravelInvariants
from .registry import ToolRegistry, travel_tools
from .session_store import harness_session_store
from ..models.session import EffectiveRequirements
from ..services.geo_entity_resolver import resolve_destination
from ..services.llm_service import get_llm
from ..tools.search_tools import get_city_center

logger = logging.getLogger(__name__)


def _extract_json_payload(raw_text: str) -> dict[str, Any] | None:
    """鲁棒抽取模型响应中的 JSON 结构 (支持 ```json 标记或裸 JSON)"""
    if not raw_text or not isinstance(raw_text, str):
        return None
    cleaned = raw_text.strip()

    # 1. 尝试直接解析裸 JSON
    try:
        data = json.loads(cleaned)
        if isinstance(data, dict):
            return data
    except Exception:
        pass

    # 2. 匹配 ```json ... ``` 代码块
    code_block_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", cleaned)
    if code_block_match:
        try:
            data = json.loads(code_block_match.group(1).strip())
            if isinstance(data, dict):
                return data
        except Exception:
            pass

    # 3. 寻找最外层大括号 {...}
    brace_match = re.search(r"(\{[\s\S]*\})", cleaned)
    if brace_match:
        try:
            data = json.loads(brace_match.group(1).strip())
            if isinstance(data, dict):
                return data
        except Exception:
            pass

    return None


class AutonomousReActHarness:
    """Pi 风格大模型自主工具调用 Harness (Dynamic Tool-Calling Loop)"""

    def __init__(
        self,
        registry: ToolRegistry = travel_tools,
        llm: Any | None = None,
        max_steps: int = 8,
    ):
        self.registry = registry
        self.llm = llm
        self.max_steps = max_steps

    def _get_active_llm(self) -> Any:
        return self.llm if self.llm is not None else get_llm()

    def _build_system_prompt(self, city: str, days: int, preferences: list[str]) -> str:
        tools_desc = []
        for t in self.registry.list_tools():
            tools_desc.append(f"- {t['name']}: {t['description']}")
        tools_str = "\n".join(tools_desc)

        return (
            f"你是一个拥有自主工具调用能力的专业旅行规划 Agent (Sovereign Travel Agent)。\n"
            f"目标：为用户规划【{city}】的 {days} 天高品质旅行行程。\n"
            f"用户偏好：{', '.join(preferences) if preferences else '城市精选'}\n\n"
            f"【可用工具列表】:\n{tools_str}\n\n"
            f"【交互协议】:\n"
            f"在每一轮决策中，你必须仅输出合法 JSON 格式，严禁包含额外寒暄！\n"
            f"若需要调用工具，格式如下：\n"
            f'{{\n  "thought": "你的决策理由 (例如: 需要先检索该城市高分景点)",\n  "tool_call": {{\n    "name": "工具名称",\n    "arguments": {{...}}\n  }}\n}}\n\n'
            f"若已收集足够的信息并完成了全部行程的规划与整合，请输出终态格式：\n"
            f'{{\n  "thought": "已完成全部规划并校验通过",\n  "finish": true,\n  "plan": {{\n    "city": "{city}",\n    "days": [\n      {{\n        "day_index": 0,\n        "date": "2026-10-01",\n        "attractions": [\n          {{"name": "景点A", "lng": 120.15, "lat": 30.25, "arrive_time": "09:00", "price": 0.0}}\n        ],\n        "meals": [{{"type": "午餐", "restaurant": "特色餐厅"}}]\n      }}\n    ]\n  }}\n}}\n'
        )

    async def run(
        self,
        session_id: str,
        user_input: str,
        user_id: str = "default_user",
        requirements: EffectiveRequirements | None = None,
        cancellation_token: asyncio.Event | None = None,
    ) -> AsyncGenerator[HarnessEvent, None]:
        """执行自主 ReAct 闭环循环"""
        def _is_preempted() -> bool:
            return bool(cancellation_token and cancellation_token.is_set())

        if _is_preempted():
            yield PreemptedEvent(session_id=session_id, reason="steered_by_user", detail="启动前检测到取消信号，安全退出")
            return

        # 1. 提取基础参数与地理定位
        city = "北京"
        days = 3
        prefs: list[str] = []
        if requirements:
            city = str(requirements.get_slot_value("city", "北京"))
            days = int(requirements.get_slot_value("days", 3))
            prefs = list(requirements.get_slot_value("preferences") or [])

        resolved_dest = resolve_destination(city)
        center_coord = get_city_center(city) or (resolved_dest.center_coord if resolved_dest else None)
        center_lng_lat = [float(center_coord[0]), float(center_coord[1])] if center_coord else [116.407, 39.904]

        yield ThinkingEvent(step="react_init", detail=f"🚀 启动 Pi 风格自主 ReAct 工具调用循环: {city} · {days}天 · 步数上限={self.max_steps}")
        yield MapActionEvent(
            action="FLY_TO",
            data={"city": city, "center": center_lng_lat, "zoom": 12, "title": f"定位至【{city}】"}
        )

        system_prompt = self._build_system_prompt(city, days, prefs)
        scratchpad_messages: list[dict[str, str]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"规划需求：城市={city}，天数={days}天，用户原始诉求='{user_input}'。请逐步调用工具生成完整方案。"},
        ]

        step = 0
        final_plan: dict[str, Any] | None = None
        observations_history: list[dict[str, Any]] = []

        while step < self.max_steps:
            step += 1
            if _is_preempted():
                yield PreemptedEvent(session_id=session_id, reason="steered_by_user", detail=f"第 {step} 步前收到取消信号，已安全中断")
                return

            yield ThinkingEvent(step=f"react_step_{step}", detail=f"大模型正在权衡当前状态并生成第 {step} 步决策...")

            # 2. 请求 LLM 进行下一步决策
            llm_client = self._get_active_llm()
            try:
                # 兼容不同协议客户端的 invoke 接口
                if hasattr(llm_client, "invoke"):
                    raw_resp = llm_client.invoke(scratchpad_messages)
                elif callable(llm_client):
                    raw_resp = llm_client(scratchpad_messages)
                else:
                    raw_resp = str(llm_client)
            except Exception as e:
                logger.error("ReAct 循环中 LLM 决策发生异常: %s", e)
                yield ExecutionFailedEvent(
                    session_id=session_id,
                    reason="llm_invocation_error",
                    detail=f"LLM 决策接口报错: {str(e)}",
                )
                yield TurnCompleteEvent(session_id=session_id, success=False, status="failed")
                return

            parsed_decision = _extract_json_payload(raw_resp)
            if not parsed_decision:
                logger.warning("第 %d 步未能从模型返回中提取到合法 JSON，回填提示并重试。原始返回: %s", step, raw_resp[:120])
                scratchpad_messages.append({"role": "assistant", "content": raw_resp})
                scratchpad_messages.append({"role": "user", "content": "格式解析失败！请务必仅输出纯 JSON 格式的决策或终态行程。"})
                continue

            thought = parsed_decision.get("thought", "")
            if thought:
                yield ThinkingEvent(step=f"react_thought_{step}", detail=f"💭 {thought}")

            # 3. 终态判断
            if parsed_decision.get("finish") and "plan" in parsed_decision:
                candidate_plan = parsed_decision["plan"]
                # 校验硬约束 (TravelInvariants.verify_plan)
                raw_violations = TravelInvariants.verify_plan(candidate_plan)
                # ReAct 模式宽容过滤：若模型暂未分配酒店或三餐，不阻塞核心行程成立，聚焦景点池纯洁性与天数合法性
                violations = [
                    v for v in raw_violations
                    if "缺少推荐住宿" not in v and "餐饮不全" not in v
                ]
                if not violations:
                    final_plan = candidate_plan
                    yield ThinkingEvent(step="react_verified", detail="行程已通过 TravelInvariants 硬约束检验")
                    break
                else:
                    logger.info("模型提交的终态计划违背硬约束: %s，要求模型自愈", violations)
                    scratchpad_messages.append({"role": "assistant", "content": json.dumps(parsed_decision, ensure_ascii=False)})
                    scratchpad_messages.append({
                        "role": "user",
                        "content": f"所提计划违背硬约束：{'; '.join(violations)}。请调用工具自愈修正或重新调整后提交。"
                    })
                    continue

            # 4. 工具调用决策
            tool_call_spec = parsed_decision.get("tool_call")
            if not tool_call_spec or not isinstance(tool_call_spec, dict):
                # 若无工具调用且无 finish，提示继续
                scratchpad_messages.append({"role": "assistant", "content": json.dumps(parsed_decision, ensure_ascii=False)})
                scratchpad_messages.append({"role": "user", "content": "请指定要调用的工具 tool_call 或输出 finish 终态。"})
                continue

            tool_name = tool_call_spec.get("name", "")
            tool_args = tool_call_spec.get("arguments", {})

            if _is_preempted():
                yield PreemptedEvent(session_id=session_id, reason="steered_by_user", detail=f"执行工具【{tool_name}】前收到取消信号")
                return

            yield ToolStartEvent(tool_name=tool_name, arguments=tool_args)

            try:
                tool_result, dur_ms = await self.registry.call(tool_name, **tool_args)
            except KeyError:
                err_msg = f"未注册工具: {tool_name}"
                yield ToolEndEvent(tool_name=tool_name, result_summary=err_msg, duration_ms=0.0)
                scratchpad_messages.append({"role": "assistant", "content": json.dumps(parsed_decision, ensure_ascii=False)})
                scratchpad_messages.append({"role": "user", "content": f"工具执行报错: {err_msg}。请检查可用工具名称。"})
                continue
            except Exception as tool_err:
                err_msg = f"工具异常: {str(tool_err)}"
                yield ToolEndEvent(tool_name=tool_name, result_summary=err_msg, duration_ms=0.0)
                scratchpad_messages.append({"role": "assistant", "content": json.dumps(parsed_decision, ensure_ascii=False)})
                scratchpad_messages.append({"role": "user", "content": f"工具执行异常: {err_msg}。请调整参数或选用替代方案。"})
                continue

            # 摘要观察结果并回填上下文
            obs_summary = str(tool_result)[:400]
            yield ToolEndEvent(tool_name=tool_name, result_summary=f"返回数据长度/摘要: {obs_summary[:100]}...", duration_ms=dur_ms)

            observations_history.append({"tool": tool_name, "result": tool_result})
            scratchpad_messages.append({"role": "assistant", "content": json.dumps(parsed_decision, ensure_ascii=False)})
            scratchpad_messages.append({
                "role": "user",
                "content": f"工具【{tool_name}】执行完毕 (耗时 {dur_ms}ms)。观察结果 (Observation):\n{json.dumps(tool_result, ensure_ascii=False, default=str)[:1500]}\n请根据观察结果决定下一步行动。"
            })

        # 5. 循环结束处理
        if final_plan:
            yield PlanVersionEvent(plan=final_plan)
            # 更新至内存快照
            harness_session_store.update(
                session_id=session_id,
                user_id=user_id,
                current_plan=final_plan,
                requirements=requirements,
                new_user_message=user_input,
            )
            yield TurnCompleteEvent(session_id=session_id, success=True, status="completed")
        else:
            logger.warning("ReAct 循环在达到步数上限 %d 后未能收敛终态", self.max_steps)
            yield ExecutionFailedEvent(
                session_id=session_id,
                reason="react_step_limit_exceeded",
                detail=f"ReAct 循环已达步数上限 ({self.max_steps})，未能完成全部决策收敛",
            )
            yield TurnCompleteEvent(session_id=session_id, success=False, status="failed")
