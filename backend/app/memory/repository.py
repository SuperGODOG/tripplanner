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


_repository: MemoryRepository | None = None


def get_memory_repository() -> MemoryRepository:
    global _repository
    if _repository is None:
        _repository = MemoryRepository()
    return _repository
