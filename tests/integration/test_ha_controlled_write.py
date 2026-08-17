"""M1B 真实 Home Assistant 受控写集成测试（opt-in，且需人工确认实体）。

执行前置（全部满足才运行，缺任一即 skip）：
- ``HA_REAL_TESTS=1``
- ``HA_URL`` / ``HA_TOKEN``
- ``HA_CONFIRM_ENTITY``（明确指定的低风险 light.* / switch.* 实体，如 ``light.desk_lamp``）

安全约束：本测试**必须**经 ``build_home_assistant_composition`` 组装出的
CapabilityGateway 完整安全链路执行，绝不直接 curl / 直连 client 写动作。
"""

from __future__ import annotations

import os

import pytest

from physical_agent.capability.request import CapabilityRequest
from physical_agent.composition_ha import build_home_assistant_composition

_REAL_HA = os.environ.get("HA_REAL_TESTS") == "1"
_HA_URL = os.environ.get("HA_URL", "")
_HA_TOKEN = os.environ.get("HA_TOKEN", "")
_CONFIRM_ENTITY = os.environ.get("HA_CONFIRM_ENTITY", "")

pytestmark = pytest.mark.skipif(
    not (_REAL_HA and _HA_URL and _HA_TOKEN),
    reason="real HA tests require HA_REAL_TESTS=1 + HA_URL + HA_TOKEN",
)

# 只允许 light/switch 作为受控写目标；拒绝任何高风险 domain
_ALLOWED_WRITE_DOMAINS = {"light", "switch"}


def _composition(tmp_path):
    return build_home_assistant_composition(
        base_url=_HA_URL,
        token=_HA_TOKEN,
        audit_path=tmp_path / "audit.jsonl",
        signing_key=b"integration-audit-signing-key",
        checkpoint_path=tmp_path / "audit.checkpoint",
        checkpoint_interval=1,
    )


@pytest.mark.skipif(not _CONFIRM_ENTITY, reason="HA_CONFIRM_ENTITY not set")
async def test_controlled_write_turn_on_off(tmp_path) -> None:
    domain = _CONFIRM_ENTITY.split(".", 1)[0]
    assert domain in _ALLOWED_WRITE_DOMAINS, f"HA_CONFIRM_ENTITY must be light.*/switch.*, got {_CONFIRM_ENTITY!r}"

    comp = _composition(tmp_path)

    # 1. 只读确认初始状态
    before = await comp.client.get_state(_CONFIRM_ENTITY)
    assert before["entity_id"] == _CONFIRM_ENTITY

    # 2. 经 gateway 执行 turn_on（完整安全链路，非直连）
    on_outcome = await comp.gateway.execute(
        CapabilityRequest(
            capability_id=f"home.{domain}.turn_on",
            device_id=_CONFIRM_ENTITY,
            correlation_id="it-real-turn-on",
            principal="human",
        )
    )
    assert on_outcome["status"] == "completed"

    # 3. 读回验证实际状态
    after_on = await comp.client.get_state(_CONFIRM_ENTITY)
    assert after_on["state"] == "on"

    # 4. 经 gateway 执行 turn_off（第二次物理动作，仍走正式路径）
    off_outcome = await comp.gateway.execute(
        CapabilityRequest(
            capability_id=f"home.{domain}.turn_off",
            device_id=_CONFIRM_ENTITY,
            correlation_id="it-real-turn-off",
            principal="human",
        )
    )
    assert off_outcome["status"] == "completed"

    after_off = await comp.client.get_state(_CONFIRM_ENTITY)
    assert after_off["state"] == "off"

    # 5. 审计链完整 + 包含完整生命周期事件
    comp.audit.verify_chain()
    types = [e.event_type for e in comp.audit.events()]
    for expected in (
        "capability_requested",
        "policy_evaluated",
        "write_gate",
        "dispatched",
        "verification",
        "execution_state",
    ):
        assert expected in types

    # 6. token 绝不进入审计
    assert _HA_TOKEN not in repr([e.to_dict() for e in comp.audit.events()])
