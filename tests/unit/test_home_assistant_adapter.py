"""HomeAssistantAdapter 单元测试（M1B）。

覆盖：capability→service 映射、discover/observe、execute 的 domain isolation、
verify 的 read-back 证据层级（V2/V3，不伪造 V4）、错误折叠为 dispatched=False。
"""

from __future__ import annotations

from typing import Any

import pytest

from physical_agent.adapters.home_assistant import HomeAssistantAdapter
from physical_agent.capability.request import CapabilityRequest


class _FakeHAClient:
    def __init__(
        self,
        *,
        states: list[dict[str, Any]] | None = None,
        entity_state: dict[str, Any] | None = None,
        service_result: list[dict[str, Any]] | None = None,
        raise_on_service: Exception | None = None,
    ) -> None:
        self._states = states or []
        self._entity_state = entity_state or {}
        self._service_result = service_result or []
        self._raise_on_service = raise_on_service
        self.service_calls: list[tuple[str, str, dict[str, Any]]] = []

    async def list_states(self) -> list[dict[str, Any]]:
        return self._states

    async def get_state(self, entity_id: str) -> dict[str, Any]:
        return {**self._entity_state, "entity_id": entity_id}

    async def call_service(self, domain: str, service: str, data: dict[str, Any]) -> list[dict[str, Any]]:
        self.service_calls.append((domain, service, data))
        if self._raise_on_service is not None:
            raise self._raise_on_service
        return self._service_result


def _adapter(client: _FakeHAClient) -> HomeAssistantAdapter:
    return HomeAssistantAdapter(client)  # type: ignore[arg-type]


def _req(capability_id: str, device_id: str = "", **params: Any) -> CapabilityRequest:
    return CapabilityRequest(
        capability_id=capability_id,
        device_id=device_id,
        parameters=params,
        correlation_id="corr-1",
    )


# ---- capability → service 解析 ----


def test_resolve_service_light() -> None:
    assert HomeAssistantAdapter.resolve_service("home.light.turn_on") == ("light", "turn_on")
    assert HomeAssistantAdapter.resolve_service("home.switch.turn_off") == ("switch", "turn_off")


def test_resolve_service_rejects_non_home() -> None:
    with pytest.raises(ValueError):
        HomeAssistantAdapter.resolve_service("computer.screen.turn_on")


@pytest.mark.parametrize(
    "capability_id",
    [
        "home.lock.unlock",
        "home.cover.open",
        "home.climate.turn_on",
        "home.alarm_control_panel.disarm",
        "home.water_heater.turn_on",
        "home.valve.open",
    ],
)
def test_resolve_service_rejects_forbidden_domains(capability_id: str) -> None:
    with pytest.raises(ValueError, match="forbidden"):
        HomeAssistantAdapter.resolve_service(capability_id)


# ---- discover / observe ----


async def test_discover_maps_domains_to_capabilities() -> None:
    client = _FakeHAClient(
        states=[
            {"entity_id": "light.desk", "state": "off"},
            {"entity_id": "switch.usb", "state": "off"},
            {"entity_id": "sensor.temp", "state": "21.5"},
            {"entity_id": "lock.front_door", "state": "locked"},
        ]
    )
    adapter = _adapter(client)
    devices = await adapter.discover()

    by_id = {d.device_id: d for d in devices}
    assert by_id["light.desk"].device_type == "light"
    assert by_id["light.desk"].capabilities == ["home.light.turn_on", "home.light.turn_off"]
    assert by_id["switch.usb"].capabilities == ["home.switch.turn_on", "home.switch.turn_off"]
    # 传感器只读：无写 capability
    assert by_id["sensor.temp"].capabilities == []
    # 高风险 domain：不暴露任何可写 capability
    assert by_id["lock.front_door"].capabilities == []


async def test_observe_returns_state() -> None:
    client = _FakeHAClient(entity_state={"state": "on", "attributes": {"brightness": 255}})
    adapter = _adapter(client)
    state = await adapter.observe("light.desk")
    assert state.device_id == "light.desk"
    assert state.available is True
    assert state.state["state"] == "on"
    assert state.state["attributes"]["brightness"] == 255


# ---- execute ----


async def test_execute_maps_to_ha_service_call() -> None:
    client = _FakeHAClient(service_result=[{"entity_id": "light.desk", "state": "on"}])
    adapter = _adapter(client)

    evidence = await adapter.execute(_req("home.light.turn_on", device_id="light.desk"))

    assert evidence.dispatched is True
    assert evidence.detail["domain"] == "light"
    assert evidence.detail["service"] == "turn_on"
    assert evidence.detail["entity_id"] == "light.desk"
    assert evidence.detail["expected_state"] == "on"
    assert client.service_calls == [("light", "turn_on", {"entity_id": "light.desk"})]


async def test_execute_requires_entity_id() -> None:
    client = _FakeHAClient()
    adapter = _adapter(client)
    evidence = await adapter.execute(_req("home.light.turn_on", device_id=""))
    assert evidence.dispatched is False
    assert "entity_id" in evidence.detail["error"]
    assert client.service_calls == []


async def test_execute_rejects_entity_domain_mismatch() -> None:
    """用 home.light.turn_on 去控制 switch 实体 → 拒绝，且绝不发 service call。"""
    client = _FakeHAClient(service_result=[{"entity_id": "switch.kitchen", "state": "on"}])
    adapter = _adapter(client)

    evidence = await adapter.execute(_req("home.light.turn_on", device_id="switch.kitchen"))

    assert evidence.dispatched is False
    assert "does not match" in evidence.detail["error"]
    assert client.service_calls == []


async def test_execute_rejects_forbidden_domain_capability() -> None:
    client = _FakeHAClient()
    adapter = _adapter(client)
    evidence = await adapter.execute(_req("home.lock.unlock", device_id="lock.front_door"))
    assert evidence.dispatched is False
    assert "forbidden" in evidence.detail["error"]
    assert client.service_calls == []


async def test_execute_folds_ha_error_into_evidence() -> None:
    from physical_agent.adapters.ha_client import HomeAssistantError

    client = _FakeHAClient(raise_on_service=HomeAssistantError("boom"))
    adapter = _adapter(client)
    evidence = await adapter.execute(_req("home.light.turn_on", device_id="light.desk"))
    assert evidence.dispatched is False
    # 只记录错误类型，不泄漏底层消息/secret
    assert evidence.detail["error"] == "HomeAssistantError"
    assert "boom" not in repr(evidence.detail)


async def test_execute_folds_empty_service_response() -> None:
    client = _FakeHAClient(service_result=[])
    adapter = _adapter(client)
    evidence = await adapter.execute(_req("home.light.turn_on", device_id="light.desk"))
    assert evidence.dispatched is False
    assert "empty service response" in evidence.detail["error"]


# ---- verify ----


async def test_verify_read_back_match_gives_device_evidence() -> None:
    client = _FakeHAClient(entity_state={"state": "on"})
    adapter = _adapter(client)

    from physical_agent.adapters.base import ExecutionEvidence

    evidence = ExecutionEvidence(
        correlation_id="corr-1",
        dispatched=True,
        detail={"entity_id": "light.desk", "expected_state": "on"},
    )
    verified = await adapter.verify(evidence)

    assert verified.actuation_observed is True
    assert verified.device_evidence is True
    # 灯无法用独立传感器验证物理效果，不得伪造 V4
    assert verified.physical_effect_verified is False
    assert verified.physical_effect == "pending"


async def test_verify_read_back_mismatch_only_actuation() -> None:
    client = _FakeHAClient(entity_state={"state": "off"})
    adapter = _adapter(client)

    from physical_agent.adapters.base import ExecutionEvidence

    evidence = ExecutionEvidence(
        correlation_id="corr-1",
        dispatched=True,
        detail={"entity_id": "light.desk", "expected_state": "on"},
    )
    verified = await adapter.verify(evidence)

    assert verified.actuation_observed is True
    assert verified.device_evidence is False


async def test_verify_not_dispatched_is_unchanged() -> None:
    from physical_agent.adapters.base import ExecutionEvidence

    client = _FakeHAClient()
    adapter = _adapter(client)
    evidence = ExecutionEvidence(correlation_id="corr-1", dispatched=False)
    verified = await adapter.verify(evidence)
    assert verified.dispatched is False
    assert verified.actuation_observed is False
