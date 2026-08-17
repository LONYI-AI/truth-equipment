"""Home Assistant transport client 单元测试（M1B）。

覆盖：URL normalization、Authorization header、/api/、state read、service call、
HTTP errors、timeout、401、malformed response、WebSocket 握手/鉴权/订阅。
安全约束：token / Authorization header / service payload 绝不出现在异常消息中。
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from physical_agent.adapters import ha_client
from physical_agent.adapters.ha_client import (
    HomeAssistantAuthError,
    HomeAssistantClient,
    HomeAssistantError,
)


class _FakeResponse:
    def __init__(self, payload: Any, *, status_code: int = 200, bad_json: bool = False) -> None:
        self._payload = payload
        self.status_code = status_code
        self._bad_json = bad_json

    def raise_for_status(self) -> None:
        if self.status_code < 400:
            return
        request = ha_client.httpx.Request("GET", "http://localhost:8123/api/")
        response = ha_client.httpx.Response(self.status_code, request=request)
        raise ha_client.httpx.HTTPStatusError(f"HTTP {self.status_code}", request=request, response=response)

    def json(self) -> Any:
        if self._bad_json:
            raise ValueError("not json")
        return self._payload


class _FakeHttpClient:
    def __init__(
        self,
        captured: dict[str, Any],
        payload: Any,
        *,
        status_code: int = 200,
        raise_exc: Exception | None = None,
        bad_json: bool = False,
        **kwargs: Any,
    ) -> None:
        captured["client_kwargs"] = kwargs
        self._captured = captured
        self._payload = payload
        self._status_code = status_code
        self._raise_exc = raise_exc
        self._bad_json = bad_json

    async def __aenter__(self) -> _FakeHttpClient:
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        return None

    async def request(self, method: str, path: str, *, json: dict[str, Any] | None = None) -> _FakeResponse:
        self._captured["request"] = {"method": method, "path": path, "json": json}
        if self._raise_exc is not None:
            raise self._raise_exc
        return _FakeResponse(
            self._payload,
            status_code=self._status_code,
            bad_json=self._bad_json,
        )


def _install_fake_async_client(
    monkeypatch: Any,
    captured: dict[str, Any],
    *,
    payload: Any = None,
    status_code: int = 200,
    raise_exc: Exception | None = None,
    bad_json: bool = False,
) -> None:
    def fake_async_client(**kw: Any) -> _FakeHttpClient:
        return _FakeHttpClient(
            captured,
            payload,
            status_code=status_code,
            raise_exc=raise_exc,
            bad_json=bad_json,
            **kw,
        )

    monkeypatch.setattr(ha_client.httpx, "AsyncClient", fake_async_client)


# ---- URL normalization ----


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("http://localhost:8123", "http://localhost:8123"),
        ("http://localhost:8123/", "http://localhost:8123"),
        ("http://localhost:8123///", "http://localhost:8123"),
        ("http://localhost:8123/api", "http://localhost:8123"),
        ("http://localhost:8123/api/", "http://localhost:8123"),
        ("  http://localhost:8123  ", "http://localhost:8123"),
    ],
)
def test_normalize_base_url(raw: str, expected: str) -> None:
    assert HomeAssistantClient.normalize_base_url(raw) == expected


def test_normalize_base_url_rejects_empty() -> None:
    with pytest.raises(ValueError):
        HomeAssistantClient.normalize_base_url("")
    with pytest.raises(ValueError):
        HomeAssistantClient.normalize_base_url("   ")
    with pytest.raises(ValueError):
        HomeAssistantClient.normalize_base_url("/api/")


def test_empty_token_rejected() -> None:
    with pytest.raises(ValueError):
        HomeAssistantClient("http://localhost:8123", "")


def test_websocket_url_derivation() -> None:
    client = HomeAssistantClient("https://ha.example.com:8123", "tok")
    assert client.websocket_url == "wss://ha.example.com:8123/api/websocket"
    client_http = HomeAssistantClient("http://localhost:8123", "tok")
    assert client_http.websocket_url == "ws://localhost:8123/api/websocket"


# ---- Authorization header / REST ----


async def test_rest_sends_bearer_header_and_disables_proxy(monkeypatch: Any) -> None:
    captured: dict[str, Any] = {}
    _install_fake_async_client(monkeypatch, captured, payload={"message": "API running."})

    client = HomeAssistantClient("http://localhost:8123", "test-token")
    result = await client.api_status()

    assert result == {"message": "API running."}
    kwargs = captured["client_kwargs"]
    assert kwargs["trust_env"] is False
    assert kwargs["base_url"] == "http://localhost:8123"
    assert kwargs["headers"]["Authorization"] == "Bearer test-token"
    assert kwargs["headers"]["Content-Type"] == "application/json"
    assert captured["request"] == {"method": "GET", "path": "/api/", "json": None}


async def test_list_states_roundtrip(monkeypatch: Any) -> None:
    captured: dict[str, Any] = {}
    payload = [{"entity_id": "light.demo", "state": "off"}]
    _install_fake_async_client(monkeypatch, captured, payload=payload)

    client = HomeAssistantClient("http://localhost:8123", "tok")
    assert await client.list_states() == payload
    assert captured["request"]["path"] == "/api/states"


async def test_get_state_roundtrip(monkeypatch: Any) -> None:
    captured: dict[str, Any] = {}
    payload = {"entity_id": "light.demo", "state": "on"}
    _install_fake_async_client(monkeypatch, captured, payload=payload)

    client = HomeAssistantClient("http://localhost:8123", "tok")
    assert await client.get_state("light.demo") == payload
    assert captured["request"]["path"] == "/api/states/light.demo"


async def test_call_service_roundtrip(monkeypatch: Any) -> None:
    captured: dict[str, Any] = {}
    payload = [{"entity_id": "light.demo", "state": "on"}]
    _install_fake_async_client(monkeypatch, captured, payload=payload)

    client = HomeAssistantClient("http://localhost:8123", "tok")
    result = await client.call_service("light", "turn_on", {"entity_id": "light.demo"})
    assert result == payload
    assert captured["request"] == {
        "method": "POST",
        "path": "/api/services/light/turn_on",
        "json": {"entity_id": "light.demo"},
    }


# ---- error mapping ----


async def test_401_maps_to_auth_error(monkeypatch: Any) -> None:
    captured: dict[str, Any] = {}
    _install_fake_async_client(monkeypatch, captured, payload={"message": "Unauthorized"}, status_code=401)
    client = HomeAssistantClient("http://localhost:8123", "secret-token")
    with pytest.raises(HomeAssistantAuthError):
        await client.api_status()


async def test_403_maps_to_auth_error(monkeypatch: Any) -> None:
    captured: dict[str, Any] = {}
    _install_fake_async_client(monkeypatch, captured, payload={}, status_code=403)
    client = HomeAssistantClient("http://localhost:8123", "tok")
    with pytest.raises(HomeAssistantAuthError):
        await client.api_status()


async def test_500_maps_to_generic_error(monkeypatch: Any) -> None:
    captured: dict[str, Any] = {}
    _install_fake_async_client(monkeypatch, captured, payload={}, status_code=500)
    client = HomeAssistantClient("http://localhost:8123", "tok")
    with pytest.raises(HomeAssistantError) as excinfo:
        await client.api_status()
    assert "500" in str(excinfo.value)


async def test_timeout_maps_to_generic_error(monkeypatch: Any) -> None:
    captured: dict[str, Any] = {}
    _install_fake_async_client(
        monkeypatch,
        captured,
        payload={},
        raise_exc=ha_client.httpx.TimeoutException("timed out"),
    )
    client = HomeAssistantClient("http://localhost:8123", "tok")
    with pytest.raises(HomeAssistantError):
        await client.api_status()


async def test_connect_error_maps_to_generic_error(monkeypatch: Any) -> None:
    captured: dict[str, Any] = {}
    _install_fake_async_client(
        monkeypatch,
        captured,
        payload={},
        raise_exc=ha_client.httpx.ConnectError("refused"),
    )
    client = HomeAssistantClient("http://localhost:8123", "tok")
    with pytest.raises(HomeAssistantError):
        await client.api_status()


async def test_invalid_json_maps_to_generic_error(monkeypatch: Any) -> None:
    captured: dict[str, Any] = {}
    _install_fake_async_client(monkeypatch, captured, payload="<html>", bad_json=True)
    client = HomeAssistantClient("http://localhost:8123", "tok")
    with pytest.raises(HomeAssistantError, match="invalid JSON"):
        await client.api_status()


async def test_malformed_list_states_rejected(monkeypatch: Any) -> None:
    captured: dict[str, Any] = {}
    _install_fake_async_client(monkeypatch, captured, payload={"not": "a list"})
    client = HomeAssistantClient("http://localhost:8123", "tok")
    with pytest.raises(HomeAssistantError, match="unexpected /api/states"):
        await client.list_states()


async def test_malformed_get_state_rejected(monkeypatch: Any) -> None:
    captured: dict[str, Any] = {}
    _install_fake_async_client(monkeypatch, captured, payload=["not", "a", "dict"])
    client = HomeAssistantClient("http://localhost:8123", "tok")
    with pytest.raises(HomeAssistantError, match="unexpected entity state"):
        await client.get_state("light.demo")


async def test_malformed_service_response_rejected(monkeypatch: Any) -> None:
    captured: dict[str, Any] = {}
    _install_fake_async_client(monkeypatch, captured, payload={"not": "a list"})
    client = HomeAssistantClient("http://localhost:8123", "tok")
    with pytest.raises(HomeAssistantError, match="unexpected service"):
        await client.call_service("light", "turn_on", {"entity_id": "light.demo"})


async def test_secret_never_appears_in_error_message(monkeypatch: Any) -> None:
    captured: dict[str, Any] = {}
    _install_fake_async_client(monkeypatch, captured, payload={}, status_code=401)
    client = HomeAssistantClient("http://localhost:8123", "super-secret-token")
    with pytest.raises(HomeAssistantAuthError) as excinfo:
        await client.api_status()
    assert "super-secret-token" not in str(excinfo.value)
    assert "Bearer" not in str(excinfo.value)


# ---- WebSocket ----


class _FakeWebSocket:
    def __init__(self, messages: list[str]) -> None:
        self.sent: list[dict[str, Any]] = []
        self._messages = iter(messages)

    async def recv(self) -> str:
        return next(self._messages)

    async def send(self, raw: str) -> None:
        self.sent.append(json.loads(raw))


class _FakeWebSocketContext:
    def __init__(self, websocket: _FakeWebSocket) -> None:
        self.websocket = websocket

    async def __aenter__(self) -> _FakeWebSocket:
        return self.websocket

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        return None


def _ok_websocket_messages() -> list[str]:
    return [
        json.dumps({"type": "auth_required"}),
        json.dumps({"type": "auth_ok"}),
        json.dumps({"id": 1, "type": "result", "success": True}),
        json.dumps(
            {
                "id": 1,
                "type": "event",
                "event": {
                    "data": {
                        "entity_id": "light.demo",
                        "old_state": {"state": "off"},
                        "new_state": {"state": "on"},
                    }
                },
            }
        ),
    ]


def _install_fake_connect(monkeypatch: Any, captured: dict[str, Any], websocket: _FakeWebSocket) -> None:
    def fake_connect(uri: str, **kwargs: Any) -> _FakeWebSocketContext:
        captured["uri"] = uri
        captured["connect_kwargs"] = kwargs
        return _FakeWebSocketContext(websocket)

    monkeypatch.setattr(ha_client, "connect", fake_connect)


async def test_websocket_handshake_and_subscribe(monkeypatch: Any) -> None:
    captured: dict[str, Any] = {}
    websocket = _FakeWebSocket(_ok_websocket_messages())
    _install_fake_connect(monkeypatch, captured, websocket)

    client = HomeAssistantClient("http://localhost:8123", "test-token")
    stream = client.state_changes({"light.demo"})
    try:
        event = await anext(stream)
    finally:
        await stream.aclose()

    assert captured["uri"] == "ws://localhost:8123/api/websocket"
    assert captured["connect_kwargs"]["proxy"] is None
    assert websocket.sent[0] == {"type": "auth", "access_token": "test-token"}
    assert websocket.sent[1] == {
        "id": 1,
        "type": "subscribe_events",
        "event_type": "state_changed",
    }
    assert event["entity_id"] == "light.demo"
    assert event["old_state"]["state"] == "off"
    assert event["new_state"]["state"] == "on"


async def test_websocket_auth_invalid(monkeypatch: Any) -> None:
    websocket = _FakeWebSocket(
        [
            json.dumps({"type": "auth_required"}),
            json.dumps({"type": "auth_invalid", "message": "Invalid access token"}),
        ]
    )
    _install_fake_connect(monkeypatch, {}, websocket)

    client = HomeAssistantClient("http://localhost:8123", "secret-invalid-token")
    stream = client.state_changes()
    with pytest.raises(HomeAssistantAuthError) as excinfo:
        await anext(stream)
    await stream.aclose()
    # token 与 HA 返回的 error message 均不得泄漏进异常
    assert "secret-invalid-token" not in str(excinfo.value)
    assert "Invalid access token" not in str(excinfo.value)


async def test_websocket_unexpected_auth_response(monkeypatch: Any) -> None:
    websocket = _FakeWebSocket(
        [
            json.dumps({"type": "auth_required"}),
            json.dumps({"type": "weird"}),
        ]
    )
    _install_fake_connect(monkeypatch, {}, websocket)

    client = HomeAssistantClient("http://localhost:8123", "tok")
    stream = client.state_changes()
    with pytest.raises(HomeAssistantError):
        await anext(stream)
    await stream.aclose()


async def test_websocket_filter_ignores_other_entities(monkeypatch: Any) -> None:
    messages = _ok_websocket_messages()[:3] + [
        json.dumps(
            {
                "id": 1,
                "type": "event",
                "event": {"data": {"entity_id": "switch.other"}},
            }
        ),
        json.dumps(
            {
                "id": 1,
                "type": "event",
                "event": {"data": {"entity_id": "light.demo", "new_state": {"state": "on"}}},
            }
        ),
    ]
    websocket = _FakeWebSocket(messages)
    _install_fake_connect(monkeypatch, {}, websocket)

    client = HomeAssistantClient("http://localhost:8123", "tok")
    stream = client.state_changes({"light.demo"})
    try:
        event = await anext(stream)
    finally:
        await stream.aclose()
    assert event["entity_id"] == "light.demo"
