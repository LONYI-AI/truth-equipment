"""P0-3 fail-closed Kill Switch / WriteGate 测试。"""

from __future__ import annotations

from physical_agent.capability.request import CapabilityRequest


async def test_missing_env_var_writes_rejected(gateway, monkeypatch):
    """AGENT_EXECUTION_ENABLED 缺失 → 写执行拒绝。"""
    monkeypatch.delenv("AGENT_EXECUTION_ENABLED", raising=False)
    req = CapabilityRequest(capability_id="home.climate.turn_off", correlation_id="fc1")
    outcome = await gateway.execute(req)
    assert outcome["status"] == "rejected"
    assert "AGENT_EXECUTION_ENABLED" in outcome["reason"]


async def test_false_env_var_writes_rejected(gateway, monkeypatch):
    """AGENT_EXECUTION_ENABLED=false → 写执行拒绝。"""
    monkeypatch.setenv("AGENT_EXECUTION_ENABLED", "false")
    req = CapabilityRequest(capability_id="home.climate.turn_off", correlation_id="fc2")
    outcome = await gateway.execute(req)
    assert outcome["status"] == "rejected"


async def test_true_plus_stack_allows(gateway):
    """AGENT_EXECUTION_ENABLED=true + 完整安全栈 → 写执行允许。"""
    req = CapabilityRequest(capability_id="home.climate.turn_off", correlation_id="fc3")
    outcome = await gateway.execute(req)
    assert outcome["status"] == "completed"


async def test_read_only_available_even_when_disabled(gateway, monkeypatch):
    """写被禁用时，只读观察仍可用。"""
    monkeypatch.setenv("AGENT_EXECUTION_ENABLED", "false")
    req = CapabilityRequest(capability_id="home.sensor.read_temperature", correlation_id="fc4")
    outcome = await gateway.execute(req)
    assert outcome["status"] == "completed"
    assert "observed" in outcome


async def test_kill_file_blocks_writes(gateway, kill_switch):
    """kill file 存在 → 写拒绝。"""
    kill_switch.activate()
    req = CapabilityRequest(capability_id="home.climate.turn_off", correlation_id="fc5")
    outcome = await gateway.execute(req)
    assert outcome["status"] == "rejected"
    assert "kill switch" in outcome["reason"]


async def test_write_gate_requires_allowlist_loaded(gateway, adapters, monkeypatch):
    """adapter allowlist 未加载 → 写拒绝（安全栈不完整）。"""
    # 构造一个 allowlist 未加载的 registry
    from physical_agent.adapters.registry import AdapterRegistry
    from physical_agent.audit.store import AuditStore
    from physical_agent.policy.approval import ApprovalEngine
    from physical_agent.safety.gateway import CapabilityGateway

    empty = AdapterRegistry()  # 未 mark_loaded，未注册
    gw = CapabilityGateway(
        registry=gateway.registry,
        adapters=empty,
        kill_switch=gateway.kill_switch,
        audit=AuditStore(),
        approval_engine=ApprovalEngine(),
    )
    req = CapabilityRequest(capability_id="home.climate.turn_off", correlation_id="fc6")
    outcome = await gw.execute(req)
    assert outcome["status"] == "rejected"
    assert "allowlist" in outcome["reason"]
