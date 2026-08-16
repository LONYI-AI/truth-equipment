"""M1A-W2 Perceive 节点测试：Fake HA → WorldState（simulation，无物理执行）。"""

from __future__ import annotations

import ast
import inspect
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError
from tests.fake_ha_server import FakeHAServer, FakeHASource

from physical_agent.runtime.nodes.perceive import (
    PerceptionSnapshot,
    WorldStateSource,
    make_perceive_handler,
)
from physical_agent.runtime.state import WorldState

FIXED_NOW = datetime(2026, 8, 16, 9, 0, 0, tzinfo=UTC)


def test_perceive_reads_fake_ha_into_world_state():
    with FakeHAServer() as server:
        source = FakeHASource(server.base_url)
        handler = make_perceive_handler(source, clock=lambda: FIXED_NOW)
        result = handler({"session_id": "s1", "correlation_id": "c1"})

        ws = result["world_state"]
        assert isinstance(ws, WorldState)
        # devices 正确
        assert ws.devices["climate.bedroom_ac"]["state"] == "off"
        assert ws.devices["climate.bedroom_ac"]["attributes"]["temperature"] == 28
        # environment 正确
        assert ws.environment["room_temperature"] == 28
        assert ws.environment["occupancy"] == "occupied"


def test_perceive_observed_at_is_timezone_aware():
    with FakeHAServer() as server:
        source = FakeHASource(server.base_url)
        handler = make_perceive_handler(source, clock=lambda: FIXED_NOW)
        ws = handler({})["world_state"]
        assert ws.observed_at == FIXED_NOW
        assert ws.observed_at.tzinfo is not None


def test_perceive_source_is_simulation_provenance_simulated():
    with FakeHAServer() as server:
        source = FakeHASource(server.base_url)
        handler = make_perceive_handler(source, clock=lambda: FIXED_NOW)
        ws = handler({})["world_state"]
        assert ws.source == "simulation"
        assert ws.provenance == "simulated"


def test_perceive_uses_injected_clock_deterministically():
    """clock 注入：确定性时间，禁止 sleep / wall-clock race。"""
    calls = []

    class FakeSource:
        def read_snapshot(self) -> PerceptionSnapshot:
            calls.append(1)
            return PerceptionSnapshot(devices={}, environment={})

    handler = make_perceive_handler(FakeSource(), clock=lambda: FIXED_NOW)
    ws1 = handler({})["world_state"]
    ws2 = handler({})["world_state"]
    assert ws1.observed_at == FIXED_NOW
    assert ws2.observed_at == FIXED_NOW  # 两次一致


def test_perceive_returns_only_world_state():
    """Perceive 只返回 world_state，不篡改 session_id/correlation_id/intent/messages。"""
    with FakeHAServer() as server:
        handler = make_perceive_handler(FakeHASource(server.base_url), clock=lambda: FIXED_NOW)
        result = handler({"session_id": "s1", "correlation_id": "c1"})
        assert set(result.keys()) == {"world_state"}


def test_world_state_source_protocol_read_only():
    """WorldStateSource 是只读契约：只有 read_snapshot，无 execute/write。"""
    assert hasattr(WorldStateSource, "read_snapshot")
    for forbidden in ("execute", "write", "dispatch"):
        assert not hasattr(WorldStateSource, forbidden)


def test_perceive_has_no_forbidden_imports():
    import physical_agent.runtime.nodes.perceive as mod

    _assert_no_forbidden_imports(mod)


def test_invalid_provenance_combo_rejected():
    """simulation + physical provenance 必须被拒绝（组合一致性）。"""
    with pytest.raises(ValidationError):
        WorldState(source="simulation", provenance="physical")


def _assert_no_forbidden_imports(mod) -> None:
    forbidden = ("physical_agent.execution", "physical_agent.safety.gateway", "physical_agent.policy.approval")
    for node in ast.walk(ast.parse(inspect.getsource(mod))):
        if isinstance(node, ast.ImportFrom) and node.module:
            assert node.module not in forbidden, f"{mod.__name__} imports {node.module}"
        elif isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name not in forbidden, f"{mod.__name__} imports {alias.name}"
