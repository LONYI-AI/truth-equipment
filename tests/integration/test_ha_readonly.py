"""M1B 真实 Home Assistant 只读集成测试（opt-in，默认不执行）。

执行前置（全部满足才运行）：
- ``HA_REAL_TESTS=1``（显式 opt-in，防止 CI 误触真实 HA）
- ``HA_URL`` / ``HA_TOKEN``（真实 Home Assistant 连接）

只读：``GET /api/``、``GET /api/states``、实体发现。绝不发写动作。
"""

from __future__ import annotations

import os

import pytest

from physical_agent.adapters.ha_client import HomeAssistantClient

_REAL_HA = os.environ.get("HA_REAL_TESTS") == "1"
_HA_URL = os.environ.get("HA_URL", "")
_HA_TOKEN = os.environ.get("HA_TOKEN", "")

pytestmark = pytest.mark.skipif(
    not (_REAL_HA and _HA_URL and _HA_TOKEN),
    reason="real HA tests require HA_REAL_TESTS=1 + HA_URL + HA_TOKEN",
)


def _client() -> HomeAssistantClient:
    return HomeAssistantClient(_HA_URL, _HA_TOKEN)


async def test_api_status_ok() -> None:
    status = await _client().api_status()
    assert isinstance(status, dict)
    assert status.get("message") == "API running."


async def test_list_states_returns_entities() -> None:
    states = await _client().list_states()
    assert isinstance(states, list)
    assert len(states) > 0
    for entry in states:
        assert isinstance(entry.get("entity_id"), str)
        assert "state" in entry


async def test_get_state_reads_single_entity() -> None:
    states = await _client().list_states()
    sample = next(s for s in states if s.get("entity_id"))
    entity_id = sample["entity_id"]
    state = await _client().get_state(entity_id)
    assert state["entity_id"] == entity_id
    assert "state" in state


def test_discover_low_risk_candidates() -> None:
    """列出 light.* / switch.* 低风险候选（只读，不动作）。"""
    import asyncio

    async def _run() -> list[str]:
        states = await _client().list_states()
        candidates: list[str] = []
        for entry in states:
            entity_id = entry.get("entity_id", "")
            if entity_id.startswith(("light.", "switch.")):
                candidates.append(entity_id)
        return candidates

    candidates = asyncio.run(_run())
    # 断言：不包含任何高风险 domain
    forbidden_prefixes = (
        "lock.",
        "cover.",
        "climate.",
        "alarm_control_panel.",
        "water_heater.",
        "valve.",
    )
    for candidate in candidates:
        assert not candidate.startswith(forbidden_prefixes)
