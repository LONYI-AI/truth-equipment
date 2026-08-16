"""ExecutionMode（physical / simulation）明确化测试（P0-1 强化）。"""

from __future__ import annotations

from physical_agent.capability.request import CapabilityRequest


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
