"""Adapter 契约测试（v3.0 §24）：所有 adapter 必须实现统一接口。"""

from __future__ import annotations

import inspect

from physical_agent.adapters.mock import MockAdapter


async def test_mock_adapter_satisfies_protocol():
    """MockAdapter 满足 DeviceAdapter 协议。"""
    adapter = MockAdapter()
    for name in ("discover", "observe", "execute", "verify"):
        assert hasattr(adapter, name)
        assert inspect.iscoroutinefunction(getattr(adapter, name))


async def test_discover_returns_capabilities():
    adapter = MockAdapter()
    devices = await adapter.discover()
    assert len(devices) == 1
    assert "home.climate.turn_on" in devices[0].capabilities


async def test_observe_returns_state():
    adapter = MockAdapter()
    state = await adapter.observe("mock.ac.bedroom")
    assert state.available
    assert "power" in state.state
