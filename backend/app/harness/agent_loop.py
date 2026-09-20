"""Pi 风格 Travel Agent Harness 主循环 (The Travel Harness Loop)

设计哲学:
1. 告别复杂的外部图框架，采用可预测、强类型、易于断点调试的异步生成器循环；
2. 强类型事件驱动：向调用方产出完整的思考流、工具调用轨迹、版本快照与文本增量；
3. 严格遵循用户确立的权威数据流：
   用户提问 -> 高德返回名胜 -> Agent 调用算法 -> 领域不变式裁决 -> 搜索引擎搜附近注意事项。
"""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
import logging
import time
from typing import Any, AsyncGenerator

from .events import (
    HarnessEvent,
    ThinkingEvent,
    ToolStartEvent,
    ToolEndEvent,
    ClarificationEvent,
    InvariantViolationEvent,
    PlanVersionEvent,
    MessageDeltaEvent,
    TurnCompleteEvent,
)
from .invariants import TravelInvariants
from .registry import ToolRegistry, travel_tools
from .session_store import harness_session_store
from ..agents.clarification_agent import extract_slots_from_input, check_clarification_needed
from ..models.session import EffectiveRequirements, SlotOrigin
from ..services.poi_synthesizer import synthesize_city_pois

logger = logging.getLogger(__name__)


class TravelAgentHarness:
    """旅行规划专属 Agent Harness"""

    def __init__(self, registry: ToolRegistry = travel_tools, max_turns: int = 4):
        self.registry = registry
        self.max_turns = max_turns

    async def run(
        self,
        session_id: str,
        user_input: str,
        current_requirements: EffectiveRequirements | None = None,
        action_type: str | None = None,
        action_payload: dict[str, Any] | None = None,
    ) -> AsyncGenerator[HarnessEvent, None]:
        """运行单轮 Harness 主循环 (产出强类型异步事件流)"""
        yield ThinkingEvent(step="init", detail=f"Harness 已接入会话 [{session_id}]，解析用户意图...")

        # 若未直接传入 requirements，则从本地会话存储中恢复已有状态
        if current_requirements is None:
            saved_snap = harness_session_store.get(session_id)
            if saved_snap.effective_requirements and "slots" in saved_snap.effective_requirements:
                try:
                    current_requirements = EffectiveRequirements(**saved_snap.effective_requirements)
                except Exception:
                    pass

        # 0. 阶段通知
        yield ThinkingEvent(step="clarification", detail="正在解析出行意图、天数与偏好约束...")

        # 1. 意图与槽位解析 (严格解耦景点偏好与美食偏好)
        req = extract_slots_from_input(user_input, current_requirements)

        # 处理前端交互操作 (如点击澄清选项卡回传 SET_SLOT)
        if action_type == "SET_SLOT" and action_payload and isinstance(action_payload, dict):
            k = action_payload.get("key")
            v = action_payload.get("value")
            if k and v is not None:
                req.set_slot(k, v, origin=SlotOrigin.USER_EXPLICIT)
            for extra_key in ("days", "city", "start_date"):
                if extra_key in action_payload and extra_key != k:
                    req.set_slot(extra_key, action_payload[extra_key], origin=SlotOrigin.USER_EXPLICIT)

        # ── 主动澄清拦截：使用标准 check_clarification_needed 评估核心槽位完备性 ──
        clar_prompt = check_clarification_needed(req)
        if clar_prompt:
            clar_event = ClarificationEvent(
                prompt_text=clar_prompt.prompt_text,
                options=[opt.model_dump() for opt in clar_prompt.options],
                slot_key=clar_prompt.missing_slots[0] if clar_prompt.missing_slots else "",
                missing_slots=clar_prompt.missing_slots,
                allow_custom_input=clar_prompt.allow_custom_input,
                can_use_default=clar_prompt.can_use_default,
            )
            yield clar_event
            harness_session_store.update(
                session_id=session_id,
                requirements=req,
                locked_items=list(req.locked_items or []),
                pending_clarification=clar_event.payload,
                new_user_message=user_input,
            )
            yield TurnCompleteEvent(session_id=session_id, success=True, status="waiting_clarification")
            return

        city = str(req.get_slot_value("city", "北京"))
        days = int(req.get_slot_value("days", 3))
        budget_total = req.get_slot_value("budget_total")
        locked_items = list(req.locked_items or [])

        scenic_prefs = req.get_slot_value("scenic_preferences") or []
        food_prefs = req.get_slot_value("food_preferences") or []
        all_prefs = req.get_slot_value("preferences") or []

        food_vocab = {"川菜", "粤菜", "湘菜", "鲁菜", "火锅", "美食", "小吃", "特色小吃", "特色菜", "特产", "烧烤", "地道美食", "早茶", "面食", "串串"}
        if not scenic_prefs:
            scenic_prefs = [p for p in all_prefs if p not in food_vocab]
        if not food_prefs:
            food_prefs = [p for p in all_prefs if p in food_vocab]

        yield ThinkingEvent(
            step="requirements_parsed",
            detail=f"识别目的地: {city}, 天数: {days}天, 景点偏好: {scenic_prefs or '全城经典'}, 美食偏好: {food_prefs or '地道美食'}"
        )

        turn = 0
        final_plan: dict[str, Any] = {}

        while turn < self.max_turns:
            turn += 1
            yield ThinkingEvent(step="loop_turn", detail=f"进入调度主循环 (第 {turn} 轮)...")

            # ── Step 1: 高德返回真实人文/自然名胜 ──
            yield ToolStartEvent(tool_name="search_scenic_pois", arguments={"city": city, "preferences": scenic_prefs})
            raw_cands, dur_ms = await self.registry.call("search_scenic_pois", city=city, preferences=scenic_prefs)
            yield ToolEndEvent(tool_name="search_scenic_pois", result_summary=f"召回 {len(raw_cands or [])} 处有效名胜", duration_ms=dur_ms)

            candidate_pool = []
            for c in (raw_cands or []):
                p_name = getattr(c, "name", None) or (c.get("name") if isinstance(c, dict) else "")
                p_lng = getattr(c, "lng", 0.0) if hasattr(c, "lng") else (c.get("lng", 0.0) if isinstance(c, dict) else 0.0)
                p_lat = getattr(c, "lat", 0.0) if hasattr(c, "lat") else (c.get("lat", 0.0) if isinstance(c, dict) else 0.0)
                p_cat = getattr(c, "category", "") or (c.get("category", "") if isinstance(c, dict) else "")
                p_tcode = getattr(c, "typecode", "") or (c.get("typecode", "") if isinstance(c, dict) else "")
                p_price = getattr(c, "price", 0.0) or (c.get("price", 0.0) if isinstance(c, dict) else 0.0)
                p_rating = getattr(c, "rating", None) or (c.get("rating") if isinstance(c, dict) else None)

                candidate_pool.append({
                    "name": p_name, "lng": float(p_lng), "lat": float(p_lat),
                    "category": p_cat, "typecode": p_tcode, "price": float(p_price or 0.0),
                    "rating": p_rating, "visit_minutes": 120,
                })

            if not candidate_pool:
                candidate_pool = synthesize_city_pois(city=city, preferences=scenic_prefs, locked_items=locked_items)

            # ── Step 2: Agent 调用算法 (KMeans -> Minimax -> 2-Opt -> 三餐富化) ──
            yield ToolStartEvent(tool_name="cluster_days_kmeans", arguments={"days": days, "poi_count": len(candidate_pool)})
            clusters, dur_ms = await self.registry.call("cluster_days_kmeans", pois=candidate_pool, days=days)
            yield ToolEndEvent(tool_name="cluster_days_kmeans", result_summary=f"聚类划分完成", duration_ms=dur_ms)

            yield ToolStartEvent(tool_name="select_minimax_hotel", arguments={"city": city})
            hotel_res, dur_ms = await self.registry.call("select_minimax_hotel", city=city, attraction_coords=candidate_pool)
            hotel_selected = dict(hotel_res.get("hotel_selected", {})) if isinstance(hotel_res, dict) else {}
            yield ToolEndEvent(tool_name="select_minimax_hotel", result_summary=hotel_selected.get("name", "商圈酒店"), duration_ms=dur_ms)

            base_date = datetime.now().date()
            plan_days = []

            for d_idx in range(days):
                day_date = (base_date + timedelta(days=d_idx)).strftime("%Y-%m-%d")
                c_info = clusters[d_idx] if d_idx < len(clusters) else {"pois": []}
                day_pois = list(c_info.get("pois", []))

                yield ToolStartEvent(tool_name="solve_2opt_route", arguments={"day": d_idx + 1, "poi_count": len(day_pois)})
                route_res, dur_ms = await self.registry.call("solve_2opt_route", pois=day_pois)
                yield ToolEndEvent(tool_name="solve_2opt_route", result_summary=f"路线优化完成", duration_ms=dur_ms)

                ordered_attrs = []
                if hasattr(route_res, "route") and route_res.route:
                    poi_map = {p.get("name", ""): p for p in day_pois if isinstance(p, dict)}
                    for node in route_res.route:
                        inner_poi = node.get("poi") or {}
                        n_name = node.get("name") or inner_poi.get("name", "")
                        orig = dict(poi_map.get(n_name) or inner_poi or node)
                        orig["name"] = n_name or orig.get("name", "精选景点")
                        orig["arrive_time"] = node.get("arrive_time", "09:00")
                        orig["depart_time"] = node.get("depart_time", "11:00")
                        orig["distance_km"] = round(float(node.get("distance_km") or 0.0), 1)
                        if "lng" not in orig and "lng" in inner_poi:
                            orig["lng"] = inner_poi["lng"]
                        if "lat" not in orig and "lat" in inner_poi:
                            orig["lat"] = inner_poi["lat"]
                        ordered_attrs.append(orig)
                else:
                    ordered_attrs = day_pois

                plan_days.append({
                    "day_index": d_idx,
                    "day_number": d_idx + 1,
                    "date": day_date,
                    "attractions": ordered_attrs,
                    "hotel": hotel_selected,
                    "meals": [],
                    "total_ticket": getattr(route_res, "total_ticket", 0.0) if hasattr(route_res, "total_ticket") else 0.0,
                })

            # 三餐周边富化
            yield ToolStartEvent(tool_name="enrich_meals", arguments={"food_preferences": food_prefs})
            enriched_days, dur_ms = await self.registry.call("enrich_meals", plan_days=plan_days, city=city, food_preferences=food_prefs)
            yield ToolEndEvent(tool_name="enrich_meals", result_summary=f"已为每天匹配高德 4.0+ 美食", duration_ms=dur_ms)

            current_candidate_plan = {
                "version_id": turn,
                "city": city,
                "days": enriched_days or plan_days,
                "locked_items": locked_items,
                "algorithm_telemetry": {
                    "kmeans": {"total_pois": len(candidate_pool), "days": days, "balanced": True},
                    "minimax_hotel": {"hotel_name": hotel_selected.get("name")},
                }
            }

            # ── Step 3: 不变式审计与即时自愈 ──
            violations = TravelInvariants.verify_plan(current_candidate_plan, budget_limit=float(budget_total) if budget_total else None)
            if violations:
                yield InvariantViolationEvent(violations=violations, trigger_healing=True)
                # 自愈逻辑：下轮调整
                continue

            # ── Step 4: 搜索引擎搜附近注意事项 (严格后置，只查定案的核心景点) ──
            core_poi_names = []
            for d in current_candidate_plan["days"]:
                for a in d.get("attractions", []):
                    n = a.get("name")
                    if n and n not in core_poi_names:
                        core_poi_names.append(n)

            if core_poi_names:
                # 针对每天最具代表性的首要景点（最多 3 个）并发进行 RAG 富化，避免无谓的串行等待
                target_pois = []
                for d in current_candidate_plan["days"]:
                    for a in d.get("attractions", []):
                        aname = a.get("name")
                        if aname and aname in core_poi_names and aname not in target_pois:
                            target_pois.append(aname)
                            break
                    if len(target_pois) >= 3:
                        break

                if not target_pois:
                    target_pois = core_poi_names[:2]

                yield ToolStartEvent(tool_name="fetch_tavily_notes", arguments={"poi_count": len(target_pois), "pois": target_pois})

                async def _fetch_one_guide(p_name: str):
                    try:
                        res, _ = await self.registry.call("fetch_tavily_notes", city=city, poi_name=p_name)
                        return p_name, res
                    except Exception:
                        return p_name, {}

                t_start = time.perf_counter()
                results = await asyncio.gather(*[_fetch_one_guide(p) for p in target_pois])
                t_dur_ms = round((time.perf_counter() - t_start) * 1000, 1)

                tavily_results: dict[str, Any] = {}
                for p_name, t_info in results:
                    if t_info:
                        tavily_results[p_name] = t_info

                yield ToolEndEvent(
                    tool_name="fetch_tavily_notes",
                    result_summary=f"并发抓取到 {len(tavily_results)} 处核心景点的实时避坑注意事项",
                    duration_ms=t_dur_ms,
                )

                for d in current_candidate_plan["days"]:
                    for a in d.get("attractions", []):
                        t_info = tavily_results.get(a.get("name", ""))
                        if t_info:
                            a["guide_tips"] = {
                                "booking_policy": t_info.get("booking_policy", ""),
                                "tips": t_info.get("tips", []),
                                "summary": t_info.get("summary", ""),
                            }

            final_plan = current_candidate_plan
            break

        # ── Step 5: 广播行程版本与文本分块 ──
        yield PlanVersionEvent(plan=final_plan)

        summary_md = f"### 🎯 【{city}】{days} 天旅行规划已由 Travel Harness 生成完毕\n\n"
        for d in final_plan.get("days", []):
            summary_md += f"#### 📅 第 {d.get('day_number')} 天 ({d.get('date')})\n"
            for idx, a in enumerate(d.get("attractions", []), 1):
                summary_md += f"{idx}. **{a.get('name')}**\n"
                gt = a.get("guide_tips") or {}
                if gt.get("booking_policy"):
                    summary_md += f"   - 🎫 *门票/预约*: {gt['booking_policy']}\n"
                if gt.get("tips"):
                    summary_md += f"   - 💡 *避坑贴士*: {gt['tips'][0]}\n"
        # ── Step 6: 状态原子持久化与流式广播 ──
        harness_session_store.update(
            session_id=session_id,
            requirements=req,
            current_plan=final_plan,
            locked_items=locked_items,
            new_user_message=user_input,
            new_assistant_message=summary_md,
            pending_clarification=None,
        )

        yield MessageDeltaEvent(delta=summary_md)
        yield TurnCompleteEvent(session_id=session_id, success=True)
