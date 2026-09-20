"""工具缓存切面装饰器 (Tool Cache Decorator)

为确定性规划工具（路线规划、空间聚类）与动态事实核验/攻略检索工具提供无侵入缓存装饰器。
基于参数依赖指纹实现毫秒级命中与天级隔离局部复用。
"""
from __future__ import annotations

import functools
import inspect
import logging
from typing import Any, Callable, get_type_hints
from pydantic import BaseModel

from ..services.cache_service import compute_fingerprint, get_cache_manager

logger = logging.getLogger(__name__)


def make_route_cache_key(
    pois: list[dict[str, Any]],
    start_hour: int = 9,
    close_hour: int = 20,
    start_hotel: dict[str, Any] | None = None,
    day_index: int = 0,
    immutable_names: list[str] | None = None,
    **_kwargs: Any,
) -> dict[str, Any]:
    """路线求解工具专用的关键特征参数归一化提取器

    排除饮食偏好、整体预算等无关扰动，仅保留路线数学求解严格依赖的特征：
    - 景点名集合及其经纬度与游玩时长（按景点名稳定排序）
    - 起止时间窗
    - 酒店坐标
    - 锁定景点列表
    """
    normalized_pois = []
    for p in pois:
        normalized_pois.append({
            "name": p.get("name"),
            "lng": round(float(p.get("lng", 0)), 5) if p.get("lng") is not None else None,
            "lat": round(float(p.get("lat", 0)), 5) if p.get("lat") is not None else None,
            "visit_minutes": p.get("visit_minutes", 60),
            "open_time": p.get("open_time"),
            "close_time": p.get("close_time"),
        })
    normalized_pois.sort(key=lambda x: x.get("name") or "")

    hotel_coord = None
    if start_hotel and start_hotel.get("lng") is not None and start_hotel.get("lat") is not None:
        hotel_coord = {
            "lng": round(float(start_hotel["lng"]), 5),
            "lat": round(float(start_hotel["lat"]), 5),
        }

    return {
        "pois": normalized_pois,
        "start_hour": start_hour,
        "close_hour": close_hour,
        "hotel": hotel_coord,
        "immutable_names": sorted(immutable_names or []),
    }


def cached_tool_result(
    tool_name: str,
    key_builder: Callable[..., Any] | None = None,
    ttl: int = 86400,
    scope_builder: Callable[..., str] | None = None,
):
    """工具结果缓存装饰器

    参数:
    - tool_name: 工具名称（作为缓存命名空间）
    - key_builder: 从被装饰工具入参中提取计算依赖指纹的最小特征集
    - ttl: 缓存存活时间（秒），默认 1 天 (86400s)
    - scope_builder: 从入参提取作用域（如特定租户/会话）
    """
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        sig = inspect.signature(func)

        # 尝试解析返回类型，用于精确反序列化 Pydantic 模型
        return_cls: type[BaseModel] | None = None
        list_item_cls: type[BaseModel] | None = None
        try:
            import typing
            hints = get_type_hints(func)
            ret_hint = hints.get("return")
            if isinstance(ret_hint, type) and issubclass(ret_hint, BaseModel):
                return_cls = ret_hint
            elif typing.get_origin(ret_hint) in (list, list):
                args = typing.get_args(ret_hint)
                if args and isinstance(args[0], type) and issubclass(args[0], BaseModel):
                    list_item_cls = args[0]
        except Exception:
            return_cls = None
            list_item_cls = None

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            cache = get_cache_manager()
            if not cache.enabled:
                return func(*args, **kwargs)

            # 绑定实参与默认参数
            bound = sig.bind_partial(*args, **kwargs)
            bound.apply_defaults()
            all_kwargs = bound.arguments

            # 提取参与计算指纹的关键参数
            if key_builder is not None:
                try:
                    cache_params = key_builder(**all_kwargs)
                except Exception as e:
                    logger.warning("key_builder 计算指纹参数失败，直接执行工具: %s", e)
                    return func(*args, **kwargs)
            else:
                cache_params = all_kwargs

            # 提取 scope
            scope = "public"
            if scope_builder is not None:
                try:
                    scope = str(scope_builder(**all_kwargs))
                except Exception:
                    scope = "public"

            fingerprint = compute_fingerprint(cache_params)

            # 1. 尝试读缓存
            cached_val = cache.get(tool_name, fingerprint, scope=scope)
            if cached_val is not None:
                logger.debug("工具 [%s] 命中指纹缓存: %s (scope: %s)", tool_name, fingerprint, scope)
                if return_cls is not None and isinstance(cached_val, dict):
                    try:
                        return return_cls.model_validate(cached_val)
                    except Exception:
                        pass
                elif list_item_cls is not None and isinstance(cached_val, list):
                    try:
                        return [
                            list_item_cls.model_validate(item) if isinstance(item, dict) else item
                            for item in cached_val
                        ]
                    except Exception:
                        pass
                return cached_val

            # 2. 执行原工具
            result = func(*args, **kwargs)

            # 3. 写入缓存
            try:
                if isinstance(result, BaseModel):
                    to_cache = result.model_dump()
                elif isinstance(result, list):
                    to_cache = [
                        x.model_dump() if isinstance(x, BaseModel) else x
                        for x in result
                    ]
                else:
                    to_cache = result
                cache.set(tool_name, fingerprint, to_cache, ttl=ttl, scope=scope)
            except Exception as e:
                logger.warning("工具 [%s] 写入指纹缓存失败: %s", tool_name, e)

            return result

        wrapper.raw_func = func  # type: ignore
        return wrapper

    return decorator
