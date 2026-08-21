"""旅行规划 API"""
import json, re, traceback
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from uuid import UUID
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from ..models.schemas import TripRequest, TripPlan, IntercityTransport
from ..graph.builder import open_trip_graph
from ..graph.context import RequestContext
from ..memory.repository import get_memory_repository

router = APIRouter(prefix="/api", tags=["trip"])


@router.get("/profile")
async def get_profile(user_id: UUID):
    trip_count, profile = get_memory_repository().get_profile(str(user_id))
    return {"trip_count": trip_count, "ready": trip_count >= 5,
            "profile": profile if trip_count >= 5 else {}}


@router.post("/trip", response_model=TripPlan)
async def plan_trip(request: TripRequest):
    try:
        start = request.start_date or date.today().isoformat()
        date_list = [(date.fromisoformat(start) + timedelta(days=i)).isoformat() for i in range(request.days)]

        # ── API 预处理（与 /trip/stream 共用）：intercity + weather 并发 ──
        intercity, ic_error, weather_data, weather_status, weather_error = \
            _prefetch_intercity_weather(request.origin, request.city, request.transport_mode)

        _record_observations(str(request.user_id), request.city, request.transport_mode,
                             request.origin, request.preferences, intercity)

        errors_init = [e for e in (ic_error, weather_error) if e]
        state = _build_trip_state(
            user_id=str(request.user_id), budget_total=request.budget_total,
            day_start_hour=request.day_start_hour, day_end_hour=request.day_end_hour,
            origin=request.origin, city=request.city, days=request.days,
            start=start, date_list=date_list,
            transport_mode=request.transport_mode, preferences=request.preferences,
            weather_data=weather_data, weather_status=weather_status,
            intercity=intercity, errors_init=errors_init,
        )

        context = RequestContext.create(str(request.user_id))
        config = context.checkpoint_config
        graph, conn = open_trip_graph()
        try:
            result = graph.invoke(state, config)
        finally:
            conn.close()  # 每请求独享连接，用完必须显式关闭（防 fd 泄漏）
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
    city: str, user_id: UUID, days: int = Query(3, ge=1, le=14),
    origin: str = "", start_date: str = "",
    transport_mode: str = "高铁",
    preferences: str = "",  # comma-separated
):
    """SSE 流式端点——前端实时看到每个 Node 进度"""
    import json, asyncio, queue, threading
    from ..graph.events import SSEEmitter

    emitter = SSEEmitter()

    async def event_stream():
        try:
            # start_date 校验（格式 + 非过去），与 POST TripRequest 规则一致
            if start_date:
                try:
                    start_parsed = date.fromisoformat(start_date)
                except ValueError:
                    yield f"data: {json.dumps({'node': 'error', 'status': 'error', 'data': {'message': 'start_date 必须是 YYYY-MM-DD 格式的有效日期'}}, ensure_ascii=False)}\n\n"
                    return
                if start_parsed < date.today():
                    yield f"data: {json.dumps({'node': 'error', 'status': 'error', 'data': {'message': 'start_date 不能早于今天'}}, ensure_ascii=False)}\n\n"
                    return
            prefs = [p.strip() for p in preferences.split(",") if p.strip()]
            start = start_date or date.today().isoformat()
            date_list = [(date.fromisoformat(start) + timedelta(days=i)).isoformat() for i in range(days)]

            # API 预处理（与 POST /trip 共用）：intercity + weather 并发
            intercity, ic_error, weather_data, weather_status, weather_error = \
                _prefetch_intercity_weather(origin, city, transport_mode)

            _record_observations(str(user_id), city, transport_mode, origin, prefs, intercity)

            errors_init = [e for e in (ic_error, weather_error) if e]
            state = _build_trip_state(
                user_id=str(user_id), budget_total=None,
                day_start_hour=9, day_end_hour=20,
                origin=origin, city=city, days=days,
                start=start, date_list=date_list,
                transport_mode=transport_mode, preferences=prefs,
                weather_data=weather_data, weather_status=weather_status,
                intercity=intercity, errors_init=errors_init,
            )

            # 发送连接成功事件
            yield f"data: {json.dumps({'node': 'connected', 'status': 'ok', 'data': {}}, ensure_ascii=False)}\n\n"

            graph, conn = open_trip_graph()
            try:
                context = RequestContext.create(str(user_id), event_sink=emitter)
                config = context.checkpoint_config
                cancel_event = threading.Event()
                result = None

                # 在 executor 中运行同步 graph.invoke()，避免阻塞事件循环
                import concurrent.futures
                loop = asyncio.get_running_loop()
                try:
                    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                        future = loop.run_in_executor(
                            pool,
                            lambda: graph.invoke(state, config) if not cancel_event.is_set() else None
                        )

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
                except asyncio.CancelledError:
                    cancel_event.set()
                    yield f"data: {json.dumps({'node': 'cancelled', 'status': 'cancelled', 'data': {}}, ensure_ascii=False)}\n\n"
                    return
            finally:
                conn.close()  # 每请求独享连接，用完必须显式关闭（防 fd 泄漏）

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


# ── API 预处理公共函数（POST /trip 与 GET /trip/stream 共用，防双份漂移）──

def _prefetch_intercity_weather(origin: str, city: str, transport_mode: str):
    """城际交通 + 天气并发拉取（不占图 Node）。

    返回 (intercity, ic_error, weather_data, weather_status, weather_error)。
    """
    with ThreadPoolExecutor(max_workers=2) as pool:
        f_intercity = (pool.submit(_compute_intercity, origin, city, transport_mode)
                       if origin else None)
        f_weather = pool.submit(_fetch_weather, city)
        intercity, ic_error = f_intercity.result() if f_intercity else (None, None)
        weather_data, weather_status, weather_error = f_weather.result()
    return intercity, ic_error, weather_data, weather_status, weather_error


def _record_observations(user_id: str, city: str, transport_mode: str,
                         origin: str, prefs: list[str], intercity) -> None:
    """记忆写入（每次请求的观察，租户隔离）。"""
    observations = [f"目的地: {city}", f"出行方式: {transport_mode}"]
    if origin:
        observations.append(f"出发地: {origin}")
    observations.extend(f"偏好: {pref}" for pref in prefs)
    if intercity and intercity.distance_category:
        observations.append(f"距离分类: {intercity.distance_category}")
    get_memory_repository().record_trip(user_id, observations)


def _build_trip_state(*, user_id: str, budget_total, day_start_hour: int,
                      day_end_hour: int, origin: str, city: str, days: int,
                      start: str, date_list: list[str], transport_mode: str,
                      preferences: list[str], weather_data: str, weather_status: str,
                      intercity, errors_init: list[str]) -> dict:
    """构造 graph.invoke 初始 state（POST 与 SSE 共用）。"""
    return {
        "user_id": user_id, "budget_total": budget_total,
        "day_start_hour": day_start_hour, "day_end_hour": day_end_hour,
        "origin": origin, "city": city, "days": days,
        "start_date": start, "date_list": date_list,
        "transport_mode": transport_mode, "preferences": preferences,
        "intercity_distance_km": intercity.distance_km if intercity else 0,
        "intercity_duration_h": intercity.duration_hours if intercity else 0,
        "intercity_cost": intercity.estimated_cost if intercity else 0,
        "distance_category": intercity.distance_category if intercity else "",
        "attraction_data": "", "weather_data": weather_data, "hotel_data": "",
        "attraction_candidates": [], "hotel_candidates": [],
        "attraction_coords": [], "excursion_pois": [],
        "day_clusters": [], "plan_days": [], "hotel_selected": {},
        "attraction_status": "", "weather_status": weather_status, "hotel_status": "",
        "final_plan": {}, "error_log": errors_init, "user_profile": {},
    }


# ── 天气查询（API 层直接调 MCP，不占图 Node） ──

def _fetch_weather(city: str) -> tuple[str, str, str | None]:
    """直接调用 maps_weather 获取天气数据，格式化后写入 state。
    返回 (weather_data, weather_status, error_msg_or_None)
    """
    from ..services.amap_service import run_mcp
    from ..tools.amap_wrapper import AmapToolWrapper

    try:
        raw = run_mcp({"action": "call_tool", "tool_name": "maps_weather",
                       "arguments": {"city": city}})
        data = AmapToolWrapper._extract_json(raw)
        if data:
            weather_data = AmapToolWrapper._format_weather(data)
        else:
            weather_data = _weather_fallback(city)
            print(f"  ⚠️ 天气查询: 解析响应失败，使用降级文本")
            return weather_data, "success", f"天气查询: 解析响应失败，使用降级文本"

        print(f"  ✅ 天气查询: {city} (高德API)")
        return weather_data, "success", None

    except Exception as e:
        fallback = _weather_fallback(city)
        error_msg = f"天气查询失败: {str(e)}"
        print(f"  ⚠️ {error_msg}")
        return fallback, "failed", error_msg


def _weather_fallback(city: str) -> str:
    return f"【天气信息】\n- {city}: 天气数据暂不可用\n  建议：春秋季带外套，夏季注意防晒，冬季穿厚外套"


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

    from ..services.amap_service import run_mcp, geo_cached

    try:
        # 地理编码：origin/city 两次 geo 无依赖，并行提交（结果走 geo_cached 缓存）
        with ThreadPoolExecutor(max_workers=2) as pool:
            f_o = pool.submit(geo_cached, origin)
            f_d = pool.submit(geo_cached, city)
            oc, dc = f_o.result(), f_d.result()

        if not oc or not dc:
            return _intercity_fallback(origin, city, mode, "地理编码失败")

        # 距离测量（lng,lat 格式）
        dist_raw = str(run_mcp({"action": "call_tool", "tool_name": "maps_distance",
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
