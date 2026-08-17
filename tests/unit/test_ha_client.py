import json
from typing import Any

from physical_agent.adapters import ha_client
from physical_agent.adapters.ha_client import (
    HomeAssistantAuthError,
    HomeAssistantClient,
)
from physical_agent.audit.store import AuditStore


class _FakeResponse:
    def __init__(
        self,
        payload: Any,
        *,
        status_code: int = 200,
    ) -> None:
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code < 400:
            return

        request = ha_client.httpx.Request(
            "GET",
            "http://localhost:8123/api/",
        )
        response = ha_client.httpx.Response(
            self.status_code,
            request=request,
        )
        raise ha_client.httpx.HTTPStatusError(
            f"HTTP {self.status_code}",
            request=request,
            response=response,
        )

    def json(self) -> Any:
        return self._payload


class _FakeHttpClient:
    def __init__(
        self,
        captured: dict[str, Any],
        payload: Any,
        *,
        status_code: int = 200,
        **kwargs: Any,
    ) -> None:
        captured["client_kwargs"] = kwargs
        self._captured = captured
        self._payload = payload
        self._status_code = status_code

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
        return _FakeResponse(
            self._payload,
            status_code=self._status_code,
        )


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



async def test_rest_success_is_audited_with_correlation_id(
    monkeypatch: Any,
) -> None:
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

    audit = AuditStore()
    client = HomeAssistantClient(
        "http://localhost:8123",
        "super-secret-token",
        audit=audit,
    )

    result = await client.api_status(
        correlation_id="corr-rest-success",
    )

    assert result == {"message": "API running."}

    events = audit.events()
    assert [event.event_type for event in events] == [
        "ha_api_request",
        "ha_api_response",
    ]
    assert {
        event.correlation_id
        for event in events
    } == {"corr-rest-success"}

    assert events[0].data == {
        "transport": "rest",
        "method": "GET",
        "path": "/api/",
    }
    assert events[1].data == {
        "transport": "rest",
        "method": "GET",
        "path": "/api/",
        "status_code": 200,
    }

    serialized = repr(
        [event.to_dict() for event in events]
    )
    assert "super-secret-token" not in serialized


async def test_rest_generates_shared_correlation_id(
    monkeypatch: Any,
) -> None:
    captured: dict[str, Any] = {}

    def fake_async_client(**kwargs: Any) -> _FakeHttpClient:
        return _FakeHttpClient(
            captured,
            [],
            **kwargs,
        )

    monkeypatch.setattr(
        ha_client.httpx,
        "AsyncClient",
        fake_async_client,
    )

    audit = AuditStore()
    client = HomeAssistantClient(
        "http://localhost:8123",
        "test-token",
        audit=audit,
    )

    assert await client.list_states() == []

    events = audit.events()
    assert len(events) == 2

    request_event, response_event = events
    assert request_event.correlation_id.startswith("ha-")
    assert (
        response_event.correlation_id
        == request_event.correlation_id
    )


async def test_rest_auth_failure_is_audited(
    monkeypatch: Any,
) -> None:
    captured: dict[str, Any] = {}

    def fake_async_client(**kwargs: Any) -> _FakeHttpClient:
        return _FakeHttpClient(
            captured,
            {"message": "Unauthorized"},
            status_code=401,
            **kwargs,
        )

    monkeypatch.setattr(
        ha_client.httpx,
        "AsyncClient",
        fake_async_client,
    )

    audit = AuditStore()
    client = HomeAssistantClient(
        "http://localhost:8123",
        "test-token",
        audit=audit,
    )

    try:
        await client.api_status(
            correlation_id="corr-rest-auth-failure",
        )
    except HomeAssistantAuthError:
        pass
    else:
        raise AssertionError(
            "expected HomeAssistantAuthError"
        )

    events = audit.events()
    assert [event.event_type for event in events] == [
        "ha_api_request",
        "ha_api_error",
    ]
    assert {
        event.correlation_id
        for event in events
    } == {"corr-rest-auth-failure"}

    assert events[1].data == {
        "transport": "rest",
        "method": "GET",
        "path": "/api/",
        "status_code": 401,
        "error": "http_status",
    }


async def test_service_payload_is_not_written_to_audit(
    monkeypatch: Any,
) -> None:
    captured: dict[str, Any] = {}

    def fake_async_client(**kwargs: Any) -> _FakeHttpClient:
        return _FakeHttpClient(
            captured,
            [],
            **kwargs,
        )

    monkeypatch.setattr(
        ha_client.httpx,
        "AsyncClient",
        fake_async_client,
    )

    audit = AuditStore()
    client = HomeAssistantClient(
        "http://localhost:8123",
        "test-token",
        audit=audit,
    )

    await client.call_service(
        "light",
        "turn_on",
        {
            "entity_id": "light.demo",
            "secret_value": "DO-NOT-AUDIT-ME",
        },
        correlation_id="corr-service",
    )

    assert captured["request"]["json"] == {
        "entity_id": "light.demo",
        "secret_value": "DO-NOT-AUDIT-ME",
    }

    serialized = repr(
        [event.to_dict() for event in audit.events()]
    )
    assert "DO-NOT-AUDIT-ME" not in serialized
    assert "test-token" not in serialized



async def test_websocket_success_is_audited_without_secrets(
    monkeypatch: Any,
) -> None:
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

    audit = AuditStore()
    client = HomeAssistantClient(
        "http://localhost:8123",
        "super-secret-ws-token",
        audit=audit,
    )

    stream = client.state_changes(
        {"light.demo"},
        correlation_id="corr-ws-success",
    )
    try:
        event = await anext(stream)
    finally:
        await stream.aclose()

    assert event["entity_id"] == "light.demo"

    events = audit.events()
    assert [event.event_type for event in events] == [
        "ha_ws_connect",
        "ha_ws_authenticated",
        "ha_ws_subscribed",
    ]
    assert {
        event.correlation_id
        for event in events
    } == {"corr-ws-success"}

    assert events[0].data == {
        "transport": "websocket",
        "path": "/api/websocket",
    }
    assert events[1].data == {
        "transport": "websocket",
        "path": "/api/websocket",
    }
    assert events[2].data == {
        "transport": "websocket",
        "path": "/api/websocket",
        "event_type": "state_changed",
    }

    serialized = repr(
        [event.to_dict() for event in events]
    )
    assert "super-secret-ws-token" not in serialized
    assert "light.demo" not in serialized
    assert "old_state" not in serialized
    assert "new_state" not in serialized


class _AuthInvalidWebSocket(_FakeWebSocket):
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []
        self._messages = iter(
            [
                json.dumps({"type": "auth_required"}),
                json.dumps(
                    {
                        "type": "auth_invalid",
                        "message": "Invalid access token",
                    }
                ),
            ]
        )


async def test_websocket_auth_failure_is_audited(
    monkeypatch: Any,
) -> None:
    websocket = _AuthInvalidWebSocket()

    def fake_connect(
        uri: str,
        **kwargs: Any,
    ) -> _FakeWebSocketContext:
        del uri, kwargs
        return _FakeWebSocketContext(websocket)

    monkeypatch.setattr(
        ha_client,
        "connect",
        fake_connect,
    )

    audit = AuditStore()
    client = HomeAssistantClient(
        "http://localhost:8123",
        "secret-invalid-token",
        audit=audit,
    )

    stream = client.state_changes(
        correlation_id="corr-ws-auth-failure",
    )

    try:
        await anext(stream)
    except HomeAssistantAuthError:
        pass
    else:
        raise AssertionError(
            "expected HomeAssistantAuthError"
        )
    finally:
        await stream.aclose()

    events = audit.events()
    assert [event.event_type for event in events] == [
        "ha_ws_connect",
        "ha_ws_error",
    ]
    assert {
        event.correlation_id
        for event in events
    } == {"corr-ws-auth-failure"}

    assert events[1].data == {
        "transport": "websocket",
        "path": "/api/websocket",
        "phase": "auth",
        "error": "HomeAssistantAuthError",
    }

    serialized = repr(
        [event.to_dict() for event in events]
    )
    assert "secret-invalid-token" not in serialized
    assert "Invalid access token" not in serialized
