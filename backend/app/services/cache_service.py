"""细粒度工具依赖指纹缓存管理器 (Fingerprint Cache Service)

实现基于输入参数哈希的细粒度缓存（非全量 Prompt/Session 粗粒度缓存）。
支持 Redis 分布式存储与内存线程安全 LRU 引擎自动降级，环境零破坏。
"""
from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from typing import Any
import redis
from pydantic import BaseModel

logger = logging.getLogger(__name__)


def compute_fingerprint(params: Any) -> str:
    """递归归一化参数并计算唯一的 MD5 依赖指纹

    保证字典键顺序无关、Pydantic 模型自适应序列化。
    """
    def _normalize(obj: Any) -> Any:
        if isinstance(obj, BaseModel):
            return _normalize(obj.model_dump())
        if isinstance(obj, dict):
            return {str(k): _normalize(v) for k, v in sorted(obj.items())}
        if isinstance(obj, (list, tuple, set)):
            return [_normalize(x) for x in obj]
        if isinstance(obj, float):
            return round(obj, 6)
        return obj

    normalized = _normalize(params)
    serialized = json.dumps(normalized, sort_keys=True, ensure_ascii=False)
    return hashlib.md5(serialized.encode("utf-8")).hexdigest()


class _MemoryCache:
    """线程安全、带 TTL 的内存缓存降级引擎"""

    def __init__(self, max_size: int = 2000):
        self._store: dict[str, tuple[str, float]] = {}  # key -> (json_val, expire_at)
        self._lock = threading.Lock()
        self._max_size = max_size

    def get(self, key: str) -> Any | None:
        now = time.time()
        with self._lock:
            item = self._store.get(key)
            if item is None:
                return None
            val_str, expire_at = item
            if expire_at > 0 and now > expire_at:
                del self._store[key]
                return None
            try:
                return json.loads(val_str)
            except Exception:
                return val_str

    def set(self, key: str, value: Any, ttl: int = 86400) -> bool:
        now = time.time()
        expire_at = (now + ttl) if ttl > 0 else 0.0
        if isinstance(value, BaseModel):
            val_str = value.model_dump_json()
        elif not isinstance(value, str):
            val_str = json.dumps(value, ensure_ascii=False)
        else:
            val_str = value
        with self._lock:
            if len(self._store) >= self._max_size:
                # 简单淘汰过期项或首项
                self._prune(now)
            self._store[key] = (val_str, expire_at)
        return True

    def delete(self, key: str) -> bool:
        with self._lock:
            return self._store.pop(key, None) is not None

    def clear_scope(self, scope_pattern: str) -> int:
        count = 0
        with self._lock:
            keys_to_delete = [k for k in self._store if scope_pattern in k]
            for k in keys_to_delete:
                del self._store[k]
                count += 1
        return count

    def _prune(self, now: float) -> None:
        expired = [k for k, (_, exp) in self._store.items() if exp > 0 and now > exp]
        for k in expired:
            del self._store[k]
        if len(self._store) >= self._max_size and self._store:
            # 删掉最旧的一项
            first_key = next(iter(self._store))
            del self._store[first_key]


class FingerprintCacheManager:
    """细粒度依赖指纹缓存管理器

    优先连接 Redis 分布式缓存；若 Redis 连接超时或不可达，
    透明自动降级为 _MemoryCache 内存缓存，确保本地与测试 100% 畅通。
    """

    def __init__(
        self,
        host: str = "localhost",
        port: int = 6379,
        password: str = "",
        db: int = 0,
        enabled: bool = True,
    ):
        self.enabled = enabled
        self._memory = _MemoryCache()
        self._redis: redis.Redis | None = None
        self.is_redis_active = False

        if self.enabled:
            try:
                client = redis.Redis(
                    host=host,
                    port=port,
                    password=password or None,
                    db=db,
                    socket_connect_timeout=0.2,
                    socket_timeout=0.5,
                    decode_responses=True,
                )
                if client.ping():
                    self._redis = client
                    self.is_redis_active = True
                    logger.info("Redis 依赖指纹缓存连接成功 (%s:%s)", host, port)
            except Exception as e:
                self.is_redis_active = False
                logger.warning("Redis 连接不可达 (%s)，自动降级为本地内存 LRU 缓存", e)

    def make_key(self, tool_name: str, fingerprint: str, scope: str = "public") -> str:
        """组装标准化缓存键名"""
        return f"tripplanner:tool:{tool_name}:{scope}:{fingerprint}"

    def get(self, tool_name: str, fingerprint: str, scope: str = "public") -> Any | None:
        """根据工具名和参数指纹读取缓存"""
        if not self.enabled:
            return None

        key = self.make_key(tool_name, fingerprint, scope)

        # 1. 尝试 Redis
        if self.is_redis_active and self._redis is not None:
            try:
                raw = self._redis.get(key)
                if raw is not None:
                    return json.loads(raw)
            except Exception as e:
                logger.warning("Redis get 失败，降级查内存: %s", e)

        # 2. 降级查内存
        return self._memory.get(key)

    def set(
        self,
        tool_name: str,
        fingerprint: str,
        value: Any,
        ttl: int = 86400,
        scope: str = "public",
    ) -> bool:
        """写入工具指纹缓存"""
        if not self.enabled:
            return False

        key = self.make_key(tool_name, fingerprint, scope)
        if isinstance(value, BaseModel):
            json_str = value.model_dump_json()
        elif not isinstance(value, str):
            json_str = json.dumps(value, ensure_ascii=False)
        else:
            json_str = value

        # 1. 尝试写入 Redis
        if self.is_redis_active and self._redis is not None:
            try:
                self._redis.set(key, json_str, ex=ttl)
            except Exception as e:
                logger.warning("Redis set 失败: %s", e)

        # 2. 同步写入内存备选
        self._memory.set(key, value, ttl=ttl)
        return True

    def delete(self, tool_name: str, fingerprint: str, scope: str = "public") -> bool:
        """删除指定指纹缓存"""
        key = self.make_key(tool_name, fingerprint, scope)
        success = False
        if self.is_redis_active and self._redis is not None:
            try:
                success = bool(self._redis.delete(key))
            except Exception:
                pass
        mem_success = self._memory.delete(key)
        return success or mem_success

    def clear_scope(self, scope: str = "public") -> int:
        """清理特定作用域（如特定租户）下的全部工具缓存"""
        pattern = f"tripplanner:tool:*:{scope}:*"
        count = 0
        if self.is_redis_active and self._redis is not None:
            try:
                keys = self._redis.keys(pattern)
                if keys:
                    count = self._redis.delete(*keys)
            except Exception:
                pass
        mem_count = self._memory.clear_scope(f":{scope}:")
        return max(count, mem_count)


_cache_manager: FingerprintCacheManager | None = None


def get_cache_manager() -> FingerprintCacheManager:
    """获取缓存管理器单例"""
    global _cache_manager
    if _cache_manager is None:
        try:
            from ..config import get_settings
            settings = get_settings()
            _cache_manager = FingerprintCacheManager(
                host=settings.redis_host,
                port=settings.redis_port,
                password=settings.redis_password,
                db=settings.redis_db,
                enabled=settings.redis_enabled,
            )
        except Exception as e:
            logger.debug("获取全局 settings 失败 (%s)，使用默认配置初始化缓存管理器", e)
            _cache_manager = FingerprintCacheManager()
    return _cache_manager
