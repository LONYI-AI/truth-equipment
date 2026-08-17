"""M1B Home Assistant 真实设备 composition root（PHYSICAL 模式）。

单一权威组装点：把真实 Home Assistant adapter 接入完整的 Safety Kernel 链路

    CapabilityGateway（policy + WriteGate + AuditStore）
        → HomeAssistantAdapter → HomeAssistantClient → HA REST/WebSocket

**安全边界**（与 M1A simulation composition 分开）：
- 本 composition **只**注册低风险白名单 capability（light/switch turn_on/off）。
  门锁/车库门/暖气/水阀等高风险 domain **不会**被注册，因此经 gateway 一律拒绝。
- PHYSICAL 模式强制持久签名审计（path + signing_key + checkpoint），缺一不可。
- 写执行仍受 WriteGate fail-closed 约束（AGENT_EXECUTION_ENABLED=true 等）。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from physical_agent.adapters.base import ExecutionDomain
from physical_agent.adapters.ha_client import HomeAssistantClient
from physical_agent.adapters.home_assistant import HomeAssistantAdapter
from physical_agent.adapters.registry import AdapterRegistry
from physical_agent.audit.store import AuditStore
from physical_agent.capability.registry import CapabilityRegistry
from physical_agent.capability.schema import (
    CapabilityDefinition,
    Operation,
    SideEffect,
    VerificationLevel,
    VerificationRequirement,
)
from physical_agent.execution.state_machine import ExecutionMode
from physical_agent.policy.approval import ApprovalEngine
from physical_agent.policy.engine import PolicyEngine
from physical_agent.policy.kill_switch import KillSwitch
from physical_agent.safety.gateway import CapabilityGateway


def default_ha_capabilities() -> list[CapabilityDefinition]:
    """M1B 低风险可写 capability 白名单（light/switch on/off）。

    高风险 domain（lock/cover/climate/alarm_control_panel/water_heater/valve）
    有意**不**在此注册：未注册 capability 会被 gateway fail-closed 拒绝。
    """
    return [
        CapabilityDefinition(
            id="home.light.turn_on",
            device_type="light",
            parameters={},
            risk={"default": 1},
            side_effect=SideEffect.REVERSIBLE_WRITE,
            operation=Operation.EXECUTE,
            verification=VerificationRequirement(required_level=VerificationLevel.V2),
        ),
        CapabilityDefinition(
            id="home.light.turn_off",
            device_type="light",
            parameters={},
            risk={"default": 1},
            side_effect=SideEffect.REVERSIBLE_WRITE,
            operation=Operation.EXECUTE,
            verification=VerificationRequirement(required_level=VerificationLevel.V2),
        ),
        CapabilityDefinition(
            id="home.switch.turn_on",
            device_type="switch",
            parameters={},
            risk={"default": 1},
            side_effect=SideEffect.REVERSIBLE_WRITE,
            operation=Operation.EXECUTE,
            verification=VerificationRequirement(required_level=VerificationLevel.V2),
        ),
        CapabilityDefinition(
            id="home.switch.turn_off",
            device_type="switch",
            parameters={},
            risk={"default": 1},
            side_effect=SideEffect.REVERSIBLE_WRITE,
            operation=Operation.EXECUTE,
            verification=VerificationRequirement(required_level=VerificationLevel.V2),
        ),
    ]


def default_ha_registry() -> CapabilityRegistry:
    reg = CapabilityRegistry()
    for definition in default_ha_capabilities():
        reg.register(definition)
    return reg


@dataclass
class HomeAssistantComposition:
    """M1B PHYSICAL HA composition 组件图。"""

    registry: CapabilityRegistry
    adapters: AdapterRegistry
    kill_switch: KillSwitch
    policy_engine: PolicyEngine
    approval_engine: ApprovalEngine
    audit: AuditStore
    gateway: CapabilityGateway
    client: HomeAssistantClient
    adapter: HomeAssistantAdapter


def build_home_assistant_composition(
    *,
    base_url: str,
    token: str,
    audit_path: Path,
    signing_key: bytes,
    checkpoint_path: Path,
    kill_file: Path | None = None,
    registry: CapabilityRegistry | None = None,
    checkpoint_interval: int = 1,
) -> HomeAssistantComposition:
    """组装 M1B PHYSICAL Home Assistant composition。

    ``signing_key`` / ``checkpoint_path`` / ``checkpoint_interval`` 是 PHYSICAL
    持久审计的硬性要求（见 ``AuditStore.is_physical_ready``）。缺任一都会让
    WriteGate fail-closed 拒绝写动作，因此必须显式提供。
    """
    client = HomeAssistantClient(base_url, token)
    adapter = HomeAssistantAdapter(client)

    adapters = AdapterRegistry()
    adapters.register("home", adapter, execution_domain=ExecutionDomain.PHYSICAL_ONLY)
    adapters.mark_loaded()

    registry = registry or default_ha_registry()
    kill_switch = KillSwitch(kill_file=kill_file)
    policy_engine = PolicyEngine(registry, kill_switch)
    approval_engine = ApprovalEngine()

    audit = AuditStore(
        path=audit_path,
        signing_key=signing_key,
        checkpoint_path=checkpoint_path,
        checkpoint_interval=checkpoint_interval,
    )

    gateway = CapabilityGateway(
        registry=registry,
        adapters=adapters,
        mode=ExecutionMode.PHYSICAL,
        kill_switch=kill_switch,
        policy_engine=policy_engine,
        approval_engine=approval_engine,
        audit=audit,
    )

    return HomeAssistantComposition(
        registry=registry,
        adapters=adapters,
        kill_switch=kill_switch,
        policy_engine=policy_engine,
        approval_engine=approval_engine,
        audit=audit,
        gateway=gateway,
        client=client,
        adapter=adapter,
    )
