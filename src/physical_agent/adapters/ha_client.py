"""Async Home Assistant REST + WebSocket client for M1B."""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncGenerator
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx
from websockets.asyncio.client import connect

from physical_agent.audit.store import AuditStore


class HomeAssistantError(RuntimeError):
    """Base error for Home Assistant client failures."""


class HomeAssistantAuthError(HomeAssistantError):
    """Raised when Home Assistant rejects authentication."""


class HomeAssistantClient:
    """Minimal authenticated Home Assistant API client."""

    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        timeout_seconds: float = 10.0,
        audit: AuditStore | None = None,
    ) -> None:
        if not base_url:
            raise ValueError("base_url must not be empty")
        if not token:
            raise ValueError("token must not be empty")

        self.base_url = base_url.rstrip("/")
        self._token = token
        self.timeout_seconds = timeout_seconds
        self._audit = audit

    @property
    def websocket_url(self) -> str:
        parsed = urlsplit(self.base_url)
        if parsed.scheme == "http":
            scheme = "ws"
        elif parsed.scheme == "https":
            scheme = "wss"
        else:
            raise ValueError("base_url scheme must be http or https")

        return urlunsplit(
            (scheme, parsed.netloc, "/api/websocket", "", "")
        )

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }

    def _audit_event(
        self,
        event_type: str,
        correlation_id: str,
        data: dict[str, Any],
    ) -> None:
        if self._audit is not None:
            self._audit.append(event_type, correlation_id, data)

    @staticmethod
    def _new_correlation_id() -> str:
        return f"ha-{uuid.uuid4()}"

    async def api_status(
        self,
        *,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        return await self._request_json(
            "GET",
            "/api/",
            correlation_id=correlation_id,
        )

    async def list_states(
        self,
        *,
        correlation_id: str | None = None,
    ) -> list[dict[str, Any]]:
        payload = await self._request_json(
            "GET",
            "/api/states",
            correlation_id=correlation_id,
        )
        if not isinstance(payload, list):
            raise HomeAssistantError("unexpected /api/states response")
        return payload

    async def get_state(
        self,
        entity_id: str,
        *,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        payload = await self._request_json(
            "GET",
            f"/api/states/{entity_id}",
            correlation_id=correlation_id,
        )
        if not isinstance(payload, dict):
            raise HomeAssistantError("unexpected entity state response")
        return payload

    async def call_service(
        self,
        domain: str,
        service: str,
        data: dict[str, Any],
        *,
        correlation_id: str | None = None,
    ) -> list[dict[str, Any]]:
        payload = await self._request_json(
            "POST",
            f"/api/services/{domain}/{service}",
            json_body=data,
            correlation_id=correlation_id,
        )
        if not isinstance(payload, list):
            raise HomeAssistantError("unexpected service response")
        return payload

    async def state_changes(
        self,
        entity_ids: set[str] | None = None,
        *,
        correlation_id: str | None = None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Yield Home Assistant state_changed event data."""

        resolved_correlation_id = (
            correlation_id or self._new_correlation_id()
        )
        audit_data = {
            "transport": "websocket",
            "path": "/api/websocket",
        }

        self._audit_event(
            "ha_ws_connect",
            resolved_correlation_id,
            audit_data,
        )

        phase = "connect"

        try:
            async with connect(
                self.websocket_url,
                open_timeout=self.timeout_seconds,
                proxy=None,
            ) as websocket:
                phase = "handshake"
                required = await self._recv_json(websocket)
                if required.get("type") != "auth_required":
                    raise HomeAssistantError(
                        "expected auth_required from websocket"
                    )

                phase = "auth"
                await websocket.send(
                    json.dumps(
                        {
                            "type": "auth",
                            "access_token": self._token,
                        }
                    )
                )

                auth_result = await self._recv_json(websocket)
                if auth_result.get("type") == "auth_invalid":
                    raise HomeAssistantAuthError(
                        "Home Assistant websocket "
                        "authentication failed"
                    )
                if auth_result.get("type") != "auth_ok":
                    raise HomeAssistantError(
                        "unexpected websocket authentication response"
                    )

                self._audit_event(
                    "ha_ws_authenticated",
                    resolved_correlation_id,
                    audit_data,
                )

                phase = "subscribe"
                subscription_id = 1
                await websocket.send(
                    json.dumps(
                        {
                            "id": subscription_id,
                            "type": "subscribe_events",
                            "event_type": "state_changed",
                        }
                    )
                )

                subscription = await self._recv_json(websocket)
                if (
                    subscription.get("type") != "result"
                    or subscription.get("id") != subscription_id
                    or subscription.get("success") is not True
                ):
                    raise HomeAssistantError(
                        "state_changed subscription failed"
                    )

                self._audit_event(
                    "ha_ws_subscribed",
                    resolved_correlation_id,
                    {
                        **audit_data,
                        "event_type": "state_changed",
                    },
                )

                phase = "stream"

                while True:
                    message = await self._recv_json(websocket)
                    if (
                        message.get("type") != "event"
                        or message.get("id") != subscription_id
                    ):
                        continue

                    event = message.get("event")
                    if not isinstance(event, dict):
                        continue

                    data = event.get("data")
                    if not isinstance(data, dict):
                        continue

                    entity_id = data.get("entity_id")
                    if (
                        entity_ids is not None
                        and entity_id not in entity_ids
                    ):
                        continue

                    yield data
        except HomeAssistantError as exc:
            self._audit_event(
                "ha_ws_error",
                resolved_correlation_id,
                {
                    **audit_data,
                    "phase": phase,
                    "error": type(exc).__name__,
                },
            )
            raise

    async def _request_json(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        correlation_id: str | None = None,
    ) -> Any:
        resolved_correlation_id = (
            correlation_id or self._new_correlation_id()
        )

        audit_data = {
            "transport": "rest",
            "method": method,
            "path": path,
        }
        self._audit_event(
            "ha_api_request",
            resolved_correlation_id,
            audit_data,
        )

        async with httpx.AsyncClient(
            base_url=self.base_url,
            headers=self._headers,
            timeout=self.timeout_seconds,
            trust_env=False,
        ) as client:
            try:
                response = await client.request(
                    method,
                    path,
                    json=json_body,
                )
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                self._audit_event(
                    "ha_api_error",
                    resolved_correlation_id,
                    {
                        **audit_data,
                        "status_code": exc.response.status_code,
                        "error": "http_status",
                    },
                )
                if exc.response.status_code in (401, 403):
                    raise HomeAssistantAuthError(
                        "Home Assistant authentication failed"
                    ) from exc
                raise HomeAssistantError(
                    f"Home Assistant returned HTTP "
                    f"{exc.response.status_code}"
                ) from exc
            except httpx.HTTPError as exc:
                self._audit_event(
                    "ha_api_error",
                    resolved_correlation_id,
                    {
                        **audit_data,
                        "error": type(exc).__name__,
                    },
                )
                raise HomeAssistantError(
                    "Home Assistant request failed"
                ) from exc

        self._audit_event(
            "ha_api_response",
            resolved_correlation_id,
            {
                **audit_data,
                "status_code": response.status_code,
            },
        )

        try:
            return response.json()
        except ValueError as exc:
            self._audit_event(
                "ha_api_error",
                resolved_correlation_id,
                {
                    **audit_data,
                    "status_code": response.status_code,
                    "error": "invalid_json",
                },
            )
            raise HomeAssistantError(
                "Home Assistant returned invalid JSON"
            ) from exc

    async def _recv_json(self, websocket: Any) -> dict[str, Any]:
        try:
            async with asyncio.timeout(self.timeout_seconds):
                raw = await websocket.recv()
        except TimeoutError as exc:
            raise HomeAssistantError(
                "Home Assistant websocket timed out"
            ) from exc

        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")

        try:
            payload = json.loads(raw)
        except (TypeError, ValueError) as exc:
            raise HomeAssistantError(
                "Home Assistant websocket returned invalid JSON"
            ) from exc

        if not isinstance(payload, dict):
            raise HomeAssistantError(
                "unexpected Home Assistant websocket message"
            )

        return payload
