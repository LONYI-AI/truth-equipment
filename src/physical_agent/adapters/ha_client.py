"""Async Home Assistant REST + WebSocket client for M1B."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx
from websockets.asyncio.client import connect


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
    ) -> None:
        if not base_url:
            raise ValueError("base_url must not be empty")
        if not token:
            raise ValueError("token must not be empty")

        self.base_url = base_url.rstrip("/")
        self._token = token
        self.timeout_seconds = timeout_seconds

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

    async def api_status(self) -> dict[str, Any]:
        return await self._request_json("GET", "/api/")

    async def list_states(self) -> list[dict[str, Any]]:
        payload = await self._request_json("GET", "/api/states")
        if not isinstance(payload, list):
            raise HomeAssistantError("unexpected /api/states response")
        return payload

    async def get_state(self, entity_id: str) -> dict[str, Any]:
        payload = await self._request_json(
            "GET",
            f"/api/states/{entity_id}",
        )
        if not isinstance(payload, dict):
            raise HomeAssistantError("unexpected entity state response")
        return payload

    async def call_service(
        self,
        domain: str,
        service: str,
        data: dict[str, Any],
    ) -> list[dict[str, Any]]:
        payload = await self._request_json(
            "POST",
            f"/api/services/{domain}/{service}",
            json_body=data,
        )
        if not isinstance(payload, list):
            raise HomeAssistantError("unexpected service response")
        return payload

    async def state_changes(
        self,
        entity_ids: set[str] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Yield Home Assistant state_changed event data."""

        async with connect(
            self.websocket_url,
            open_timeout=self.timeout_seconds,
            proxy=None,
        ) as websocket:
            required = await self._recv_json(websocket)
            if required.get("type") != "auth_required":
                raise HomeAssistantError(
                    "expected auth_required from websocket"
                )

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
                    "Home Assistant websocket authentication failed"
                )
            if auth_result.get("type") != "auth_ok":
                raise HomeAssistantError(
                    "unexpected websocket authentication response"
                )

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
                if entity_ids is not None and entity_id not in entity_ids:
                    continue

                yield data

    async def _request_json(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
    ) -> Any:
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
                if exc.response.status_code in (401, 403):
                    raise HomeAssistantAuthError(
                        "Home Assistant authentication failed"
                    ) from exc
                raise HomeAssistantError(
                    f"Home Assistant returned HTTP "
                    f"{exc.response.status_code}"
                ) from exc
            except httpx.HTTPError as exc:
                raise HomeAssistantError(
                    "Home Assistant request failed"
                ) from exc

        try:
            return response.json()
        except ValueError as exc:
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
