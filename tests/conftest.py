"""测试公共 fixtures。"""

from __future__ import annotations

import pytest

from physical_agent.adapters.mock import MockAdapter, MockDevice
from physical_agent.adapters.registry import AdapterRegistry
from physical_agent.audit.store import AuditStore
from physical_agent.capability.registry import CapabilityRegistry
from physical_agent.capability.schema import (
    CapabilityDefinition,
    Operation,
    ParameterSpec,
    SideEffect,
)
from physical_agent.execution.state_machine import ExecutionMode
from physical_agent.policy.approval import ApprovalEngine
from physical_agent.policy.engine import PolicyEngine
from physical_agent.policy.kill_switch import KillSwitch
from physical_agent.safety.gateway import CapabilityGateway


@pytest.fixture(autouse=True)
def _writes_enabled(monkeypatch):
    """默认开启写执行（fail-closed 测试用 monkeypatch 覆盖）。"""
    monkeypatch.setenv("AGENT_EXECUTION_ENABLED", "true")


@pytest.fixture
def registry() -> CapabilityRegistry:
    reg = CapabilityRegistry()
    reg.register(CapabilityDefinition(
        id="home.climate.turn_on",
        device_type="climate",
        parameters={
            "temperature": ParameterSpec(type="integer", minimum=16, maximum=30),
            "mode": ParameterSpec(type="string", enum=["cool", "heat", "dry", "fan_only"], required=False),
        },
        risk={"default": 1},
        side_effect=SideEffect.REVERSIBLE_WRITE,
        operation=Operation.EXECUTE,
    ))
    reg.register(CapabilityDefinition(
        id="home.climate.turn_off",
        device_type="climate",
        parameters={},
        risk={"default": 1},
        side_effect=SideEffect.REVERSIBLE_WRITE,
        operation=Operation.EXECUTE,
    ))
    reg.register(CapabilityDefinition(
        id="home.climate.set_temperature",
        device_type="climate",
        parameters={"temperature": ParameterSpec(type="integer", minimum=16, maximum=30)},
        risk={"default": 1},
        side_effect=SideEffect.REVERSIBLE_WRITE,
        operation=Operation.EXECUTE,
    ))
    reg.register(CapabilityDefinition(
        id="home.light.turn_on",
        device_type="light",
        parameters={},
        risk={"default": 1},
        side_effect=SideEffect.REVERSIBLE_WRITE,
        operation=Operation.EXECUTE,
    ))
    reg.register(CapabilityDefinition(
        id="home.lock.unlock",
        device_type="lock",
        parameters={},
        risk={"default": 3},
        side_effect=SideEffect.IRREVERSIBLE_WRITE,
        operation=Operation.EXECUTE,
    ))
    reg.register(CapabilityDefinition(
        id="home.sensor.read_temperature",
        device_type="sensor",
        parameters={},
        risk={"default": 0},
        side_effect=SideEffect.NONE,
        operation=Operation.OBSERVE,
    ))
    return reg


@pytest.fixture
def audit(tmp_path) -> AuditStore:
    return AuditStore(path=tmp_path / "audit.jsonl", checkpoint_path=tmp_path / "audit.checkpoint")


@pytest.fixture
def kill_switch(tmp_path) -> KillSwitch:
    return KillSwitch(kill_file=tmp_path / ".kill_switch")


@pytest.fixture
def mock_device() -> MockDevice:
    return MockDevice()


@pytest.fixture
def mock_adapter(mock_device: MockDevice) -> MockAdapter:
    return MockAdapter(mock_device)


@pytest.fixture
def adapters(mock_adapter: MockAdapter) -> AdapterRegistry:
    reg = AdapterRegistry()
    reg.register("home", mock_adapter)
    reg.mark_loaded()
    return reg


@pytest.fixture
def policy_engine(registry: CapabilityRegistry, kill_switch: KillSwitch) -> PolicyEngine:
    return PolicyEngine(registry, kill_switch)


@pytest.fixture
def approval_engine() -> ApprovalEngine:
    return ApprovalEngine()


@pytest.fixture
def gateway(
    registry: CapabilityRegistry,
    adapters: AdapterRegistry,
    kill_switch: KillSwitch,
    audit: AuditStore,
    approval_engine: ApprovalEngine,
) -> CapabilityGateway:
    # 默认 PHYSICAL（fail-closed 安全默认）
    return CapabilityGateway(
        registry=registry,
        adapters=adapters,
        mode=ExecutionMode.PHYSICAL,
        kill_switch=kill_switch,
        audit=audit,
        approval_engine=approval_engine,
    )


@pytest.fixture
def simulation_gateway(
    registry: CapabilityRegistry,
    adapters: AdapterRegistry,
    kill_switch: KillSwitch,
    audit: AuditStore,
    approval_engine: ApprovalEngine,
) -> CapabilityGateway:
    # SIMULATION：不接触真实设备，跳过 fail-closed 写闸门
    return CapabilityGateway(
        registry=registry,
        adapters=adapters,
        mode=ExecutionMode.SIMULATION,
        kill_switch=kill_switch,
        audit=audit,
        approval_engine=approval_engine,
    )
