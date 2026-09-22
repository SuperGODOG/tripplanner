import json
import sqlite3
from pathlib import Path
from typing import Any

from .manager import MemoryManager

DEFAULT_LIFESTYLE_PROFILES: dict[str, dict[str, Any]] = {
    "alice_explorer": {
        "daily_walking_limit_km": 6.0,
        "morning_person": 0,  # 松弛晚起，首站从 10:30 起步
        "travel_pace": "relaxed",  # 松弛慢游
        "companion_type": "solo",  # 独行
        "special_needs": ["avoid_crowds", "tea_breaks"],
        "aesthetic_taste": ["小众古建", "慢调茶歇", "文创书店"],
    },
    "bob_foodie": {
        "daily_walking_limit_km": 12.0,
        "morning_person": 1,  # 晨起鸟儿，08:00 开始早市探店
        "travel_pace": "intense",  # 特种兵充沛探索
        "companion_type": "family_with_kids",  # 亲子出行
        "special_needs": ["stroller_friendly", "kid_friendly"],
        "aesthetic_taste": ["老字号街巷", "夜市小吃", "市井烟火"],
    },
    "demo_traveler": {
        "daily_walking_limit_km": 8.0,
        "morning_person": 0,
        "travel_pace": "balanced",  # 均衡深度
        "companion_type": "couple",  # 伴侣双人
        "special_needs": [],
        "aesthetic_taste": ["历史名胜", "地道美食", "经典打卡"],
    },
}


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

    def get_lifestyle(self, user_id: str) -> dict[str, Any]:
        """查询用户生活方式体温画像 (支持默认租户种子自愈)"""
        with self._connect() as connection:
            row = connection.execute(
                """SELECT user_id, daily_walking_limit_km, morning_person, travel_pace,
                          companion_type, special_needs_json, aesthetic_taste_json, updated_at
                   FROM user_lifestyle
                   WHERE user_id = ?""",
                (user_id,),
            ).fetchone()

        if row is not None:
            return {
                "user_id": row[0],
                "daily_walking_limit_km": float(row[1]),
                "morning_person": bool(row[2]),
                "travel_pace": row[3],
                "companion_type": row[4],
                "special_needs": json.loads(row[5]) if row[5] else [],
                "aesthetic_taste": json.loads(row[6]) if row[6] else [],
                "updated_at": str(row[7]),
            }

        # 数据库中尚无记录：从预设模板回填种子数据
        preset = DEFAULT_LIFESTYLE_PROFILES.get(user_id) or DEFAULT_LIFESTYLE_PROFILES["demo_traveler"]
        seeded = self.update_lifestyle(user_id, preset)
        return seeded

    def update_lifestyle(self, user_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        """事务性更新用户生活方式画像 (支持差量原子合并)"""
        current = DEFAULT_LIFESTYLE_PROFILES.get(user_id, DEFAULT_LIFESTYLE_PROFILES["demo_traveler"]).copy()
        with self._connect() as connection:
            row = connection.execute(
                """SELECT daily_walking_limit_km, morning_person, travel_pace,
                          companion_type, special_needs_json, aesthetic_taste_json
                   FROM user_lifestyle WHERE user_id = ?""",
                (user_id,),
            ).fetchone()
            if row:
                current["daily_walking_limit_km"] = float(row[0])
                current["morning_person"] = int(row[1])
                current["travel_pace"] = row[2]
                current["companion_type"] = row[3]
                current["special_needs"] = json.loads(row[4]) if row[4] else []
                current["aesthetic_taste"] = json.loads(row[5]) if row[5] else []

            # 差量合并
            if "daily_walking_limit_km" in updates and updates["daily_walking_limit_km"] is not None:
                current["daily_walking_limit_km"] = float(updates["daily_walking_limit_km"])
            if "morning_person" in updates and updates["morning_person"] is not None:
                current["morning_person"] = 1 if updates["morning_person"] else 0
            if "travel_pace" in updates and updates["travel_pace"]:
                current["travel_pace"] = str(updates["travel_pace"])
            if "companion_type" in updates and updates["companion_type"]:
                current["companion_type"] = str(updates["companion_type"])
            if "special_needs" in updates and isinstance(updates["special_needs"], list):
                current["special_needs"] = list(updates["special_needs"])
            if "aesthetic_taste" in updates and isinstance(updates["aesthetic_taste"], list):
                current["aesthetic_taste"] = list(updates["aesthetic_taste"])

            connection.execute(
                """INSERT INTO user_lifestyle (
                       user_id, daily_walking_limit_km, morning_person, travel_pace,
                       companion_type, special_needs_json, aesthetic_taste_json, updated_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                   ON CONFLICT(user_id) DO UPDATE SET
                       daily_walking_limit_km = excluded.daily_walking_limit_km,
                       morning_person = excluded.morning_person,
                       travel_pace = excluded.travel_pace,
                       companion_type = excluded.companion_type,
                       special_needs_json = excluded.special_needs_json,
                       aesthetic_taste_json = excluded.aesthetic_taste_json,
                       updated_at = CURRENT_TIMESTAMP""",
                (
                    user_id,
                    current["daily_walking_limit_km"],
                    current["morning_person"],
                    current["travel_pace"],
                    current["companion_type"],
                    json.dumps(current["special_needs"], ensure_ascii=False),
                    json.dumps(current["aesthetic_taste"], ensure_ascii=False),
                ),
            )

        return {
            "user_id": user_id,
            "daily_walking_limit_km": current["daily_walking_limit_km"],
            "morning_person": bool(current["morning_person"]),
            "travel_pace": current["travel_pace"],
            "companion_type": current["companion_type"],
            "special_needs": current["special_needs"],
            "aesthetic_taste": current["aesthetic_taste"],
        }

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
            connection.execute(
                """CREATE TABLE IF NOT EXISTS user_lifestyle (
                    user_id TEXT PRIMARY KEY,
                    daily_walking_limit_km REAL NOT NULL DEFAULT 8.0,
                    morning_person INTEGER NOT NULL DEFAULT 0,
                    travel_pace TEXT NOT NULL DEFAULT 'balanced',
                    companion_type TEXT NOT NULL DEFAULT 'solo',
                    special_needs_json TEXT NOT NULL DEFAULT '[]',
                    aesthetic_taste_json TEXT NOT NULL DEFAULT '["culture", "nature"]',
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )"""
            )


_repository: MemoryRepository | None = None


def get_memory_repository() -> MemoryRepository:
    global _repository
    if _repository is None:
        _repository = MemoryRepository()
    return _repository
