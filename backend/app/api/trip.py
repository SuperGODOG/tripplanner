"""旅行规划 API"""
import re, traceback
from datetime import date, timedelta
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from ..models.schemas import TripRequest, TripPlan, IntercityTransport
from ..graph.builder import get_trip_graph
from ..memory.manager import get_memory

router = APIRouter(prefix="/api", tags=["trip"])


@router.get("/profile")
async def get_profile():
    memory = get_memory()
    profile = memory.get_profile()
    return {"trip_count": memory.trip_count, "ready": memory.trip_count >= 5,
            "profile": profile if memory.trip_count >= 5 else {}}


@router.post("/trip", response_model=TripPlan)
async def plan_trip(request: TripRequest):
    try:
        graph = get_trip_graph()
        memory = get_memory()

        start = request.start_date or date.today().isoformat()
        date_list = [(date.fromisoformat(start) + timedelta(days=i)).isoformat() for i in range(request.days)]

        # ── 城际交通计算（API 层，不占 LangGraph Node） ──
        intercity, ic_error = _compute_intercity(request.origin, request.city, request.transport_mode) if request.origin else (None, None)

        # 写入记忆
        memory.add(f"目的地: {request.city}", "observe")
        if request.origin:
            memory.add(f"出发地: {request.origin}", "observe")
        memory.add(f"出行方式: {request.transport_mode}", "observe")
        for pref in request.preferences:
            memory.add(f"偏好: {pref}", "observe")
        if intercity and intercity.distance_category:
            memory.add(f"距离分类: {intercity.distance_category}", "observe")
        memory.trip_count += 1
        memory._save()

        state = {
            "origin": request.origin,
            "city": request.city,
            "days": request.days,
            "start_date": start,
            "date_list": date_list,
            "transport_mode": request.transport_mode,
            "preferences": request.preferences,
            "intercity_distance_km": intercity.distance_km if intercity else 0,
            "intercity_duration_h": intercity.duration_hours if intercity else 0,
            "intercity_cost": intercity.estimated_cost if intercity else 0,
            "distance_category": intercity.distance_category if intercity else "",
            "attraction_data": "", "weather_data": "", "hotel_data": "", "center_lng": 0, "center_lat": 0, "attraction_coords": [],
            "attraction_status": "", "weather_status": "", "hotel_status": "",
            "final_plan": {}, "error_log": [ic_error] if ic_error else [],
            "user_profile": {},
        }

        result = graph.invoke(state)
        plan_data = result.get("final_plan", {})
        errors = result.get("error_log", [])

        return TripPlan(
            city=plan_data.get("city", request.city),
            origin=request.origin,
            start_date=start,
            days=plan_data.get("days", []),
            weather_info=plan_data.get("weather_info", []),
            overall_suggestions=plan_data.get("overall_suggestions", ""),
            budget=plan_data.get("budget", {}),
            intercity_transport=intercity,
            user_profile=result.get("user_profile", {}),
            is_fallback=plan_data.get("status") == "fallback" or len(errors) > 0,
            errors=errors,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/trip/stream")
async def plan_trip_stream(
    city: str, days: int = 3,
    origin: str = "", start_date: str = "",
    transport_mode: str = "高铁",
    preferences: str = "",  # comma-separated
):
    """SSE 流式端点——前端实时看到每个 Node 进度"""
    import json, asyncio, queue
    from ..graph.events import SSEEmitter
    from ..graph.nodes import set_emitter

    emitter = SSEEmitter()

    async def event_stream():
        try:
            prefs = [p.strip() for p in preferences.split(",") if p.strip()]
            start = start_date or date.today().isoformat()
            date_list = [(date.fromisoformat(start) + timedelta(days=i)).isoformat() for i in range(days)]
            intercity, ic_error = _compute_intercity(origin, city, transport_mode) if origin else (None, None)

            memory = get_memory()
            memory.add(f"目的地: {city}", "observe")
            if origin: memory.add(f"出发地: {origin}", "observe")
            memory.add(f"出行方式: {transport_mode}", "observe")
            for p in prefs: memory.add(f"偏好: {p}", "observe")
            if intercity and intercity.distance_category: memory.add(f"距离分类: {intercity.distance_category}", "observe")
            memory.trip_count += 1; memory._save()

            state = {
                "origin": origin, "city": city, "days": days,
                "start_date": start, "date_list": date_list,
                "transport_mode": transport_mode, "preferences": prefs,
                "intercity_distance_km": intercity.distance_km if intercity else 0,
                "intercity_duration_h": intercity.duration_hours if intercity else 0,
                "intercity_cost": intercity.estimated_cost if intercity else 0,
                "distance_category": intercity.distance_category if intercity else "",
                "attraction_data": "", "weather_data": "", "hotel_data": "", "center_lng": 0, "center_lat": 0, "attraction_coords": [],
                "attraction_status": "", "weather_status": "", "hotel_status": "",
                "final_plan": {}, "error_log": [], "user_profile": {},
            }

            # 发送连接成功事件
            yield f"data: {json.dumps({'node': 'connected', 'status': 'ok', 'data': {}}, ensure_ascii=False)}\n\n"

            set_emitter(emitter)
            graph = get_trip_graph()

            # 在 executor 中运行同步 graph.invoke()，避免阻塞事件循环
            import concurrent.futures
            loop = asyncio.get_running_loop()
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = loop.run_in_executor(pool, lambda: graph.invoke(state))

                # 轮询：从线程安全 queue 中取事件，逐个 yield
                while not future.done():
                    drained = False
                    while True:
                        try:
                            event = emitter.get_nowait()
                            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                            drained = True
                        except queue.Empty:
                            break
                    # 有事件时立即继续轮询（无延迟），无事件时才 sleep 50ms
                    if drained:
                        await asyncio.sleep(0)
                    else:
                        await asyncio.sleep(0.05)

                # 排空残余事件（graph 已完成，最后再排一次）
                while not emitter.empty():
                    try:
                        event = emitter.get_nowait()
                        yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                    except queue.Empty:
                        break

                result = future.result()
            set_emitter(None)

            # 最终结果
            plan_data = result.get("final_plan", {})
            errors = result.get("error_log", [])
            final_event = {
                "node": "done", "status": "complete",
                "data": {
                    "city": plan_data.get("city", city),
                    "days": plan_data.get("days", []),
                    "weather_info": plan_data.get("weather_info", []),
                    "overall_suggestions": plan_data.get("overall_suggestions", ""),
                    "budget": plan_data.get("budget", {}),
                    "intercity": {
                        "mode": transport_mode,
                        "distance_km": intercity.distance_km if intercity else 0,
                        "distance_category": intercity.distance_category if intercity else "",
                        "estimated_cost": intercity.estimated_cost if intercity else 0,
                        "duration_hours": intercity.duration_hours if intercity else 0,
                    } if intercity else None,
                    "is_fallback": plan_data.get("status") == "fallback" or len(errors) > 0,
                    "errors": errors,
                },
            }
            yield f"data: {json.dumps(final_event, ensure_ascii=False)}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'node': 'error', 'status': 'error', 'data': {'message': str(e)}}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        }
    )


# ── 城际交通计算（纯 API + 本地计算，不占图 Node） ──

_FALLBACK_DISTANCES = {
    ("上海", "北京"): 1200, ("北京", "上海"): 1200,
    ("上海", "杭州"): 170, ("杭州", "上海"): 170,
    ("北京", "天津"): 130, ("天津", "北京"): 130,
    ("广州", "深圳"): 140, ("深圳", "广州"): 140,
}


def _compute_intercity(origin: str, city: str, mode: str) -> tuple[IntercityTransport | None, str | None]:
    """计算城际交通距离/费用/时间。失败时返回 fallback 估算 + 降级提示。"""
    if not origin or origin == city:
        return None, None

    from ..services.amap_service import get_amap_mcp_tool

    try:
        mcp = get_amap_mcp_tool()

        # 地理编码
        geo_o = str(mcp.run({"action": "call_tool", "tool_name": "maps_geo", "arguments": {"address": origin}}))
        geo_d = str(mcp.run({"action": "call_tool", "tool_name": "maps_geo", "arguments": {"address": city}}))

        def get_coord(s):
            m = re.search(r'\"location\"\s*:\s*\"([\d.]+),([\d.]+)\"', s)
            return (float(m.group(1)), float(m.group(2))) if m else None

        oc, dc = get_coord(geo_o), get_coord(geo_d)

        if not oc or not dc:
            return _intercity_fallback(origin, city, mode, "地理编码失败")

        # 距离测量（lng,lat 格式）
        dist_raw = str(mcp.run({"action": "call_tool", "tool_name": "maps_distance",
                                 "arguments": {"origins": f"{oc[0]},{oc[1]}",
                                               "destination": f"{dc[0]},{dc[1]}",
                                               "type": "1"}}))
        dm = re.search(r'\"distance\"\s*:\s*\"(\d+)\"', dist_raw)
        dur_m = re.search(r'\"duration\"\s*:\s*\"(\d+)\"', dist_raw)
        if not dm:
            return _intercity_fallback(origin, city, mode, "距离测量失败")

        km = int(dm.group(1)) / 1000
        dur = int(dur_m.group(1)) / 3600 if dur_m else round(km / 250, 1)
        cat = "短途" if km < 300 else ("中途" if km < 800 else "长途")

        rates = {"高铁": 0.5, "飞机": 1.2, "自驾": 0.8}
        rate = rates.get(mode, 0.5)
        cost = 500 if (mode == "飞机" and km < 500) else int(km * rate)

        print(f"  ✅ 城际交通: {origin}→{city} {km:.0f}km {dur}h ¥{cost} (高德API)")
        return IntercityTransport(mode=mode, distance_km=round(km, 1), distance_category=cat,
                                   estimated_cost=cost, duration_hours=round(dur, 1)), None

    except Exception:
        return _intercity_fallback(origin, city, mode, "API 调用异常")


def _intercity_fallback(origin: str, city: str, mode: str, reason: str) -> tuple[IntercityTransport, str]:
    km = _FALLBACK_DISTANCES.get((origin, city), 500)
    cat = "短途" if km < 300 else ("中途" if km < 800 else "长途")
    rates = {"高铁": 0.5, "飞机": 1.2, "自驾": 0.8}
    cost = 500 if (mode == "飞机" and km < 500) else int(km * rates.get(mode, 0.5))
    dur = round(km / 250, 1)
    msg = f"城际交通: {reason}（{origin}→{city}），使用估算距离 {km}km"
    print(f"  ⚠️ {msg}")
    return IntercityTransport(mode=mode, distance_km=km, distance_category=cat,
                               estimated_cost=cost, duration_hours=dur), msg
