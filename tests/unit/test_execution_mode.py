"""ExecutionMode（physical / simulation）明确化测试（P0-1 强化）。"""

from __future__ import annotations

import pytest

from physical_agent.adapters.base import Device, DeviceState, ExecutionDomain, ExecutionEvidence
from physical_agent.adapters.registry import AdapterRegistry
from physical_agent.audit.store import AuditStore
from physical_agent.capability.request import CapabilityRequest
from physical_agent.execution.state_machine import ExecutionMode
from physical_agent.policy.approval import ApprovalEngine
from physical_agent.safety.gateway import CapabilityGateway


class _RealLikeAdapter:
    """Adversarial physical-looking adapter: execution must never be reached in SIMULATION."""

    def __init__(self) -> None:
        self.execute_calls = 0

    async def discover(self) -> list[Device]:
        return []

    async def observe(self, device_id: str) -> DeviceState:
        return DeviceState(device_id=device_id)

    async def execute(self, request: object) -> ExecutionEvidence:
        self.execute_calls += 1
        return ExecutionEvidence(correlation_id="should-not-run", dispatched=True)

    async def verify(self, execution: ExecutionEvidence) -> ExecutionEvidence:
        return execution


async def test_simulation_mode_no_env_required(simulation_gateway, monkeypatch):
    """SIMULATION 模式不接触真实设备，无需 AGENT_EXECUTION_ENABLED。"""
    monkeypatch.delenv("AGENT_EXECUTION_ENABLED", raising=False)
    req = CapabilityRequest(capability_id="home.climate.turn_off", correlation_id="sim1")
    outcome = await simulation_gateway.execute(req)
    assert outcome["status"] == "completed"
    assert outcome["execution_mode"] == "simulation"


async def test_physical_mode_requires_env(gateway, monkeypatch):
    """PHYSICAL 模式必须 AGENT_EXECUTION_ENABLED=true（fail-closed）。"""
    monkeypatch.delenv("AGENT_EXECUTION_ENABLED", raising=False)
    req = CapabilityRequest(capability_id="home.climate.turn_off", correlation_id="phy1")
    outcome = await gateway.execute(req)
    assert outcome["status"] == "rejected"
    assert "AGENT_EXECUTION_ENABLED" in outcome["reason"]


async def test_physical_mode_marks_execution_mode(gateway):
    """PHYSICAL 模式成功执行时，结果明确标记 physical。"""
    req = CapabilityRequest(capability_id="home.climate.turn_off", correlation_id="phy2")
    outcome = await gateway.execute(req)
    assert outcome["status"] == "completed"
    assert outcome["execution_mode"] == "physical"


async def test_simulation_mode_marks_execution_mode(simulation_gateway):
    """SIMULATION 模式成功执行时，结果明确标记 simulation。"""
    req = CapabilityRequest(capability_id="home.climate.turn_off", correlation_id="sim2")
    outcome = await simulation_gateway.execute(req)
    assert outcome["status"] == "completed"
    assert outcome["execution_mode"] == "simulation"


async def test_kill_switch_blocks_simulation_too(simulation_gateway, kill_switch):
    """kill file（紧急停止）在 simulation 模式同样阻断写动作。"""
    kill_switch.activate()
    req = CapabilityRequest(capability_id="home.climate.turn_off", correlation_id="sim3")
    outcome = await simulation_gateway.execute(req)
    assert outcome["status"] == "rejected"
    assert "kill switch" in outcome["reason"]


async def test_audit_records_execution_mode(simulation_gateway, audit):
    """审计事件携带 execution_mode。"""
    req = CapabilityRequest(capability_id="home.climate.turn_off", correlation_id="sim4")
    await simulation_gateway.execute(req)
    requested = [e for e in audit.events() if e.event_type == "capability_requested"]
    assert requested
    assert requested[0].data.get("execution_mode") == "simulation"


async def test_simulation_rejects_physical_adapter_without_execute(registry, kill_switch, tmp_path):
    """A real-like adapter registered in SIMULATION is fail-closed before execute()."""
    real_like = _RealLikeAdapter()
    adapters = AdapterRegistry()
    adapters.register("home", real_like, execution_domain=ExecutionDomain.PHYSICAL_ONLY)
    adapters.mark_loaded()
    gw = CapabilityGateway(
        registry,
        adapters,
        mode=ExecutionMode.SIMULATION,
        kill_switch=kill_switch,
        audit=AuditStore(),
        approval_engine=ApprovalEngine(),
    )
    outcome = await gw.execute(CapabilityRequest(capability_id="home.climate.turn_off", correlation_id="adversary"))
    assert outcome["status"] == "rejected"
    assert "execution domain" in outcome["reason"]
    assert real_like.execute_calls == 0


async def test_physical_rejects_simulation_only_adapter(registry, kill_switch, audit):
    adapters = AdapterRegistry()
    adapters.register("home", _RealLikeAdapter(), execution_domain=ExecutionDomain.SIMULATION_ONLY)
    adapters.mark_loaded()
    gw = CapabilityGateway(
        registry,
        adapters,
        kill_switch=kill_switch,
        audit=audit,
        approval_engine=ApprovalEngine(),
    )
    outcome = await gw.execute(CapabilityRequest(capability_id="home.climate.turn_off", correlation_id="sim-only"))
    assert outcome["status"] == "rejected"
    assert "execution domain" in outcome["reason"]


def test_physical_mode_rejects_memory_only_audit(registry, kill_switch):
    with pytest.raises(ValueError, match="PHYSICAL mode requires"):
        CapabilityGateway(
            registry,
            AdapterRegistry(),
            mode=ExecutionMode.PHYSICAL,
            kill_switch=kill_switch,
            audit=AuditStore(),
            approval_engine=ApprovalEngine(),
        )
