"""Simulated Physical Loop（v3.0 §46）：不接触真实设备的完整闭环 + 故障注入。"""

from __future__ import annotations

from physical_agent.capability.request import CapabilityRequest
from physical_agent.runtime.base import RuntimeContext, UserIntent
from physical_agent.runtime.mock import MockRuntime


async def test_full_loop_turn_on_ac_v2(gateway, mock_device, audit):
    """完整链：request → policy → execute → adapter → mock device → verify V2 → audit。"""
    req = CapabilityRequest(
        capability_id="home.climate.turn_on",
        parameters={"temperature": 26, "mode": "cool"},
        correlation_id="loop1",
    )
    outcome = await gateway.execute(req)
    assert outcome["status"] == "completed"
    assert outcome["verification_level"] == "V2"
    # 模拟设备已开启
    assert mock_device.power == "on"
    assert mock_device.temperature == 26
    # 审计链完整且可校验
    audit.verify_chain()
    types = [e.event_type for e in audit.events()]
    assert "capability_requested" in types
    assert "policy_evaluated" in types
    assert "dispatched" in types
    assert "verification" in types


async def test_full_loop_v4_confirmation(gateway, mock_device):
    """V4 证据时，状态机推进到 PHYSICAL_EFFECT。"""
    mock_device.set_fault(evidence_level="V4")
    req = CapabilityRequest(
        capability_id="home.climate.turn_on",
        parameters={"temperature": 26, "mode": "cool"},
        correlation_id="loop2",
    )
    outcome = await gateway.execute(req)
    assert outcome["status"] == "completed"
    assert outcome["verification_level"] == "V4"
    assert outcome["physical_effect"] == "confirmed"
    assert outcome["state"] == "PHYSICAL_EFFECT"


async def test_actuation_failure(gateway, mock_device, audit):
    """执行器故障 → FAILED，审计记录 dispatch_failed。"""
    mock_device.set_fault(fail_actuation=True)
    req = CapabilityRequest(
        capability_id="home.climate.turn_on",
        parameters={"temperature": 26},
        correlation_id="loop3",
    )
    outcome = await gateway.execute(req)
    assert outcome["status"] == "failed"
    assert any(e.event_type == "dispatch_failed" for e in audit.events())


async def test_ir_readback_v2_is_not_physical_confirmation(gateway, mock_device):
    """V2（IR 回读）不能误判为物理效果已确认。"""
    mock_device.set_fault(evidence_level="V2")  # 仅 V2
    req = CapabilityRequest(
        capability_id="home.climate.turn_on",
        parameters={"temperature": 26},
        correlation_id="loop4",
    )
    outcome = await gateway.execute(req)
    assert outcome["verification_level"] == "V2"
    assert outcome["state"] == "ACTUATION_OBSERVED"  # 停在 V2，不宣称物理效果
    assert outcome["physical_effect"] == "pending"


async def test_mock_runtime_end_to_end(gateway, mock_device, audit):
    """MockRuntime 端到端：自然语言 → 物理设备。"""
    rt = MockRuntime(gateway)
    result = await rt.run(
        UserIntent(text="打开空调", session_id="s1"),
        RuntimeContext(correlation_id="e2e1", session_id="s1"),
    )
    assert result.status in ("completed", "partial")
    assert mock_device.power == "on"
    audit.verify_chain()


async def test_duplicate_commands_rate_limited(gateway):
    """重复命令（快速连续）→ 速率限制。"""
    outcomes = []
    for i in range(5):
        o = await gateway.execute(
            CapabilityRequest(capability_id="home.climate.turn_off", correlation_id=f"d{i}")
        )
        outcomes.append(o)
    # 前 3 次成功，后 2 次 rate limited
    assert outcomes[0]["status"] == "completed"
    assert any(o["status"] == "rejected" and "rate limit" in o["reason"] for o in outcomes)
