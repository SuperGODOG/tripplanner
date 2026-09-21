"""Transactional, tenant-scoped persistence for travel memory."""
import json
import sqlite3
from pathlib import Path

from .manager import MemoryManager


class MemoryRepository:
    """One deep interface for user memory; callers never handle persistence."""

    def __init__(self, db_path: str | Path | None = None):
        project_root = Path(__file__).resolve().parents[3]
        self.db_path = Path(db_path or project_root / "data" / "memory.db")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def get_profile(self, user_id: str) -> tuple[int, dict]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT trip_count, entries_json FROM user_memory WHERE user_id = ?", (user_id,)
            ).fetchone()
        if row is None:
            return 0, {}
        manager = MemoryManager.from_snapshot(
            {"trip_count": row[0], "entries": json.loads(row[1])}
        )
        return manager.trip_count, manager.get_profile()

    def record_trip(self, user_id: str, observations: list[str]) -> dict:
        """Atomically merge a request's observations into exactly one user profile."""
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT trip_count, entries_json FROM user_memory WHERE user_id = ?", (user_id,)
            ).fetchone()
            snapshot = {"trip_count": row[0], "entries": json.loads(row[1])} if row else {}
            manager = MemoryManager.from_snapshot(snapshot)
            for observation in observations:
                manager.add(observation, "observe")
            manager.trip_count += 1
            data = manager.snapshot()
            connection.execute(
                """INSERT INTO user_memory (user_id, trip_count, entries_json)
                   VALUES (?, ?, ?)
                   ON CONFLICT(user_id) DO UPDATE SET
                     trip_count = excluded.trip_count,
                     entries_json = excluded.entries_json""",
                (user_id, data["trip_count"], json.dumps(data["entries"], ensure_ascii=False)),
            )
        return manager.get_profile()

    def add_footprint(self, user_id: str, poi_name: str, city: str) -> bool:
        """记录用户已游览景点足迹 (幂等更新)"""
        clean_poi = (poi_name or "").strip()
        clean_city = (city or "").strip()
        if not clean_poi or not clean_city:
            return False
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO user_footprint (user_id, poi_name, city)
                   VALUES (?, ?, ?)
                   ON CONFLICT(user_id, poi_name, city) DO UPDATE SET
                     visited_at = CURRENT_TIMESTAMP""",
                (user_id, clean_poi, clean_city),
            )
        return True

    def remove_footprint(self, user_id: str, poi_name: str, city: str) -> bool:
        """移除用户已游览景点足迹"""
        clean_poi = (poi_name or "").strip()
        clean_city = (city or "").strip()
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM user_footprint WHERE user_id = ? AND poi_name = ? AND city = ?",
                (user_id, clean_poi, clean_city),
            )
            return cursor.rowcount > 0

    def get_footprints(self, user_id: str, city: str | None = None) -> list[dict]:
        """按租户严格隔离查询用户足迹（可选城市过滤）"""
        with self._connect() as connection:
            if city:
                rows = connection.execute(
                    """SELECT id, user_id, poi_name, city, visited_at
                       FROM user_footprint
                       WHERE user_id = ? AND city = ?
                       ORDER BY visited_at DESC""",
                    (user_id, city.strip()),
                ).fetchall()
            else:
                rows = connection.execute(
                    """SELECT id, user_id, poi_name, city, visited_at
                       FROM user_footprint
                       WHERE user_id = ?
                       ORDER BY visited_at DESC""",
                    (user_id,),
                ).fetchall()
        return [
            {
                "id": r[0],
                "user_id": r[1],
                "poi_name": r[2],
                "city": r[3],
                "visited_at": str(r[4]),
            }
            for r in rows
        ]

    def is_visited(self, user_id: str, poi_name: str, city: str) -> bool:
        """检查指定景点是否已被该用户游览打卡"""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM user_footprint WHERE user_id = ? AND poi_name = ? AND city = ? LIMIT 1",
                (user_id, (poi_name or "").strip(), (city or "").strip()),
            ).fetchone()
            return row is not None

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path, timeout=30, isolation_level=None)

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS user_memory (
                    user_id TEXT PRIMARY KEY,
                    trip_count INTEGER NOT NULL,
                    entries_json TEXT NOT NULL
                )"""
            )
            connection.execute(
                """CREATE TABLE IF NOT EXISTS user_footprint (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    poi_name TEXT NOT NULL,
                    city TEXT NOT NULL,
                    visited_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(user_id, poi_name, city)
                )"""
            )
            connection.execute(
                """CREATE INDEX IF NOT EXISTS idx_footprint_user_city
                   ON user_footprint(user_id, city)"""
            )


_repository: MemoryRepository | None = None


def get_memory_repository() -> MemoryRepository:
    global _repository
    if _repository is None:
        _repository = MemoryRepository()
    return _repository
