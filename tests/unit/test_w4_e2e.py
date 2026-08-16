"""M1A-W4 E2E 测试：第一个完整 simulation 用户闭环。

覆盖（全部真实 graph.ainvoke + 真实 CapabilityGateway + MockAdapter，非 sentinel）：
- A. 审批闭环：打开空调到 26 度 → perceive→recall→reason→plan→policy(NEEDS_APPROVAL)
     → human_review interrupt → Owner grant → Command(resume approve) → re-policy+consume
     → execute(MockAdapter) → verify → success boundary（复用 W3 审批生命周期，不重建）。
- B. 无需审批 path：turn_off（risk=1）→ APPROVED → execute → verify 成功。
- C. SIMULATION-only 硬边界：execute_authorized_simulation 在非 SIMULATION 模式
     fail-closed REJECT，adapter.execute 绝不调用。
- D. verify 成功语义：V2 达 required_level 即 satisfied，physical_effect 保持 pending，
     绝不伪造 confirmed（V2 不冒充 V4）；evidence["provenance"]=="simulated"。
"""

from __future__ import annotations

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from tests.mock_llm import MockReasoningModel

from physical_agent.adapters.base import ExecutionDomain
from physical_agent.adapters.mock import MockAdapter, MockDevice
from physical_agent.adapters.registry import AdapterRegistry
from physical_agent.audit.store import AuditStore
from physical_agent.capability.registry import CapabilityRegistry
from physical_agent.capability.request import CapabilityRequest
from physical_agent.capability.schema import (
    CapabilityDefinition,
    Operation,
    ParameterSpec,
    SideEffect,
    VerificationLevel,
)
from physical_agent.execution.state_machine import ExecutionMode
from physical_agent.memory.store import SqliteMemoryStore
from physical_agent.policy.approval import ApprovalEngine
from physical_agent.policy.engine import PolicyDecision, PolicyEngine
from physical_agent.policy.kill_switch import KillSwitch
from physical_agent.policy.risk import RiskTier
from physical_agent.runtime.base import UserIntent
from physical_agent.runtime.graph import NodeHandlers, build_graph
from physical_agent.runtime.nodes import (
    make_execute_handler,
    make_human_review_handler,
    make_perceive_handler,
    make_plan_handler,
    make_policy_gate_handler,
    make_reason_handler,
    make_recall_handler,
    make_verify_handler,
)
from physical_agent.runtime.nodes.perceive import PerceptionSnapshot, WorldStateSource
from physical_agent.runtime.planning import PolicyRoute, ReasoningDecision, ReasoningRoute
from physical_agent.safety.gateway import CapabilityGateway


def _w4_registry() -> CapabilityRegistry:
    """turn_on=risk2(需审批)；turn_off=risk1(无需审批)。"""
    reg = CapabilityRegistry()
    reg.register(CapabilityDefinition(
        id="home.climate.turn_on",
        device_type="climate",
        parameters={
            "temperature": ParameterSpec(type="integer", minimum=16, maximum=30),
            "mode": ParameterSpec(type="string", enum=["cool", "heat", "dry", "fan_only"], required=False),
        },
        risk={"default": 2},  # SIGNIFICANT → requires_approval
        side_effect=SideEffect.REVERSIBLE_WRITE,
        operation=Operation.EXECUTE,
    ))
    reg.register(CapabilityDefinition(
        id="home.climate.turn_off",
        device_type="climate",
        parameters={},
        risk={"default": 1},  # LOW_REVERSIBLE → no approval
        side_effect=SideEffect.REVERSIBLE_WRITE,
        operation=Operation.EXECUTE,
    ))
    return reg


class _InlineSource(WorldStateSource):
    def read_snapshot(self) -> PerceptionSnapshot:
        return PerceptionSnapshot(devices={"climate.bedroom_ac": {"state": "off"}}, environment={})


def _spy(name: str, sink: list[str]):
    def handler(state):
        sink.append(name)
        return {}

    return handler


def _initial_state(**overrides):
    base = {
        "messages": [],
        "session_id": "s1",
        "correlation_id": "req-1",
        "intent": UserIntent(text="打开空调到26度", principal="human", session_id="s1"),
    }
    base.update(overrides)
    return base


# ---- A. 审批闭环：打开空调到 26 度 ----

async def test_w4_approval_e2e_full(tmp_path):
    reg = _w4_registry()
    kill_switch = KillSwitch(kill_file=tmp_path / ".kill_switch")
    audit = AuditStore(path=tmp_path / "audit.jsonl")
    mock_device = MockDevice()

    policy_engine = PolicyEngine(reg, kill_switch)
    approval_engine = ApprovalEngine()
    mock_adapter = MockAdapter(mock_device)
    adapters = AdapterRegistry()
    adapters.register("home", mock_adapter, execution_domain=ExecutionDomain.BOTH)
    adapters.mark_loaded()
    gateway = CapabilityGateway(
        registry=reg, adapters=adapters, mode=ExecutionMode.SIMULATION,
        kill_switch=kill_switch, audit=audit,
        policy_engine=policy_engine, approval_engine=approval_engine,
    )

    decision = ReasoningDecision(
        route=ReasoningRoute.PLAN,
        capability_id="home.climate.turn_on",
        device_id="mock.ac.bedroom",
        parameters={"temperature": 26, "mode": "cool"},
    )
    model = MockReasoningModel([decision])
    store = SqliteMemoryStore(":memory:")
    visited: list[str] = []

    handlers = NodeHandlers(
        perceive=make_perceive_handler(_InlineSource()),
        recall=make_recall_handler(store),
        reason=make_reason_handler(model),
        plan=make_plan_handler(),
        policy_gate=make_policy_gate_handler(policy_engine, approval_engine, audit=audit),
        execute=make_execute_handler(gateway),
        verify=make_verify_handler(),
        compensate=_spy("compensate", visited),
        memory_update=_spy("memory_update", visited),
        escalate=_spy("escalate", visited),
        human_review=make_human_review_handler(policy_engine, approval_engine, audit=audit),
    )
    graph = build_graph(handlers, checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "w4-approval-full"}}

    r1 = await graph.ainvoke(_initial_state(), config)
    assert "__interrupt__" in r1
    approval_id = r1["__interrupt__"][0].value["approval_id"]
    assert mock_device.power == "off"  # 尚未执行

    # Owner grant（复用 W3 ApprovalEngine）
    approval_engine.grant(approval_id, approver="owner")

    # resume approve → re-policy + consume → execute → verify
    r2 = await graph.ainvoke(Command(resume={"decision": "approve"}), config)

    # 成功闭环断言
    assert r2["verification_satisfied"] is True
    assert r2["verification"].level == VerificationLevel.V2
    # V2 达 required_level 即 satisfied，但绝不伪造 V4 physical confirmation
    assert r2["verification"].physical_effect == "pending"
    assert r2["verification"].evidence["provenance"] == "simulated"
    # 真实执行到 mock device
    assert mock_device.power == "on"
    assert mock_device.temperature == 26
    # 到达成功终态
    assert "memory_update" in visited
    assert "compensate" not in visited
    assert "escalate" not in visited


# ---- B. 无需审批 path：turn_off ----

async def test_w4_no_approval_e2e(tmp_path):
    reg = _w4_registry()
    kill_switch = KillSwitch(kill_file=tmp_path / ".kill_switch")
    audit = AuditStore(path=tmp_path / "audit.jsonl")
    mock_device = MockDevice()
    mock_device.power = "on"  # 前置：已开启，才能 turn_off

    policy_engine = PolicyEngine(reg, kill_switch)
    approval_engine = ApprovalEngine()
    mock_adapter = MockAdapter(mock_device)
    adapters = AdapterRegistry()
    adapters.register("home", mock_adapter, execution_domain=ExecutionDomain.BOTH)
    adapters.mark_loaded()
    gateway = CapabilityGateway(
        registry=reg, adapters=adapters, mode=ExecutionMode.SIMULATION,
        kill_switch=kill_switch, audit=audit,
        policy_engine=policy_engine, approval_engine=approval_engine,
    )

    decision = ReasoningDecision(
        route=ReasoningRoute.PLAN,
        capability_id="home.climate.turn_off",
        device_id="mock.ac.bedroom",
        parameters={},
    )
    model = MockReasoningModel([decision])
    store = SqliteMemoryStore(":memory:")
    visited: list[str] = []

    handlers = NodeHandlers(
        perceive=make_perceive_handler(_InlineSource()),
        recall=make_recall_handler(store),
        reason=make_reason_handler(model),
        plan=make_plan_handler(),
        policy_gate=make_policy_gate_handler(policy_engine, approval_engine, audit=audit),
        execute=make_execute_handler(gateway),
        verify=make_verify_handler(),
        compensate=_spy("compensate", visited),
        memory_update=_spy("memory_update", visited),
        escalate=_spy("escalate", visited),
        human_review=make_human_review_handler(policy_engine, approval_engine, audit=audit),
    )
    graph = build_graph(handlers, checkpointer=InMemorySaver())

    # 无需审批：直接 APPROVED → execute，无 interrupt
    result = await graph.ainvoke(_initial_state(), {"configurable": {"thread_id": "w4-noapproval"}})
    assert result["policy_route"] is PolicyRoute.APPROVED
    assert result["verification_satisfied"] is True
    assert mock_device.power == "off"  # 真实执行 turn_off
    assert "memory_update" in visited


# ---- C. SIMULATION-only 硬边界 ----

async def test_execute_authorized_simulation_rejects_non_simulation(tmp_path):
    """非 SIMULATION 模式 → execute_authorized_simulation fail-closed REJECT，adapter 零调用。"""
    reg = _w4_registry()
    kill_switch = KillSwitch(kill_file=tmp_path / ".kill_switch")
    audit = AuditStore(
        path=tmp_path / "audit.jsonl",
        signing_key=b"test-signing-key",
        checkpoint_path=tmp_path / "audit.checkpoint",
        checkpoint_interval=1,
    )
    mock_adapter = MockAdapter(MockDevice())
    adapters = AdapterRegistry()
    adapters.register("home", mock_adapter, execution_domain=ExecutionDomain.BOTH)
    adapters.mark_loaded()

    gateway = CapabilityGateway(
        registry=reg, adapters=adapters, mode=ExecutionMode.PHYSICAL,
        kill_switch=kill_switch, audit=audit,
    )

    request = CapabilityRequest(
        capability_id="home.climate.turn_on",
        parameters={"temperature": 26, "mode": "cool"},
        correlation_id="phys-reject",
    )
    decision = PolicyDecision(True, RiskTier.SIGNIFICANT, "ok", True, "phys-reject")
    outcome = await gateway.execute_authorized_simulation(request, decision)

    assert outcome["status"] == "rejected"
    assert mock_adapter.execute_calls == 0  # adapter.execute NEVER CALLED


# ---- 单元：execute_authorized_simulation 的 fail-closed 分支 + execute 缺字段 ----

def _make_sim_gateway(tmp_path):
    """构造 SIMULATION gateway + mock_adapter（供 fail-closed 分支单测）。"""
    reg = _w4_registry()
    kill_switch = KillSwitch(kill_file=tmp_path / ".kill_switch")
    audit = AuditStore(path=tmp_path / "audit.jsonl")
    mock_device = MockDevice()
    mock_adapter = MockAdapter(mock_device)
    adapters = AdapterRegistry()
    adapters.register("home", mock_adapter, execution_domain=ExecutionDomain.BOTH)
    adapters.mark_loaded()
    gateway = CapabilityGateway(
        registry=reg, adapters=adapters, mode=ExecutionMode.SIMULATION,
        kill_switch=kill_switch, audit=audit,
    )
    return gateway, mock_adapter


async def test_execute_authorized_simulation_denied_decision_rejected(tmp_path):
    """decision.allowed=False → fail-closed REJECT，adapter 零调用。"""
    gateway, mock_adapter = _make_sim_gateway(tmp_path)
    request = CapabilityRequest(
        capability_id="home.climate.turn_on",
        parameters={"temperature": 26},
        correlation_id="denied-1",
    )
    denied = PolicyDecision(False, RiskTier.SAFETY_SENSITIVE, "kill switch active", False, "denied-1")
    outcome = await gateway.execute_authorized_simulation(request, denied)
    assert outcome["status"] == "rejected"
    assert mock_adapter.execute_calls == 0


async def test_execute_authorized_simulation_unknown_capability_rejected(tmp_path):
    """未知 capability → fail-closed REJECT（registry allowlist），adapter 零调用。"""
    gateway, mock_adapter = _make_sim_gateway(tmp_path)
    request = CapabilityRequest(
        capability_id="home.unknown.thing",
        parameters={},
        correlation_id="unknown-1",
    )
    decision = PolicyDecision(True, RiskTier.LOW_REVERSIBLE, "ok", False, "unknown-1")
    outcome = await gateway.execute_authorized_simulation(request, decision)
    assert outcome["status"] == "rejected"
    assert mock_adapter.execute_calls == 0


async def test_execute_authorized_simulation_duplicate_rejected(tmp_path):
    """同一 correlation_id 二次派发 → 幂等 REJECT，无第二次 adapter.execute。"""
    gateway, mock_adapter = _make_sim_gateway(tmp_path)
    request = CapabilityRequest(
        capability_id="home.climate.turn_off",
        parameters={},
        correlation_id="dup-1",
    )
    decision = PolicyDecision(True, RiskTier.LOW_REVERSIBLE, "ok", False, "dup-1")
    first = await gateway.execute_authorized_simulation(request, decision)
    assert first["status"] in ("completed", "partial")
    assert mock_adapter.execute_calls == 1

    second = await gateway.execute_authorized_simulation(request, decision)
    assert second["status"] == "rejected"
    assert mock_adapter.execute_calls == 1  # 无第二次 execute


async def test_execute_handler_missing_request_fail_closed(tmp_path):
    """execute 节点缺 current_request / policy_decision → fail-closed rejected outcome。"""
    gateway, _adapter = _make_sim_gateway(tmp_path)
    handler = make_execute_handler(gateway)
    outcome = await handler({})
    assert outcome["execution_outcome"]["status"] == "rejected"
    assert "missing canonical request or policy decision" in outcome["execution_outcome"]["reason"]


# ---- E. REV2：真实 execute+verify 失败 → fail-closed 到 compensate（无 recursion）----

async def test_w4_dispatch_failure_fail_closed_no_recursion(tmp_path):
    """真实 execute + verify 路径制造 dispatch failure，证明：
    graph 正常结束、无 recursion loop、execute 不重复、compensate 恰好到达、memory_update 不调用。
    """
    # 自定义 registry：turn_on 无需审批（risk=1），便于直接 APPROVED → execute
    reg = CapabilityRegistry()
    reg.register(CapabilityDefinition(
        id="home.climate.turn_on",
        device_type="climate",
        parameters={"temperature": ParameterSpec(type="integer", minimum=16, maximum=30)},
        risk={"default": 1},
        side_effect=SideEffect.REVERSIBLE_WRITE,
        operation=Operation.EXECUTE,
    ))

    kill_switch = KillSwitch(kill_file=tmp_path / ".kill_switch")
    audit = AuditStore(path=tmp_path / "audit.jsonl")
    mock_device = MockDevice()
    mock_device.set_fault(fail_actuation=True)  # 注入 dispatch failure

    policy_engine = PolicyEngine(reg, kill_switch)
    approval_engine = ApprovalEngine()
    mock_adapter = MockAdapter(mock_device)
    adapters = AdapterRegistry()
    adapters.register("home", mock_adapter, execution_domain=ExecutionDomain.BOTH)
    adapters.mark_loaded()
    gateway = CapabilityGateway(
        registry=reg, adapters=adapters, mode=ExecutionMode.SIMULATION,
        kill_switch=kill_switch, audit=audit,
        policy_engine=policy_engine, approval_engine=approval_engine,
    )

    decision = ReasoningDecision(
        route=ReasoningRoute.PLAN,
        capability_id="home.climate.turn_on",
        device_id="mock.ac.bedroom",
        parameters={"temperature": 26},
    )
    model = MockReasoningModel([decision])
    store = SqliteMemoryStore(":memory:")
    visited: list[str] = []

    handlers = NodeHandlers(
        perceive=make_perceive_handler(_InlineSource()),
        recall=make_recall_handler(store),
        reason=make_reason_handler(model),
        plan=make_plan_handler(),
        policy_gate=make_policy_gate_handler(policy_engine, approval_engine, audit=audit),
        execute=make_execute_handler(gateway),
        verify=make_verify_handler(),
        compensate=_spy("compensate", visited),
        memory_update=_spy("memory_update", visited),
        escalate=_spy("escalate", visited),
        human_review=make_human_review_handler(policy_engine, approval_engine, audit=audit),
    )
    graph = build_graph(handlers, checkpointer=InMemorySaver())

    # 无审批 → APPROVED → execute（dispatch failure）→ verify failed → compensate → END
    result = await graph.ainvoke(_initial_state(), {"configurable": {"thread_id": "w4-fail"}})

    # 证明：正常结束（无 interrupt）、不 recursion、execute 不重复、compensate 到达、memory_update 不调用
    assert "__interrupt__" not in result
    assert mock_adapter.execute_calls == 1  # adapter.execute 只调用一次，无 recursion 重复
    assert "compensate" in visited
    assert "memory_update" not in visited
    assert "escalate" not in visited
    assert result["verification_satisfied"] is False
