"""DeepSeek Harness 真实 SDK smoke test（P0-1 强化）。

关键约束（不允许 "SDK 没装但 Harness conformance PASS"）：
- 支持平台（Linux x64/arm64、macOS 14+ arm64）上 SDK 必须真实导入、真实实例化官方
  `deepseek_harness.DeepSeekHarness`、加载真实 Cordis composition，并对本地 fake/model
  proxy 跑一次真实 run()。
- 不支持平台（Windows 等）→ 明确 skip。
- 支持平台但 SDK 未安装 → FAIL（而非 skip）。

本测试不消耗真实 DeepSeek API：DEEPSEEK_BASE_URL 指向本地 fake OpenAI-compatible proxy。
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from physical_agent.runtime.deepseek_harness import (
    DSH_SDK_VERSION,
    _platform_supported,
    _sdk_available,
    physical_cordis_path,
)

# ---- 本地 fake OpenAI-compatible model proxy ----


def _chat_completion(model: str, content: str) -> dict:
    return {
        "id": "chatcmpl-fake",
        "object": "chat.completion",
        "created": 0,
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }


def _responses(model: str, content: str) -> dict:
    return {
        "id": "resp-fake",
        "object": "response",
        "model": model,
        "output": [
            {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": content}],
            }
        ],
        "status": "completed",
    }


class _ModelProxy:
    """本地 fake model proxy：真实 SDK 可指向它（DEEPSEEK_BASE_URL），不消耗真实 API。"""

    def __init__(self, model: str) -> None:
        self.model = model
        self.hits = 0
        self.requests: list[dict] = []
        self._lock = threading.Lock()
        proxy = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "FakeModelProxy/1.0"

            def log_message(self, *args: object) -> None:  # noqa: D401 - 静默日志
                return

            def _send_json(self, code: int, obj: dict) -> None:
                body = json.dumps(obj).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _record(self, body: dict) -> None:
                with proxy._lock:
                    proxy.hits += 1
                    proxy.requests.append(body)

            def do_GET(self) -> None:  # noqa: N802
                if self.path.rstrip("/").endswith("models"):
                    self._send_json(
                        200, {"object": "list", "data": [{"id": proxy.model, "object": "model"}]}
                    )
                else:
                    self._send_json(404, {"error": "not found"})

            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(length) if length else b"{}"
                try:
                    body = json.loads(raw.decode("utf-8"))
                except Exception:
                    body = {}
                self._record(body)
                if "responses" in self.path:
                    self._respond_responses(body)
                else:
                    self._respond_chat(body)

            def _respond_chat(self, body: dict) -> None:
                if body.get("stream"):
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.send_header("Cache-Control", "no-cache")
                    self.end_headers()
                    delta = {
                        "choices": [
                            {
                                "index": 0,
                                "delta": {"role": "assistant", "content": "OK"},
                                "finish_reason": None,
                            }
                        ]
                    }
                    stop = {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}
                    self.wfile.write(f"data: {json.dumps(delta)}\n\n".encode())
                    self.wfile.write(f"data: {json.dumps(stop)}\n\n".encode())
                    self.wfile.write(b"data: [DONE]\n\n")
                    self.wfile.flush()
                else:
                    self._send_json(200, _chat_completion(proxy.model, "OK"))

            def _respond_responses(self, body: dict) -> None:
                if body.get("stream"):
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.end_headers()
                    evt = {"type": "response.output_text.delta", "delta": "OK"}
                    self.wfile.write(f"data: {json.dumps(evt)}\n\n".encode())
                    self.wfile.write(b"data: [DONE]\n\n")
                    self.wfile.flush()
                else:
                    self._send_json(200, _responses(proxy.model, "OK"))

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self._server.server_address[1]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}/v1"

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()


def _require_sdk() -> None:
    if not _platform_supported():
        pytest.skip("DeepSeek Harness SDK runtime binaries unsupported on this platform")
    if not _sdk_available():
        pytest.fail(
            f"deepseek-harness-sdk=={DSH_SDK_VERSION} must be installed on a supported platform "
            "(CI: pip install -e '.[dev,harness]'); refusing a false conformance PASS"
        )


@pytest.mark.harness_smoke
def test_official_deepseek_harness_smoke(gateway, tmp_path: Path, monkeypatch) -> None:
    """真正实例化官方 DeepSeekHarness + 加载真实 Cordis composition + 对本地 proxy 跑一次 run()。"""
    _require_sdk()

    from deepseek_harness import DeepSeekHarness  # 官方 SDK（仅支持平台可导入）

    from physical_agent.runtime.deepseek_harness import DeepSeekHarnessRuntime

    workspace = tmp_path / "workspace"
    sessions = tmp_path / "sessions"
    workspace.mkdir()
    sessions.mkdir()

    proxy = _ModelProxy("deepseek-v4-flash")
    try:
        monkeypatch.setenv("DEEPSEEK_BASE_URL", proxy.base_url)
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-fake-smoke-key")
        monkeypatch.setenv("DSH_MODEL", "deepseek-v4-flash")
        monkeypatch.setenv("DSH_SESSION_ROOT", str(sessions))
        monkeypatch.setenv("DSH_CWD", str(workspace))
        monkeypatch.setenv("DSH_SNAPSHOT", "none")

        cordis = physical_cordis_path()
        assert cordis.exists(), f"physical Cordis composition missing: {cordis}"

        rt = DeepSeekHarnessRuntime(
            gateway,
            provider="deepseek-official",
            model="deepseek-v4-flash",
            max_tokens=256,
            workspace=workspace,
            session_dir=sessions,
            cordis=cordis,
        )
        harness = rt.build_harness()
        assert isinstance(harness, DeepSeekHarness), "runtime did not build the official DeepSeekHarness"

        with harness:
            result = harness.run("Reply with exactly the word: OK", session_id="smoke-001")

        # 真实实例化 + 真实调用证据（硬断言）
        assert getattr(result, "session_id", None) == "smoke-001"
        assert proxy.hits >= 1, "fake model proxy was never called — harness did not reach the model endpoint"

        # 软证据（打印，便于 CI 诊断；不因响应格式微差而脆断）
        print(f"[smoke] final_response={getattr(result, 'final_response', None)!r}")
        print(f"[smoke] finish_reason={getattr(result, 'finish_reason', None)!r}")
    finally:
        proxy.stop()
