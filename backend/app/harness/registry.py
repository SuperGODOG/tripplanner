"""标准化工具契约注册中心 (Typed Tool Registry)

将分散在高德服务、运筹算法和网络搜索中的原子能力封装为一等公民契约。
提供标准元数据、参数校验、执行拦截与耗时遥测。
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Callable, Coroutine

from ..tools.search_tools import (
    search_attractions_tool,
    search_hotel_minimax_tool,
    enrich_meals_tool,
    discover_hidden_gems_tool,
)
from ..tools.planning_tools import (
    cluster_pois_tool,
    solve_day_route_tool,
)
from ..tools.tavily_tool import search_tavily_poi_guides

logger = logging.getLogger(__name__)


class ToolDefinition:
    def __init__(self, name: str, description: str, func: Callable):
        self.name = name
        self.description = description
        self.func = func

    async def execute(self, **kwargs: Any) -> Any:
        start_t = time.perf_counter()
        if asyncio.iscoroutinefunction(self.func):
            res = await self.func(**kwargs)
        else:
            res = self.func(**kwargs)
        duration_ms = (time.perf_counter() - start_t) * 1000
        return res, duration_ms


class ToolRegistry:
    """工具注册中心"""

    def __init__(self):
        self._registry: dict[str, ToolDefinition] = {}

    def register(self, name: str, description: str) -> Callable:
        def decorator(fn: Callable) -> Callable:
            self._registry[name] = ToolDefinition(name, description, fn)
            return fn
        return decorator

    def get_tool(self, name: str) -> ToolDefinition | None:
        return self._registry.get(name)

    async def call(self, name: str, **kwargs: Any) -> tuple[Any, float]:
        tool = self.get_tool(name)
        if not tool:
            raise KeyError(f"Tool {name} 未在注册中心注册")
        return await tool.execute(**kwargs)

    def list_tools(self) -> list[dict[str, str]]:
        return [
            {"name": t.name, "description": t.description}
            for t in self._registry.values()
        ]


# 实例化标准 Travel 工具中心
travel_tools = ToolRegistry()


@travel_tools.register("search_scenic_pois", "高德真实人文/自然风景名胜检索 (白名单守门)")
def _tool_search_scenic(city: str, preferences: list[str] | None = None, **kwargs: Any):
    return search_attractions_tool(city=city, preferences=preferences or [], locked_items=kwargs.get("locked_items"))


@travel_tools.register("cluster_days_kmeans", "基于 Balanced K-Means 的空间均衡分日聚簇")
def _tool_kmeans(pois: list[dict[str, Any]], days: int, **kwargs: Any):
    return cluster_pois_tool(pois=pois, days=days)


@travel_tools.register("select_minimax_hotel", "Minimax 极小化通勤距离商圈酒店选址")
def _tool_minimax_hotel(city: str, attraction_coords: list[dict[str, Any]], **kwargs: Any):
    return search_hotel_minimax_tool(city=city, attraction_coords=attraction_coords)


@travel_tools.register("solve_2opt_route", "基于 2-Opt TSP 局部搜索的最优游览时序求解")
def _tool_2opt_route(pois: list[dict[str, Any]], **kwargs: Any):
    return solve_day_route_tool(
        pois=pois,
        immutable_names=kwargs.get("immutable_names"),
        start_hotel=kwargs.get("start_hotel"),
        start_hour=kwargs.get("start_hour", 9),
        close_hour=kwargs.get("close_hour", 20),
        day_index=kwargs.get("day_index", 0),
    )


@travel_tools.register("enrich_meals", "结合用户美食偏好周边检索高德 4.0+ 评分餐厅")
def _tool_enrich_meals(plan_days: list[dict[str, Any]], city: str, food_preferences: list[str] | None = None, **kwargs: Any):
    return enrich_meals_tool(plan_days=plan_days, city=city, food_preferences=food_preferences)


@travel_tools.register("fetch_tavily_notes", "搜索引擎仅针对最终确立的景点抓取门票与避坑事项")
def _tool_tavily_notes(city: str, poi_name: str, **kwargs: Any):
    return search_tavily_poi_guides(city=city, poi_name=poi_name)


@travel_tools.register("discover_hidden_gems", "探索城市小众特色秘境与高分美学宝藏")
def _tool_discover_gems(city: str, center_coords: tuple[float, float] | None = None, limit: int = 2, **kwargs: Any):
    return discover_hidden_gems_tool(city=city, center_coords=center_coords, limit=limit)
