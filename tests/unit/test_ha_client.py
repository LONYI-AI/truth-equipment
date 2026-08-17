import json
from typing import Any

from physical_agent.adapters import ha_client
from physical_agent.adapters.ha_client import HomeAssistantClient


class _FakeResponse:
    def __init__(self, payload: Any) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> Any:
        return self._payload


class _FakeHttpClient:
    def __init__(
        self,
        captured: dict[str, Any],
        payload: Any,
        **kwargs: Any,
    ) -> None:
        captured["client_kwargs"] = kwargs
        self._captured = captured
        self._payload = payload

    async def __aenter__(self) -> "_FakeHttpClient":
        return self

    async def __aexit__(
        self,
        exc_type: Any,
        exc: Any,
        tb: Any,
    ) -> None:
        return None

    async def request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
    ) -> _FakeResponse:
        self._captured["request"] = {
            "method": method,
            "path": path,
            "json": json,
        }
        return _FakeResponse(self._payload)


async def test_rest_client_disables_environment_proxy(monkeypatch: Any) -> None:
    captured: dict[str, Any] = {}

    def fake_async_client(**kwargs: Any) -> _FakeHttpClient:
        return _FakeHttpClient(
            captured,
            {"message": "API running."},
            **kwargs,
        )

    monkeypatch.setattr(
        ha_client.httpx,
        "AsyncClient",
        fake_async_client,
    )

    client = HomeAssistantClient(
        "http://localhost:8123",
        "test-token",
    )

    result = await client.api_status()

    assert result == {"message": "API running."}
    assert captured["client_kwargs"]["trust_env"] is False
    assert captured["client_kwargs"]["base_url"] == "http://localhost:8123"
    assert captured["request"] == {
        "method": "GET",
        "path": "/api/",
        "json": None,
    }


class _FakeWebSocket:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []
        self._messages = iter(
            [
                json.dumps({"type": "auth_required"}),
                json.dumps({"type": "auth_ok"}),
                json.dumps(
                    {
                        "id": 1,
                        "type": "result",
                        "success": True,
                    }
                ),
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
        )

    async def recv(self) -> str:
        return next(self._messages)

    async def send(self, raw: str) -> None:
        self.sent.append(json.loads(raw))


class _FakeWebSocketContext:
    def __init__(self, websocket: _FakeWebSocket) -> None:
        self.websocket = websocket

    async def __aenter__(self) -> _FakeWebSocket:
        return self.websocket

    async def __aexit__(
        self,
        exc_type: Any,
        exc: Any,
        tb: Any,
    ) -> None:
        return None


async def test_websocket_client_disables_proxy(monkeypatch: Any) -> None:
    captured: dict[str, Any] = {}
    websocket = _FakeWebSocket()

    def fake_connect(
        uri: str,
        **kwargs: Any,
    ) -> _FakeWebSocketContext:
        captured["uri"] = uri
        captured["connect_kwargs"] = kwargs
        return _FakeWebSocketContext(websocket)

    monkeypatch.setattr(
        ha_client,
        "connect",
        fake_connect,
    )

    client = HomeAssistantClient(
        "http://localhost:8123",
        "test-token",
    )

    stream = client.state_changes({"light.demo"})
    try:
        event = await anext(stream)
    finally:
        await stream.aclose()

    assert captured["uri"] == "ws://localhost:8123/api/websocket"
    assert captured["connect_kwargs"]["proxy"] is None

    assert websocket.sent[0] == {
        "type": "auth",
        "access_token": "test-token",
    }
    assert websocket.sent[1] == {
        "id": 1,
        "type": "subscribe_events",
        "event_type": "state_changed",
    }

    assert event["entity_id"] == "light.demo"
    assert event["old_state"]["state"] == "off"
    assert event["new_state"]["state"] == "on"
