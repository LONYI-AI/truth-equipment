"""Fake HA Server（M1A simulation）——确定性的本地 HA-like 只读端点。

- 127.0.0.1 + ephemeral port（无公网访问、无真实 HA 依赖、无 Docker 要求）。
- stdlib `http.server`（无新增 runtime dependency、无 token）。
- fixture 可被测试精确控制（`set_states` / `set_state`）。
"""

from __future__ import annotations

import json
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from physical_agent.runtime.nodes.perceive import PerceptionSnapshot, WorldStateSource

# 确定性默认 fixture（ROADMAP M1A-01）
DEFAULT_STATES: dict[str, dict[str, Any]] = {
    "climate.bedroom_ac": {
        "state": "off",
        "attributes": {"temperature": 28, "target_temperature": 26, "mode": "cool"},
    },
    "environment": {
        "room_temperature": 28,
        "occupancy": "occupied",
    },
}


class FakeHAServer:
    """本地只读 HA-like HTTP server（/api/states 返回 fixture JSON）。"""

    def __init__(self, states: dict[str, dict[str, Any]] | None = None) -> None:
        self._states: dict[str, dict[str, Any]] = dict(states if states is not None else DEFAULT_STATES)
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def base_url(self) -> str:
        if self._httpd is None:
            raise RuntimeError("FakeHAServer not started")
        host, port = self._httpd.server_address[:2]
        return f"http://{host}:{port}"

    def set_states(self, states: dict[str, dict[str, Any]]) -> None:
        self._states = dict(states)

    def set_state(self, entity_id: str, state: dict[str, Any]) -> None:
        self._states[entity_id] = dict(state)

    def start(self) -> FakeHAServer:
        outer = self

        class _Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802 (http.server API)
                if self.path == "/api/states":
                    body = json.dumps(outer._states, ensure_ascii=False).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                else:
                    self.send_response(404)
                    self.end_headers()

            def log_message(self, *args: Any) -> None:  # noqa: ARG002 - silence
                pass

        # 127.0.0.1 + port 0 => ephemeral port（仅 loopback）
        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None

    def __enter__(self) -> FakeHAServer:
        return self.start()

    def __exit__(self, *exc: Any) -> None:
        self.stop()


class FakeHASource(WorldStateSource):
    """实现 WorldStateSource，从 Fake HA HTTP 端点读取 snapshot（stdlib urllib）。"""

    def __init__(self, base_url: str) -> None:
        self._base_url = base_url

    def read_snapshot(self) -> PerceptionSnapshot:
        with urllib.request.urlopen(f"{self._base_url}/api/states", timeout=3) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        devices = {k: v for k, v in data.items() if k != "environment"}
        environment = data.get("environment", {})
        return PerceptionSnapshot(devices=devices, environment=environment)
