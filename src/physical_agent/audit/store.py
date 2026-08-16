"""Tamper-evident 持久审计存储（v3.0 §30/§31 + M0.1 P0-5）。

完整性机制：
- canonical JSON 序列化（字段顺序固定、UTF-8）
- SHA-256 链式哈希：hash_i = SHA256(hash_{i-1} ‖ canonical(event_i))
- 启动时 load_and_verify()：解析 JSONL → 校验哈希链 → 恢复 last_hash
- checkpoint 持久化（HMAC 签名）

语义：**tamper-evident（可检测篡改）**，不是"不可篡改"。
禁止使用 Python built-in hash()。
"""

from __future__ import annotations

import hashlib
import hmac
import json
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

GENESIS = "GENESIS"


class ChainIntegrityError(Exception):
    """哈希链断裂（检测到篡改）。"""


class AuditEvent:
    """一条审计事件。"""

    def __init__(self, event_type: str, correlation_id: str, data: dict[str, Any] | None = None) -> None:
        self.event_type = event_type
        self.correlation_id = correlation_id
        self.data = data or {}
        self.timestamp = datetime.now(UTC).isoformat()
        self.prev_hash = ""
        self.hash = ""

    def canonical(self) -> str:
        obj = {
            "event_type": self.event_type,
            "correlation_id": self.correlation_id,
            "data": self.data,
            "timestamp": self.timestamp,
        }
        return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_type": self.event_type,
            "correlation_id": self.correlation_id,
            "data": self.data,
            "timestamp": self.timestamp,
            "prev_hash": self.prev_hash,
            "hash": self.hash,
        }


class AuditStore:
    """append-only + SHA-256 链式哈希的持久审计存储（P0-5）。"""

    def __init__(
        self,
        path: Path | None = None,
        signing_key: bytes | None = None,
        checkpoint_path: Path | None = None,
        auto_load: bool = True,
    ) -> None:
        self._path = path
        self._signing_key = signing_key
        self._checkpoint_path = checkpoint_path
        self._events: list[AuditEvent] = []
        self._lock = threading.Lock()
        self._last_hash = GENESIS
        self._loaded = False
        self._healthy = True
        if auto_load and path is not None and path.exists():
            try:
                self.load_and_verify()
            except ChainIntegrityError:
                # 损坏：标记 unhealthy（fail-closed），不崩溃启动
                self._healthy = False

    @staticmethod
    def _sha256(data: str) -> str:
        return hashlib.sha256(data.encode("utf-8")).hexdigest()

    # ---- 持久化 / 加载（P0-5）----

    def load_and_verify(self) -> None:
        """从 JSONL 加载并校验哈希链，恢复 last_hash。损坏即抛 ChainIntegrityError。"""
        if self._path is None or not self._path.exists():
            self._loaded = True
            self._healthy = True
            return

        events: list[AuditEvent] = []
        prev = GENESIS
        with self._path.open("r", encoding="utf-8") as f:
            for lineno, line in enumerate(f, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError as exc:
                    self._healthy = False
                    raise ChainIntegrityError(f"corrupt JSON at line {lineno}: {exc}") from exc

                ev = AuditEvent(obj["event_type"], obj["correlation_id"], obj.get("data", {}))
                ev.timestamp = obj.get("timestamp", ev.timestamp)
                ev.prev_hash = obj.get("prev_hash", "")
                ev.hash = obj.get("hash", "")

                expected = self._sha256(prev + ev.canonical())
                if ev.hash != expected or ev.prev_hash != prev:
                    self._healthy = False
                    raise ChainIntegrityError(
                        f"chain broken at line {lineno} ({ev.event_type}): "
                        f"expected {expected[:12]}, got {ev.hash[:12]}"
                    )
                prev = ev.hash
                events.append(ev)

        with self._lock:
            self._events = events
            self._last_hash = prev
            self._loaded = True
            self._healthy = True

    def verify_file(self) -> None:
        """校验磁盘文件（不改变内存状态）。"""
        if self._path is None or not self._path.exists():
            return
        prev = GENESIS
        with self._path.open("r", encoding="utf-8") as f:
            for lineno, line in enumerate(f, start=1):
                line = line.strip()
                if not line:
                    continue
                obj = json.loads(line)
                ev = AuditEvent(obj["event_type"], obj["correlation_id"], obj.get("data", {}))
                ev.timestamp = obj.get("timestamp", ev.timestamp)
                ev.prev_hash = obj.get("prev_hash", "")
                ev.hash = obj.get("hash", "")
                expected = self._sha256(prev + ev.canonical())
                if ev.hash != expected or ev.prev_hash != prev:
                    raise ChainIntegrityError(f"chain broken at line {lineno}")
                prev = ev.hash

    @property
    def is_healthy(self) -> bool:
        return self._healthy

    @property
    def loaded(self) -> bool:
        return self._loaded

    # ---- append / checkpoint ----

    def append(self, event_type: str, correlation_id: str, data: dict[str, Any] | None = None) -> AuditEvent:
        event = AuditEvent(event_type, correlation_id, data)
        with self._lock:
            event.prev_hash = self._last_hash
            event.hash = self._sha256(self._last_hash + event.canonical())
            self._last_hash = event.hash
            self._events.append(event)
            self._flush(event)
        return event

    def _flush(self, event: AuditEvent) -> None:
        if self._path is None:
            return
        with self._path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event.to_dict(), ensure_ascii=False) + "\n")

    def checkpoint(self, persist: bool = True) -> str:
        """生成签名 checkpoint（HMAC）。无 signing_key 时返回链尾哈希。"""
        with self._lock:
            digest = self._last_hash
        if self._signing_key is None:
            cp = digest
        else:
            cp = hmac.new(self._signing_key, digest.encode(), hashlib.sha256).hexdigest()
        if persist and self._checkpoint_path is not None:
            self._checkpoint_path.write_text(
                json.dumps({"last_hash": digest, "checkpoint": cp}), encoding="utf-8"
            )
        return cp

    @property
    def last_hash(self) -> str:
        with self._lock:
            return self._last_hash

    def events(self) -> list[AuditEvent]:
        with self._lock:
            return list(self._events)

    def verify_chain(self) -> None:
        """校验内存中的整条链；断裂时抛 ChainIntegrityError。"""
        with self._lock:
            prev = GENESIS
            for event in self._events:
                expected = self._sha256(prev + event.canonical())
                if event.hash != expected:
                    raise ChainIntegrityError(
                        f"chain broken at {event.event_type}/{event.correlation_id}"
                    )
                prev = event.hash
