"""P0-7 AdapterRegistry 路由测试 + P0-9 side_effect 元数据测试。"""

from __future__ import annotations

import pytest

from physical_agent.adapters.base import ExecutionDomain
from physical_agent.adapters.mock import MockAdapter
from physical_agent.adapters.registry import AdapterRegistry, UnknownNamespaceError
from physical_agent.capability.schema import CapabilityDefinition, Operation, SideEffect


def test_route_by_namespace():
    reg = AdapterRegistry()
    ha = MockAdapter()
    reg.register("home", ha, execution_domain=ExecutionDomain.BOTH)
    assert reg.route("home.climate.turn_on") is ha


def test_unknown_namespace_raises():
    reg = AdapterRegistry()
    with pytest.raises(UnknownNamespaceError):
        reg.route("computer.app.launch")


def test_allowlist_loaded_flag():
    reg = AdapterRegistry()
    assert not reg.is_allowlist_loaded
    reg.register("home", MockAdapter(), execution_domain=ExecutionDomain.SIMULATION_ONLY)
    assert not reg.is_allowlist_loaded  # 未 mark_loaded
    reg.mark_loaded()
    assert reg.is_allowlist_loaded


def test_side_effect_is_explicit_not_inferred_from_tier():
    """P0-9：安全属性不得由 risk tier 隐式推断。"""
    # tier 0 但显式声明有副作用 → 不算只读
    write_cap = CapabilityDefinition(
        id="x", device_type="x", risk={"default": 0},
        side_effect=SideEffect.REVERSIBLE_WRITE, operation=Operation.EXECUTE,
    )
    assert not write_cap.is_read_only

    # tier 高但显式声明无副作用 → 只读
    read_cap = CapabilityDefinition(
        id="y", device_type="y", risk={"default": 3},
        side_effect=SideEffect.NONE, operation=Operation.OBSERVE,
    )
    assert read_cap.is_read_only


async def test_gateway_reads_via_side_effect_not_tier(gateway):
    """read_temperature（side_effect none）在写禁用时仍可读。"""
    from physical_agent.capability.request import CapabilityRequest
    req = CapabilityRequest(capability_id="home.sensor.read_temperature", correlation_id="se1")
    outcome = await gateway.execute(req)
    assert outcome["status"] == "completed"
    assert "observed" in outcome
