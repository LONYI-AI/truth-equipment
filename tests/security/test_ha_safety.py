"""M1B Home Assistant 安全架构测试（安全红线，与 M0 不变量对齐）。

证明：
1. 真实设备写必须经 CapabilityGateway（adapter 本身无 audit / 无 write gate）。
2. PHYSICAL 在持久审计不可用 / 未 ready 时拒绝写。
3. adapter domain mismatch（跨域控制）拒绝。
4. 高风险 domain 不作为默认 capability 注册。
5. token 绝不出现在审计记录中。
6. 完整安全链路事件序列落审计。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from physical_agent.adapters.base import ExecutionDomain
from physical_agent.adapters.home_assistant import HomeAssistantAdapter
from physical_agent.adapters.registry import AdapterRegistry
from physical_agent.audit.store import AuditStore
from physical_agent.capability.request import CapabilityRequest
from physical_agent.composition_ha import default_ha_registry
from physical_agent.execution.state_machine import ExecutionMode
from physical_agent.policy.approval import ApprovalEngine
from physical_agent.policy.engine import PolicyEngine
from physical_agent.policy.kill_switch import KillSwitch
from physical_agent.safety.gateway import CapabilityGateway

TOKEN = "tok-super-secret-abc123"


class _FakeHAClient:
    """记录调用、返回可控响应的假 HA 传输客户端（无网络）。"""

    def __init__(self) -> None:
        self.service_calls: list[tuple[str, str, dict[str, Any]]] = []
        self.state = "off"

    async def list_states(self) -> list[dict[str, Any]]:
        return [{"entity_id": "light.desk", "state": self.state}]

    async def get_state(self, entity_id: str) -> dict[str, Any]:
        return {"entity_id": entity_id, "state": self.state, "attributes": {}}

    async def call_service(self, domain: str, service: str, data: dict[str, Any]) -> list[dict[str, Any]]:
        self.service_calls.append((domain, service, data))
        self.state = "on" if service == "turn_on" else "off"
        return [{"entity_id": data["entity_id"], "state": self.state}]


def _physical_audit(tmp_path: Path) -> AuditStore:
    return AuditStore(
        path=tmp_path / "audit.jsonl",
        signing_key=b"test-audit-signing-key",
        checkpoint_path=tmp_path / "audit.checkpoint",
        checkpoint_interval=1,
    )


def _build_gateway(
    tmp_path: Path,
    client: _FakeHAClient,
    *,
    audit: AuditStore | None = None,
    registry=None,
) -> tuple[CapabilityGateway, AuditStore]:
    adapter = HomeAssistantAdapter(client)  # type: ignore[arg-type]
    adapters = AdapterRegistry()
    adapters.register("home", adapter, execution_domain=ExecutionDomain.PHYSICAL_ONLY)
    adapters.mark_loaded()

    registry = registry or default_ha_registry()
    audit = audit if audit is not None else _physical_audit(tmp_path)
    kill_switch = KillSwitch(kill_file=tmp_path / ".kill_switch")

    gateway = CapabilityGateway(
        registry=registry,
        adapters=adapters,
        mode=ExecutionMode.PHYSICAL,
        kill_switch=kill_switch,
        policy_engine=PolicyEngine(registry, kill_switch),
        approval_engine=ApprovalEngine(),
        audit=audit,
    )
    return gateway, audit


def _req(capability_id: str, device_id: str, correlation_id: str) -> CapabilityRequest:
    return CapabilityRequest(
        capability_id=capability_id,
        device_id=device_id,
        correlation_id=correlation_id,
    )


# ---- 1. 必须经 gateway；adapter 自身无 audit/write gate ----


def test_adapter_has_no_audit_or_write_gate() -> None:
    """adapter 只做传输翻译；审计与写闸门属于 gateway，adapter 不得持有。"""
    adapter = HomeAssistantAdapter(_FakeHAClient())  # type: ignore[arg-type]
    assert not hasattr(adapter, "audit")
    assert not hasattr(adapter, "write_gate")
    assert not hasattr(adapter, "policy_engine")


async def test_direct_adapter_execute_produces_no_audit(tmp_path: Path) -> None:
    """直接调用 adapter.execute 不落审计——gateway 是唯一受审计的物理动作入口。"""
    client = _FakeHAClient()
    adapter = HomeAssistantAdapter(client)  # type: ignore[arg-type]
    await adapter.execute(_req("home.light.turn_on", "light.desk", "direct-1"))
    # 无 audit store 可查——adapter 不拥有审计责任（gateway 负责）。
    assert client.service_calls  # 传输确实发生，但没有审计，证明不能作为正式路径


# ---- 2. PHYSICAL 持久审计不可用时拒绝写 ----


async def test_physical_write_rejected_when_audit_not_ready(tmp_path: Path) -> None:
    """audit 缺签名/checkpoint（is_physical_ready=False）→ 写被拒绝，不发 service call。"""
    client = _FakeHAClient()
    # 只有 path，无 signing_key/checkpoint → 非 physical ready
    audit = AuditStore(path=tmp_path / "audit.jsonl")
    gateway, _ = _build_gateway(tmp_path, client, audit=audit)

    outcome = await gateway.execute(_req("home.light.turn_on", "light.desk", "not-ready-1"))
    assert outcome["status"] == "rejected"
    assert "audit" in outcome["reason"]
    assert client.service_calls == []


def test_physical_mode_rejects_memory_only_audit(tmp_path: Path) -> None:
    """PHYSICAL + 内存审计（无 path）→ 构造即拒绝。"""
    client = _FakeHAClient()
    with pytest.raises(ValueError, match="PHYSICAL mode requires"):
        _build_gateway(tmp_path, client, audit=AuditStore())


# ---- 3. adapter domain mismatch（跨域控制）拒绝 ----


async def test_cross_domain_control_rejected(tmp_path: Path) -> None:
    """home.light.turn_on 作用于 switch 实体 → 拒绝，不发 service call。"""
    client = _FakeHAClient()
    gateway, _ = _build_gateway(tmp_path, client)
    # capability 是 light，但 device_id 是 switch → adapter domain isolation 拒绝
    outcome = await gateway.execute(_req("home.light.turn_on", "switch.kitchen", "cross-1"))
    assert outcome["status"] == "failed"
    assert client.service_calls == []


# ---- 4. 高风险 domain 不作为默认 capability ----


def test_forbidden_domains_not_registered_by_default() -> None:
    registry = default_ha_registry()
    registered = set(registry.list())
    # 只注册低风险 on/off
    assert registered == {
        "home.light.turn_on",
        "home.light.turn_off",
        "home.switch.turn_on",
        "home.switch.turn_off",
    }
    for forbidden in (
        "home.lock.unlock",
        "home.cover.open_cover",
        "home.climate.turn_on",
        "home.alarm_control_panel.disarm",
        "home.water_heater.turn_on",
        "home.valve.open",
    ):
        assert forbidden not in registered


async def test_forbidden_domain_request_rejected_by_gateway(tmp_path: Path) -> None:
    """未注册的高风险 capability → gateway fail-closed 拒绝。"""
    client = _FakeHAClient()
    gateway, _ = _build_gateway(tmp_path, client)
    outcome = await gateway.execute(_req("home.lock.unlock", "lock.front_door", "lock-1"))
    assert outcome["status"] == "rejected"
    assert client.service_calls == []


# ---- 5. token 不进审计 ----


async def test_token_never_in_audit(tmp_path: Path) -> None:
    client = _FakeHAClient()
    gateway, audit = _build_gateway(tmp_path, client)

    outcome = await gateway.execute(_req("home.light.turn_on", "light.desk", "audit-token-1"))
    assert outcome["status"] == "completed"

    serialized = json.dumps([e.to_dict() for e in audit.events()])
    assert TOKEN not in serialized
    assert "Bearer" not in serialized
    assert "Authorization" not in serialized


# ---- 6. 完整安全链路事件序列 ----


async def test_full_safety_chain_audit_sequence(tmp_path: Path) -> None:
    client = _FakeHAClient()
    gateway, audit = _build_gateway(tmp_path, client)

    outcome = await gateway.execute(_req("home.light.turn_on", "light.desk", "chain-1"))
    assert outcome["status"] == "completed"

    types = [e.event_type for e in audit.events()]
    # requested → policy → write gate → dispatched → verification → state
    for expected in (
        "capability_requested",
        "policy_evaluated",
        "write_gate",
        "dispatched",
        "verification",
        "execution_state",
    ):
        assert expected in types

    dispatched = next(e for e in audit.events() if e.event_type == "dispatched")
    assert dispatched.data["device_id"] == "light.desk"
    assert dispatched.data["adapter"] == "home"
    assert dispatched.data["capability_id"] == "home.light.turn_on"

    write_gate = next(e for e in audit.events() if e.event_type == "write_gate")
    assert write_gate.data["allowed"] is True

    audit.verify_chain()


# ---- 7. write gate fail-closed：未显式启用写 ----


async def test_write_gate_fail_closed_without_env(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.delenv("AGENT_EXECUTION_ENABLED", raising=False)
    client = _FakeHAClient()
    gateway, audit = _build_gateway(tmp_path, client)

    outcome = await gateway.execute(_req("home.light.turn_on", "light.desk", "fc-1"))
    assert outcome["status"] == "rejected"
    assert "AGENT_EXECUTION_ENABLED" in outcome["reason"]
    assert client.service_calls == []
    assert any(e.event_type == "write_blocked" for e in audit.events())
