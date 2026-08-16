"""MemoryStore：结构化记忆（v3.0 §28）。

M1 实现：Working Memory → Agent State；Event Memory / Preferences / Device History → SQLite。
Qdrant 为 planned adapter（SemanticMemory），M1 不部署。
"""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any, Protocol


class MemoryStore(Protocol):
    def append_event(self, event: dict[str, Any]) -> str: ...
    def query_events(self, *, session_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]: ...
    def get_preference(self, key: str) -> Any: ...
    def set_preference(self, key: str, value: Any) -> None: ...
    def record_device_state(self, device_id: str, state: Any) -> None: ...


class SqliteMemoryStore:
    """SQLite 实现：事件流水 + 结构化偏好 + 设备历史。"""

    def __init__(self, path: Path | str = ":memory:") -> None:
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._lock = threading.Lock()
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS events ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "session_id TEXT, correlation_id TEXT, event_type TEXT,"
            "payload TEXT, created_at TEXT DEFAULT (datetime('now')))"
        )
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS preferences ("
            "key TEXT PRIMARY KEY, value TEXT)"
        )
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS device_history ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "device_id TEXT, state TEXT, created_at TEXT DEFAULT (datetime('now')))"
        )
        self._conn.commit()

    def append_event(self, event: dict[str, Any]) -> str:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO events (session_id, correlation_id, event_type, payload) VALUES (?,?,?,?)",
                (
                    event.get("session_id"),
                    event.get("correlation_id"),
                    event.get("event_type"),
                    json.dumps(event.get("payload", {}), ensure_ascii=False),
                ),
            )
            self._conn.commit()
            return str(cur.lastrowid)

    def query_events(self, *, session_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock:
            if session_id is None:
                rows = self._conn.execute(
                    "SELECT session_id, correlation_id, event_type, payload, created_at "
                    "FROM events ORDER BY id DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT session_id, correlation_id, event_type, payload, created_at "
                    "FROM events WHERE session_id = ? ORDER BY id DESC LIMIT ?",
                    (session_id, limit),
                ).fetchall()
        return [
            {
                "session_id": r[0],
                "correlation_id": r[1],
                "event_type": r[2],
                "payload": json.loads(r[3]),
                "created_at": r[4],
            }
            for r in rows
        ]

    def get_preference(self, key: str) -> Any:
        with self._lock:
            row = self._conn.execute(
                "SELECT value FROM preferences WHERE key = ?", (key,)
            ).fetchone()
        if row is None:
            return None
        return json.loads(row[0])

    def set_preference(self, key: str, value: Any) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO preferences (key, value) VALUES (?,?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, json.dumps(value, ensure_ascii=False)),
            )
            self._conn.commit()

    def record_device_state(self, device_id: str, state: Any) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO device_history (device_id, state) VALUES (?,?)",
                (device_id, json.dumps(state, ensure_ascii=False)),
            )
            self._conn.commit()
