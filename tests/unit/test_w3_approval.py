"""M1A-W3 Approval Lifecycle 测试：suspend / resume / 单次消费 / 防重放 / 精确绑定。

真实 LangGraph interrupt + checkpointer（InMemorySaver）+ Command(resume=...)。
复用 M0 ApprovalEngine（request_approval / grant / consume）。
Execute 一律 injected spy（无生产 side effect）。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from tests.mock_llm import MockReasoningModel

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
from physical_agent.memory.store import SqliteMemoryStore
from physical_agent.policy.approval import ApprovalEngine, ApprovalError
from physical_agent.policy.engine import PolicyEngine
from physical_agent.runtime.base import UserIntent
from physical_agent.runtime.graph import NodeHandlers, build_graph
from physical_agent.runtime.nodes import (
    make_human_review_handler,
    make_perceive_handler,
    make_plan_handler,
    make_policy_gate_handler,
    make_reason_handler,
    make_recall_handler,
)
from physical_agent.runtime.nodes.perceive import PerceptionSnapshot, WorldStateSource
from physical_agent.runtime.planning import PolicyRoute, ReasoningDecision, ReasoningRoute
from physical_agent.verification.evidence import VerificationEvidence


def _approval_registry() -> CapabilityRegistry:
    """climate set_temperature 在 risk=2（SIGNIFICANT）→ requires_approval，含 temperature 参数。"""
    reg = CapabilityRegistry()
    reg.register(CapabilityDefinition(
        id="home.climate.set_temperature",
        device_type="climate",
        parameters={"temperature": ParameterSpec(type="integer", minimum=16, maximum=30)},
        risk={"default": 2},
        side_effect=SideEffect.REVERSIBLE_WRITE,
        operation=Operation.EXECUTE,
    ))
    reg.register(CapabilityDefinition(
        id="home.climate.turn_on",
        device_type="climate",
        parameters={"temperature": ParameterSpec(type="integer", minimum=16, maximum=30)},
        risk={"default": 1},
        side_effect=SideEffect.REVERSIBLE_WRITE,
        operation=Operation.EXECUTE,
    ))
    return reg


class _InlineSource(WorldStateSource):
    def read_snapshot(self) -> PerceptionSnapshot:
        return PerceptionSnapshot(devices={"climate.bedroom_ac": {"state": "off"}}, environment={})


def _initial_state(**overrides):
    base = {
        "messages": [],
        "session_id": "s1",
        "correlation_id": "req-1",
        "intent": UserIntent(text="set temperature", principal="human", session_id="s1"),
    }
    base.update(overrides)
    return base


def _sim_verification() -> VerificationEvidence:
    return VerificationEvidence(
        correlation_id="req-1",
        capability_id="home.climate.set_temperature",
        level=VerificationLevel.V2,
        evidence={"provenance": "simulated"},
        physical_effect="confirmed",
    )


def _build_graph(policy_engine, approval_engine, decision, *, audit=None):
    model = MockReasoningModel([decision])
    store = SqliteMemoryStore(":memory:")
    visited: list[str] = []

    def execute(state):
        visited.append("execute")
        return {}

    def spy(name):
        def handler(state):
            visited.append(name)
            return {}

        return handler

    handlers = NodeHandlers(
        perceive=make_perceive_handler(_InlineSource()),
        recall=make_recall_handler(store),
        reason=make_reason_handler(model),
        plan=make_plan_handler(),
        policy_gate=make_policy_gate_handler(policy_engine, approval_engine, audit=audit),
        execute=execute,
        verify=lambda s: {"verification": _sim_verification()},
        compensate=spy("compensate"),
        memory_update=spy("memory_update"),
        escalate=spy("escalate"),
        human_review=make_human_review_handler(policy_engine, approval_engine, audit=audit),
    )
    graph = build_graph(handlers, checkpointer=InMemorySaver())
    return graph, visited


def _needs_approval_decision(**params) -> ReasoningDecision:
    return ReasoningDecision(
        route=ReasoningRoute.PLAN,
        capability_id="home.climate.set_temperature",
        device_id="climate.bedroom_ac",
        parameters={"temperature": 26, **params},
    )


def _approval_id(result) -> str:
    return result["__interrupt__"][0].value["approval_id"]


def _config(thread_id: str) -> dict:
    return {"configurable": {"thread_id": thread_id}}


# ---- needs approval → suspend ----

def test_needs_approval_suspends():
    reg = _approval_registry()
    pe = PolicyEngine(reg)
    ae = ApprovalEngine()
    graph, visited = _build_graph(pe, ae, _needs_approval_decision())
    result = graph.invoke(_initial_state(), _config("t-suspend"))

    assert "__interrupt__" in result
    assert result["policy_route"] is PolicyRoute.NEEDS_APPROVAL
    assert result["approval_id"] is not None
    assert result["canonical_request_hash"] is not None
    assert result["needs_human_review"] is True
    # 挂起后不得执行
    assert "execute" not in visited


# ---- approved resume → execute boundary once ----

def test_approved_resume_executes_once():
    reg = _approval_registry()
    pe = PolicyEngine(reg)
    ae = ApprovalEngine()
    graph, visited = _build_graph(pe, ae, _needs_approval_decision())
    config = _config("t-approve")

    r1 = graph.invoke(_initial_state(), config)
    approval_id = _approval_id(r1)
    ae.grant(approval_id, approver="owner")

    r2 = graph.invoke(Command(resume={"decision": "approve"}), config)
    assert r2["policy_route"] is PolicyRoute.APPROVED
    assert visited.count("execute") == 1  # 恰好一次


# ---- reject on resume → no execute ----

def test_reject_on_resume_no_execute():
    reg = _approval_registry()
    pe = PolicyEngine(reg)
    ae = ApprovalEngine()
    graph, visited = _build_graph(pe, ae, _needs_approval_decision())
    config = _config("t-reject")

    r1 = graph.invoke(_initial_state(), config)
    ae.grant(_approval_id(r1))

    r2 = graph.invoke(Command(resume={"decision": "reject"}), config)
    assert r2["policy_route"] is PolicyRoute.REJECTED
    assert "execute" not in visited


# ---- replay：单次消费，第二次 consume 拒绝 ----

def test_approval_replay_no_second_execute():
    reg = _approval_registry()
    pe = PolicyEngine(reg)
    ae = ApprovalEngine()
    graph, visited = _build_graph(pe, ae, _needs_approval_decision())
    config = _config("t-replay")

    r1 = graph.invoke(_initial_state(), config)
    approval_id = _approval_id(r1)
    ae.grant(approval_id)
    r2 = graph.invoke(Command(resume={"decision": "approve"}), config)
    assert visited.count("execute") == 1

    # grant 已被单次消费
    assert ae._grants[approval_id].is_consumed is True
    # 重放：同一 approval_id 再次 consume → 拒绝
    request = r2["current_request"]
    with pytest.raises(ApprovalError):
        ae.consume(approval_id, request, 2)
    assert visited.count("execute") == 1  # 无第二次 execute


def test_consumed_approval_resume_replay_no_second_execute():
    """REV2：真实 graph resume replay——同一已消费 approval 再次 resume 不得第二次 execute。

    在 human_review 挂起后、resume 前，将同一 approval 预先消费（模拟重放/并发攻击）。
    随后走真实 `Command(resume={"decision": "approve"})` 路径：human_review 内
    `ApprovalEngine.consume` 因 grant 已消费抛 ApprovalError → REJECTED，execute 零调用。
    """
    reg = _approval_registry()
    pe = PolicyEngine(reg)
    ae = ApprovalEngine()
    graph, visited = _build_graph(pe, ae, _needs_approval_decision())
    config = _config("t-replay-resume")

    r1 = graph.invoke(_initial_state(), config)
    approval_id = _approval_id(r1)
    ae.grant(approval_id)

    # 同一 approval 已被消费（重放攻击者在 resume 前抢先消费）
    request = r1["current_request"]
    tier = int(r1["policy_decision"].tier)
    ae.consume(approval_id, request, tier)  # 第一次消费成功

    # 真实 graph resume：consume 因已消费抛 ApprovalError → REJECTED → 无 execute
    r2 = graph.invoke(Command(resume={"decision": "approve"}), config)
    assert r2["policy_route"] is PolicyRoute.REJECTED
    assert "execute" not in visited  # 无第二次 execute
    assert ae._grants[approval_id].is_consumed is True


# ---- expired approval → no execute ----

def test_expired_approval_no_execute(monkeypatch):
    reg = _approval_registry()
    pe = PolicyEngine(reg)
    ae = ApprovalEngine(ttl_seconds=300)
    graph, visited = _build_graph(pe, ae, _needs_approval_decision())
    config = _config("t-expired")

    now = [datetime.now(UTC)]
    monkeypatch.setattr(ae, "_now", lambda: now[0])

    r1 = graph.invoke(_initial_state(), config)
    approval_id = _approval_id(r1)
    ae.grant(approval_id)
    # 时间越过 ttl
    now[0] = now[0] + timedelta(seconds=400)
    r2 = graph.invoke(Command(resume={"decision": "approve"}), config)
    assert r2["policy_route"] is PolicyRoute.REJECTED
    assert "execute" not in visited


# ---- mutated request / wrong binding → no execute ----

def test_mutated_parameters_no_execute():
    reg = _approval_registry()
    pe = PolicyEngine(reg)
    ae = ApprovalEngine()
    graph, visited = _build_graph(pe, ae, _needs_approval_decision())
    config = _config("t-mutate")

    r1 = graph.invoke(_initial_state(), config)
    approval_id = _approval_id(r1)
    ae.grant(approval_id)

    # resume 时 current_request 被篡改（temperature 26 → 18）
    mutated = CapabilityRequest(
        capability_id="home.climate.set_temperature",
        device_id="climate.bedroom_ac",
        parameters={"temperature": 18},
        principal="human",
        correlation_id="req-1",
    )
    r2 = graph.invoke(
        Command(resume={"decision": "approve"}, update={"current_request": mutated}),
        config,
    )
    assert r2["policy_route"] is PolicyRoute.REJECTED
    assert "execute" not in visited


def test_wrong_principal_no_execute():
    reg = _approval_registry()
    pe = PolicyEngine(reg)
    ae = ApprovalEngine()
    graph, visited = _build_graph(pe, ae, _needs_approval_decision())
    config = _config("t-principal")

    r1 = graph.invoke(_initial_state(), config)
    approval_id = _approval_id(r1)
    ae.grant(approval_id)

    mutated = CapabilityRequest(
        capability_id="home.climate.set_temperature",
        device_id="climate.bedroom_ac",
        parameters={"temperature": 26},
        principal="intruder",  # 换 principal
        correlation_id="req-1",
    )
    r2 = graph.invoke(
        Command(resume={"decision": "approve"}, update={"current_request": mutated}),
        config,
    )
    assert r2["policy_route"] is PolicyRoute.REJECTED
    assert "execute" not in visited


def test_wrong_device_no_execute():
    reg = _approval_registry()
    pe = PolicyEngine(reg)
    ae = ApprovalEngine()
    graph, visited = _build_graph(pe, ae, _needs_approval_decision())
    config = _config("t-device")

    r1 = graph.invoke(_initial_state(), config)
    approval_id = _approval_id(r1)
    ae.grant(approval_id)

    mutated = CapabilityRequest(
        capability_id="home.climate.set_temperature",
        device_id="climate.living_room_ac",  # 换 device
        parameters={"temperature": 26},
        principal="human",
        correlation_id="req-1",
    )
    r2 = graph.invoke(
        Command(resume={"decision": "approve"}, update={"current_request": mutated}),
        config,
    )
    assert r2["policy_route"] is PolicyRoute.REJECTED
    assert "execute" not in visited


def test_wrong_capability_no_execute():
    reg = _approval_registry()
    pe = PolicyEngine(reg)
    ae = ApprovalEngine()
    graph, visited = _build_graph(pe, ae, _needs_approval_decision())
    config = _config("t-capability")

    r1 = graph.invoke(_initial_state(), config)
    approval_id = _approval_id(r1)
    ae.grant(approval_id)

    mutated = CapabilityRequest(
        capability_id="home.climate.turn_on",  # 换 capability
        device_id="climate.bedroom_ac",
        parameters={"temperature": 26},
        principal="human",
        correlation_id="req-1",
    )
    r2 = graph.invoke(
        Command(resume={"decision": "approve"}, update={"current_request": mutated}),
        config,
    )
    assert r2["policy_route"] is PolicyRoute.REJECTED
    assert "execute" not in visited


def test_wrong_correlation_no_execute():
    reg = _approval_registry()
    pe = PolicyEngine(reg)
    ae = ApprovalEngine()
    graph, visited = _build_graph(pe, ae, _needs_approval_decision())
    config = _config("t-correlation")

    r1 = graph.invoke(_initial_state(), config)
    approval_id = _approval_id(r1)
    ae.grant(approval_id)

    mutated = CapabilityRequest(
        capability_id="home.climate.set_temperature",
        device_id="climate.bedroom_ac",
        parameters={"temperature": 26},
        principal="human",
        correlation_id="req-OTHER",  # 换 correlation
    )
    r2 = graph.invoke(
        Command(resume={"decision": "approve"}, update={"current_request": mutated}),
        config,
    )
    assert r2["policy_route"] is PolicyRoute.REJECTED
    assert "execute" not in visited


# ---- kill switch after grant → re-policy reject → no execute ----

def test_kill_switch_after_grant_no_execute(tmp_path):
    from physical_agent.policy.kill_switch import KillSwitch

    kill_switch = KillSwitch(kill_file=tmp_path / ".kill_switch")
    reg = _approval_registry()
    pe = PolicyEngine(reg, kill_switch)
    ae = ApprovalEngine()
    audit = AuditStore(path=tmp_path / "kill.jsonl")
    graph, visited = _build_graph(pe, ae, _needs_approval_decision(), audit=audit)
    config = _config("t-kill")

    r1 = graph.invoke(_initial_state(), config)
    approval_id = _approval_id(r1)
    ae.grant(approval_id)
    kill_switch.activate()  # grant 后打开 kill switch

    r2 = graph.invoke(Command(resume={"decision": "approve"}), config)
    assert r2["policy_route"] is PolicyRoute.REJECTED
    assert "execute" not in visited
    types = {e.event_type for e in audit.events()}
    assert "policy_rejected_after_approval" in types


# ---- 防御分支：resume 时缺失 canonical request / re-policy 异常 → fail-closed ----

def test_missing_canonical_request_on_resume_no_execute(tmp_path):
    reg = _approval_registry()
    pe = PolicyEngine(reg)
    ae = ApprovalEngine()
    audit = AuditStore(path=tmp_path / "no-req.jsonl")
    graph, visited = _build_graph(pe, ae, _needs_approval_decision(), audit=audit)
    config = _config("t-no-request")

    r1 = graph.invoke(_initial_state(), config)
    approval_id = _approval_id(r1)
    ae.grant(approval_id)

    r2 = graph.invoke(
        Command(resume={"decision": "approve"}, update={"current_request": None}),
        config,
    )
    assert r2["policy_route"] is PolicyRoute.REJECTED
    assert "execute" not in visited
    types = {e.event_type for e in audit.events()}
    assert "approval_rejected" in types


def test_re_policy_exception_on_resume_no_execute(monkeypatch, tmp_path):
    reg = _approval_registry()
    pe = PolicyEngine(reg)
    ae = ApprovalEngine()
    audit = AuditStore(path=tmp_path / "repolicy.jsonl")
    graph, visited = _build_graph(pe, ae, _needs_approval_decision(), audit=audit)
    config = _config("t-repolicy-exc")

    r1 = graph.invoke(_initial_state(), config)
    approval_id = _approval_id(r1)
    ae.grant(approval_id)

    def boom(request, context=None):
        raise RuntimeError("unexpected policy failure")

    monkeypatch.setattr(pe, "evaluate", boom)
    r2 = graph.invoke(Command(resume={"decision": "approve"}), config)
    assert r2["policy_route"] is PolicyRoute.REJECTED
    assert "execute" not in visited
    types = {e.event_type for e in audit.events()}
    assert "approval_rejected" in types


def test_reject_on_resume_with_audit(tmp_path):
    reg = _approval_registry()
    pe = PolicyEngine(reg)
    ae = ApprovalEngine()
    audit = AuditStore(path=tmp_path / "reject.jsonl")
    graph, visited = _build_graph(pe, ae, _needs_approval_decision(), audit=audit)
    config = _config("t-reject-audit")

    r1 = graph.invoke(_initial_state(), config)
    ae.grant(_approval_id(r1))
    r2 = graph.invoke(Command(resume={"decision": "reject"}), config)
    assert r2["policy_route"] is PolicyRoute.REJECTED
    assert "execute" not in visited
    types = {e.event_type for e in audit.events()}
    assert "approval_rejected" in types


def test_mutation_with_audit(tmp_path):
    reg = _approval_registry()
    pe = PolicyEngine(reg)
    ae = ApprovalEngine()
    audit = AuditStore(path=tmp_path / "mutate.jsonl")
    graph, visited = _build_graph(pe, ae, _needs_approval_decision(), audit=audit)
    config = _config("t-mutate-audit")

    r1 = graph.invoke(_initial_state(), config)
    approval_id = _approval_id(r1)
    ae.grant(approval_id)

    mutated = CapabilityRequest(
        capability_id="home.climate.set_temperature",
        device_id="climate.bedroom_ac",
        parameters={"temperature": 18},
        principal="human",
        correlation_id="req-1",
    )
    r2 = graph.invoke(
        Command(resume={"decision": "approve"}, update={"current_request": mutated}),
        config,
    )
    assert r2["policy_route"] is PolicyRoute.REJECTED
    assert "execute" not in visited
    types = {e.event_type for e in audit.events()}
    assert "approval_rejected" in types


# ---- audit：approval 生命周期 correlation_id 一致 ----

def test_approval_audit_events_correlation_consistent(tmp_path):
    reg = _approval_registry()
    pe = PolicyEngine(reg)
    ae = ApprovalEngine()
    audit = AuditStore(path=tmp_path / "approval.jsonl")
    graph, _ = _build_graph(pe, ae, _needs_approval_decision(), audit=audit)
    config = _config("t-audit")

    r1 = graph.invoke(_initial_state(correlation_id="req-42"), config)
    approval_id = _approval_id(r1)
    ae.grant(approval_id)
    graph.invoke(Command(resume={"decision": "approve"}), config)

    events = audit.events()
    assert all(e.correlation_id == "req-42" for e in events)
    types = {e.event_type for e in events}
    assert "policy_evaluated" in types
    assert "needs_approval" in types
    assert "approval_consumed" in types
