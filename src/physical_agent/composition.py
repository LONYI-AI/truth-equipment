"""M1A-W5（Integration Hardening）Production composition root：单一权威组装点。

集中组装 Safety Kernel（CapabilityRegistry / AdapterRegistry / PolicyEngine /
ApprovalEngine / CapabilityGateway / AuditStore）+ MemoryStore + ReasoningModel +
Perception + NodeHandlers + LangGraph checkpointer/runtime，产出一个可启动、可交互的
M1A Simulation MVP。

**禁止**：测试代码自己拼一套、产品入口再拼另一套不同架构。所有正式入口（CLI、验收
测试）都必须经 `build_simulation_composition()` 组装。

**本轮禁止**（M1A Simulation 边界）：不接真实 Home Assistant、不做 ESPHome、不控制真实
设备、不做 Web UI / 手机 App / 多 Agent、不大规模重构 Safety Kernel、不开始 M1B。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from langgraph.checkpoint.memory import InMemorySaver

from physical_agent.adapters.base import ExecutionDomain
from physical_agent.adapters.mock import MockAdapter, MockDevice
from physical_agent.adapters.registry import AdapterRegistry
from physical_agent.audit.store import AuditStore
from physical_agent.capability.registry import CapabilityRegistry
from physical_agent.capability.schema import (
    CapabilityDefinition,
    Operation,
    ParameterSpec,
    SideEffect,
)
from physical_agent.execution.state_machine import ExecutionMode
from physical_agent.memory.store import SqliteMemoryStore
from physical_agent.policy.approval import ApprovalEngine
from physical_agent.policy.engine import PolicyEngine, RateLimiter
from physical_agent.policy.kill_switch import KillSwitch
from physical_agent.policy.risk import RiskContext
from physical_agent.runtime.assembly import build_node_handlers
from physical_agent.runtime.graph import NodeHandlers, build_graph
from physical_agent.runtime.langgraph import LangGraphRuntime
from physical_agent.runtime.nodes.perceive import PerceptionSnapshot, WorldStateSource
from physical_agent.runtime.nodes.reason import ReasoningModel
from physical_agent.runtime.reasoning import RuleBasedReasoningModel
from physical_agent.safety.gateway import CapabilityGateway

# 默认模拟设备 ID（与 default_ac_rules 的 device_id 一致）
DEFAULT_DEVICE_ID = "climate.bedroom_ac"


def default_simulation_capabilities() -> list[CapabilityDefinition]:
    """M1A Simulation 默认 capability 注册集（空调场景）。

    turn_on = risk 2（SIGNIFICANT → 需人工审批）；turn_off / set_temperature = risk 1。
    与 M1A-W4 审批闭环语义一致，使「调到 26 度」走 needs_approval 路径。
    """
    return [
        CapabilityDefinition(
            id="home.climate.turn_on",
            device_type="climate",
            parameters={
                "temperature": ParameterSpec(type="integer", minimum=16, maximum=30),
                "mode": ParameterSpec(
                    type="string", enum=["cool", "heat", "dry", "fan_only"], required=False
                ),
            },
            risk={"default": 2},
            side_effect=SideEffect.REVERSIBLE_WRITE,
            operation=Operation.EXECUTE,
        ),
        CapabilityDefinition(
            id="home.climate.turn_off",
            device_type="climate",
            parameters={},
            risk={"default": 1},
            side_effect=SideEffect.REVERSIBLE_WRITE,
            operation=Operation.EXECUTE,
        ),
        CapabilityDefinition(
            id="home.climate.set_temperature",
            device_type="climate",
            parameters={"temperature": ParameterSpec(type="integer", minimum=16, maximum=30)},
            risk={"default": 1},
            side_effect=SideEffect.REVERSIBLE_WRITE,
            operation=Operation.EXECUTE,
        ),
    ]


def default_simulation_registry() -> CapabilityRegistry:
    reg = CapabilityRegistry()
    for definition in default_simulation_capabilities():
        reg.register(definition)
    return reg


class SimulationPerceptionSource:
    """只读感知源：从 MockDevice 读取当前状态（同步，无副作用）。"""

    def __init__(self, device: MockDevice) -> None:
        self._device = device

    def read_snapshot(self) -> PerceptionSnapshot:
        return PerceptionSnapshot(
            devices={self._device.device_id: self._device.observe()},
            environment={"indoor_temperature": self._device.current_temp},
        )


@dataclass
class SimulationComposition:
    """一次组装产出的完整组件图（供 CLI / 验收测试复用同一架构）。"""

    registry: CapabilityRegistry
    adapters: AdapterRegistry
    kill_switch: KillSwitch
    policy_engine: PolicyEngine
    approval_engine: ApprovalEngine
    gateway: CapabilityGateway
    audit: AuditStore
    memory: SqliteMemoryStore
    device: MockDevice
    mock_adapter: MockAdapter
    reasoning_model: ReasoningModel
    perception_source: WorldStateSource
    handlers: NodeHandlers
    checkpointer: InMemorySaver
    graph: object
    runtime: LangGraphRuntime


def build_simulation_composition(
    *,
    device: MockDevice | None = None,
    registry: CapabilityRegistry | None = None,
    reasoning_model: ReasoningModel | None = None,
    perception_source: WorldStateSource | None = None,
    audit_path: Path | None = None,
    memory_path: Path | str | None = None,
    kill_file: Path | None = None,
    risk_context: RiskContext | None = None,
    rate_limiter: RateLimiter | None = None,
    mode: ExecutionMode = ExecutionMode.SIMULATION,
) -> SimulationComposition:
    """组装 M1A Simulation composition（单一权威入口）。

    所有组件在此集中组装；`LangGraphRuntime` 由本函数用真实 StateGraph +
    `InMemorySaver` checkpointer 接线。调用方只消费返回的 `SimulationComposition`，
    不得自行另拼一套（否则视为架构漂移）。

    `mode` 默认 SIMULATION（M1A 唯一合法模式；PHYSICAL 留待 M1B+）。
    """
    if mode != ExecutionMode.SIMULATION:
        raise ValueError("M1A Simulation composition only supports mode=SIMULATION")

    registry = registry or default_simulation_registry()
    device = device or MockDevice(DEFAULT_DEVICE_ID)
    mock_adapter = MockAdapter(device)

    adapters = AdapterRegistry()
    adapters.register("home", mock_adapter, execution_domain=ExecutionDomain.SIMULATION_ONLY)
    adapters.mark_loaded()

    kill_switch = KillSwitch(kill_file=kill_file)
    policy_engine = PolicyEngine(registry, kill_switch, rate_limiter=rate_limiter)
    approval_engine = ApprovalEngine()
    audit = AuditStore(path=audit_path)

    gateway = CapabilityGateway(
        registry=registry,
        adapters=adapters,
        mode=mode,
        kill_switch=kill_switch,
        audit=audit,
        policy_engine=policy_engine,
        approval_engine=approval_engine,
    )

    memory = SqliteMemoryStore(memory_path if memory_path is not None else ":memory:")
    reasoning_model = reasoning_model or RuleBasedReasoningModel()
    perception_source = perception_source or SimulationPerceptionSource(device)

    handlers = build_node_handlers(
        gateway,
        memory=memory,
        reasoning_model=reasoning_model,
        perception_source=perception_source,
        audit=audit,
        risk_context=risk_context,
    )

    checkpointer = InMemorySaver()
    graph = build_graph(handlers, checkpointer=checkpointer)

    runtime = LangGraphRuntime(
        gateway,
        graph=graph,
        handlers=handlers,
        checkpointer=checkpointer,
        audit=audit,
        memory=memory,
        reasoning_model=reasoning_model,
        perception_source=perception_source,
        risk_context=risk_context,
    )

    return SimulationComposition(
        registry=registry,
        adapters=adapters,
        kill_switch=kill_switch,
        policy_engine=policy_engine,
        approval_engine=approval_engine,
        gateway=gateway,
        audit=audit,
        memory=memory,
        device=device,
        mock_adapter=mock_adapter,
        reasoning_model=reasoning_model,
        perception_source=perception_source,
        handlers=handlers,
        checkpointer=checkpointer,
        graph=graph,
        runtime=runtime,
    )
