"""用户与足迹管理 API (User Footprint & Profile API)

职责:
1. 提供用户游览足迹的持久化 CRUD 接口（按租户隔离）；
2. 足迹变更时主动触发租户级私有缓存失效 (Targeted Cache Invalidation)，防范缓存投毒；
3. 查询租户关联的所有活跃会话列表。
"""
from __future__ import annotations

import logging
from typing import Any
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from ..memory.repository import get_memory_repository
from ..services.cache_service import get_cache_manager
from ..harness.session_store import harness_session_store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/user", tags=["user"])


class FootprintRequest(BaseModel):
    """足迹操作载荷"""
    poi_name: str = Field(..., min_length=1, description="景点名称 (如 '故宫博物院')")
    city: str = Field(..., min_length=1, description="城市名称 (如 '北京')")


@router.get("/{user_id}/footprint")
async def get_user_footprints(user_id: str, city: str | None = Query(None)):
    """查询指定用户的游览足迹列表（按城市可选过滤）"""
    repo = get_memory_repository()
    footprints = repo.get_footprints(user_id=user_id, city=city)
    return {
        "user_id": user_id,
        "city": city,
        "total": len(footprints),
        "footprints": footprints,
    }


@router.post("/{user_id}/footprint")
async def add_user_footprint(user_id: str, payload: FootprintRequest):
    """记录用户游览打卡足迹 (幂等)

    打卡后自动清除该租户的私有规划缓存，确保后续同城生成即时生效且无缓存投毒。
    """
    repo = get_memory_repository()
    success = repo.add_footprint(user_id=user_id, poi_name=payload.poi_name, city=payload.city)
    if not success:
        raise HTTPException(status_code=400, detail="添加足迹失败，景点名或城市不能为空")

    # 精准清除该租户私有作用域缓存
    cache = get_cache_manager()
    cleared_count = cache.clear_scope(scope=f"user:{user_id}")
    logger.info("用户 [%s] 打卡 [%s - %s]，已定向清理私有缓存 %d 条", user_id, payload.city, payload.poi_name, cleared_count)

    return {
        "status": "success",
        "user_id": user_id,
        "poi_name": payload.poi_name,
        "city": payload.city,
        "message": f"已成功记录【{payload.poi_name}】至您的足迹库，后续规划将自动避开",
        "cache_invalidated": cleared_count,
    }


@router.delete("/{user_id}/footprint")
async def remove_user_footprint(user_id: str, payload: FootprintRequest):
    """移除用户游览足迹（允许重新纳入推荐规划池）"""
    repo = get_memory_repository()
    removed = repo.remove_footprint(user_id=user_id, poi_name=payload.poi_name, city=payload.city)

    # 精准清除该租户私有作用域缓存
    cache = get_cache_manager()
    cleared_count = cache.clear_scope(scope=f"user:{user_id}")

    return {
        "status": "success" if removed else "not_found",
        "user_id": user_id,
        "poi_name": payload.poi_name,
        "city": payload.city,
        "message": f"已从足迹库移除【{payload.poi_name}】" if removed else "未找到该足迹记录",
        "cache_invalidated": cleared_count,
    }


@router.get("/{user_id}/sessions")
async def get_user_sessions(user_id: str):
    """获取指定租户名下的所有活跃会话列表"""
    sessions = harness_session_store.list_user_sessions(user_id=user_id)
    return {
        "user_id": user_id,
        "sessions": sessions,
        "count": len(sessions),
    }
