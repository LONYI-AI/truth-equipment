"""M1A-W3 Policy Gate 测试：canonical request + 复用 M0 PolicyEngine + typed route。

覆盖：
- unit：derive_policy_route / extract_canonical_request（PLAN / DIRECT / fail-closed）。
- 真实 graph.invoke：PLAN/DIRECT approved 到 execute boundary；rejected（temp=100、
  unknown capability、kill switch、rate limit）绝不 execute；stale-policy regression。
- Execute 一律是 injected spy（无生产 side effect）。
"""

from __future__ import annotations

import pytest
from tests.mock_llm import MockReasoningModel

from physical_agent.audit.store import AuditStore
from physical_agent.capability.request import CapabilityRequest
from physical_agent.capability.schema import VerificationLevel
from physical_agent.memory.store import SqliteMemoryStore
from physical_agent.policy.engine import PolicyDecision, PolicyEngine, RateLimiter
from physical_agent.policy.risk import RiskTier
from physical_agent.runtime.base import UserIntent
from physical_agent.runtime.graph import NodeHandlers, build_graph
from physical_agent.runtime.nodes import (
    derive_policy_route,
    extract_canonical_request,
    make_human_review_handler,
    make_perceive_handler,
    make_plan_handler,
    make_policy_gate_handler,
    make_reason_handler,
    make_recall_handler,
)
from physical_agent.runtime.nodes.perceive import PerceptionSnapshot, WorldStateSource
from physical_agent.runtime.nodes.policy_gate import PolicyGateError
from physical_agent.runtime.planning import (
    Plan,
    PolicyRoute,
    ReasoningDecision,
    ReasoningRoute,
)
from physical_agent.verification.evidence import VerificationEvidence


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


def _sim_verification(physical_effect: str = "confirmed") -> VerificationEvidence:
    return VerificationEvidence(
        correlation_id="req-1",
        capability_id="home.climate.turn_on",
        level=VerificationLevel.V2,
        evidence={"provenance": "simulated"},
        physical_effect=physical_effect,
    )


def _spy(name: str, sink: list[str]):
    def handler(state):
        sink.append(name)
        return {}

    return handler


def _execute_spy(sink: list[str]):
    def handler(state):
        sink.append("execute")
        return {}

    return handler


def _build_graph(policy_engine, approval_engine, decision, *, audit=None, checkpointer=None):
    """构建含真实 policy_gate / human_review 的图；execute 为 spy，verify 返回 confirmed。"""
    model = MockReasoningModel([decision])
    store = SqliteMemoryStore(":memory:")
    visited: list[str] = []

    handlers = NodeHandlers(
        perceive=make_perceive_handler(_InlineSource()),
        recall=make_recall_handler(store),
        reason=make_reason_handler(model),
        plan=make_plan_handler(),
        policy_gate=make_policy_gate_handler(policy_engine, approval_engine, audit=audit),
        execute=_execute_spy(visited),
        verify=lambda s: {"verification": _sim_verification("confirmed"), "verification_satisfied": True},
        compensate=_spy("compensate", visited),
        memory_update=_spy("memory_update", visited),
        escalate=_spy("escalate", visited),
        human_review=make_human_review_handler(policy_engine, approval_engine, audit=audit),
    )
    graph = build_graph(handlers, checkpointer=checkpointer)
    return graph, visited


# ---- unit：derive_policy_route ----

def test_derive_policy_route():
    approved = PolicyDecision(True, RiskTier.LOW_REVERSIBLE, "ok", False, "c1")
    needs = PolicyDecision(True, RiskTier.SAFETY_SENSITIVE, "ok", True, "c1")
    rejected = PolicyDecision(False, RiskTier.SAFETY_SENSITIVE, "no", False, "c1")
    assert derive_policy_route(approved) is PolicyRoute.APPROVED
    assert derive_policy_route(needs) is PolicyRoute.NEEDS_APPROVAL
    assert derive_policy_route(rejected) is PolicyRoute.REJECTED


# ---- unit：extract_canonical_request ----

def test_extract_canonical_request_plan():
    plan = Plan(
        session_id="s1",
        correlation_id="req-1",
        steps=[
            CapabilityRequest(
                capability_id="home.climate.turn_on",
                principal="human",
                correlation_id="req-1",
                parameters={"temperature": 26},
            )
        ],
    )
    req = extract_canonical_request({"route": ReasoningRoute.PLAN, "current_plan": plan, "correlation_id": "req-1"})
    assert req.capability_id == "home.climate.turn_on"
    assert req.parameters == {"temperature": 26}


def test_extract_canonical_request_plan_rejects_multiple_steps():
    plan = Plan(
        session_id="s1",
        correlation_id="req-1",
        steps=[
            CapabilityRequest(capability_id="a", principal="human", correlation_id="req-1"),
            CapabilityRequest(capability_id="b", principal="human", correlation_id="req-1"),
        ],
    )
    with pytest.raises(PolicyGateError):
        extract_canonical_request({"route": ReasoningRoute.PLAN, "current_plan": plan, "correlation_id": "req-1"})


def test_extract_canonical_request_plan_rejects_correlation_mismatch():
    plan = Plan(
        session_id="s1",
        correlation_id="req-old",
        steps=[CapabilityRequest(capability_id="a", principal="human", correlation_id="req-old")],
    )
    with pytest.raises(PolicyGateError):
        extract_canonical_request({"route": ReasoningRoute.PLAN, "current_plan": plan, "correlation_id": "req-1"})


def test_extract_canonical_request_direct_preserves_parameters():
    reasoning = ReasoningDecision(
        route=ReasoningRoute.DIRECT,
        capability_id="home.climate.set_temperature",
        device_id="climate.bedroom_ac",
        parameters={"temperature": 100},  # 不 clamp
        rationale="cool",
    )
    state = {
        "route": ReasoningRoute.DIRECT,
        "reasoning": reasoning,
        "correlation_id": "req-1",
        "intent": UserIntent(text="cool", principal="human", session_id="s1"),
    }
    req = extract_canonical_request(state)
    assert req.capability_id == "home.climate.set_temperature"
    assert req.device_id == "climate.bedroom_ac"
    assert req.parameters == {"temperature": 100}  # 原样透传
    assert req.principal == "human"
    assert req.correlation_id == "req-1"


def test_extract_canonical_request_noop_unreachable():
    with pytest.raises(PolicyGateError):
        extract_canonical_request({"route": ReasoningRoute.NOOP, "correlation_id": "req-1"})


def _plan_with_step(capability_id: str, principal: str) -> Plan:
    return Plan(
        session_id="s1",
        correlation_id="req-1",
        steps=[CapabilityRequest(capability_id=capability_id, principal=principal, correlation_id="req-1")],
    )


@pytest.mark.parametrize(
    "state",
    [
        # PLAN：current_plan 缺失
        {"route": ReasoningRoute.PLAN, "correlation_id": "req-1"},
        # PLAN：correlation_id 缺失
        {"route": ReasoningRoute.PLAN, "current_plan": _plan_with_step("a", "h")},
        # PLAN：step 缺 capability_id
        {"route": ReasoningRoute.PLAN, "correlation_id": "req-1",
         "current_plan": _plan_with_step("", "h")},
        # PLAN：step 缺 principal
        {"route": ReasoningRoute.PLAN, "correlation_id": "req-1",
         "current_plan": _plan_with_step("a", "")},
        # DIRECT：reasoning 缺失
        {"route": ReasoningRoute.DIRECT, "correlation_id": "req-1"},
        # DIRECT：reasoning.route 非 DIRECT
        {"route": ReasoningRoute.DIRECT, "correlation_id": "req-1",
         "reasoning": ReasoningDecision(route=ReasoningRoute.NOOP)},
        # DIRECT：correlation_id 缺失
        {"route": ReasoningRoute.DIRECT, "correlation_id": "",
         "reasoning": ReasoningDecision(route=ReasoningRoute.DIRECT, capability_id="a")},
        # DIRECT：intent 缺失 → 缺 principal
        {"route": ReasoningRoute.DIRECT, "correlation_id": "req-1",
         "reasoning": ReasoningDecision(route=ReasoningRoute.DIRECT, capability_id="a")},
    ],
)
def test_extract_canonical_request_fail_closed(state):
    with pytest.raises(PolicyGateError):
        extract_canonical_request(state)


# ---- 真实 graph：approved / rejected ----

def test_plan_approved_reaches_execute_boundary(registry, kill_switch):
    approval = registry.get("home.lock.unlock")  # noqa: F841 - ensure registry usable
    from physical_agent.policy.approval import ApprovalEngine

    pe = PolicyEngine(registry, kill_switch)
    ae = ApprovalEngine()
    decision = ReasoningDecision(
        route=ReasoningRoute.PLAN,
        capability_id="home.climate.turn_on",
        parameters={"temperature": 26},
    )
    graph, visited = _build_graph(pe, ae, decision)
    result = graph.invoke(_initial_state())
    assert result["policy_route"] is PolicyRoute.APPROVED
    assert "execute" in visited  # 到达 execute boundary
    assert isinstance(result["policy_decision"], PolicyDecision)


def test_direct_approved_reaches_execute_boundary(registry, kill_switch):
    from physical_agent.policy.approval import ApprovalEngine

    pe = PolicyEngine(registry, kill_switch)
    ae = ApprovalEngine()
    decision = ReasoningDecision(
        route=ReasoningRoute.DIRECT,
        capability_id="home.climate.turn_on",
        parameters={"temperature": 26},
    )
    graph, visited = _build_graph(pe, ae, decision)
    result = graph.invoke(_initial_state())
    assert result["policy_route"] is PolicyRoute.APPROVED
    assert "execute" in visited
    assert result["current_request"].capability_id == "home.climate.turn_on"


def test_plan_rejected_temperature_100_no_execute(registry, kill_switch):
    from physical_agent.policy.approval import ApprovalEngine

    pe = PolicyEngine(registry, kill_switch)
    ae = ApprovalEngine()
    decision = ReasoningDecision(
        route=ReasoningRoute.PLAN,
        capability_id="home.climate.set_temperature",
        parameters={"temperature": 100},  # 越界
    )
    graph, visited = _build_graph(pe, ae, decision)
    result = graph.invoke(_initial_state())
    assert result["policy_route"] is PolicyRoute.REJECTED
    assert "execute" not in visited
    # 参数未被修改（不 clamp）
    assert result["current_request"].parameters == {"temperature": 100}


def test_direct_rejected_unknown_capability_no_execute(registry, kill_switch):
    from physical_agent.policy.approval import ApprovalEngine

    pe = PolicyEngine(registry, kill_switch)
    ae = ApprovalEngine()
    decision = ReasoningDecision(
        route=ReasoningRoute.DIRECT,
        capability_id="home.unknown.thing",  # 未注册
    )
    graph, visited = _build_graph(pe, ae, decision)
    result = graph.invoke(_initial_state())
    assert result["policy_route"] is PolicyRoute.REJECTED
    assert "execute" not in visited


def test_kill_switch_rejects_no_execute(registry, kill_switch, tmp_path):
    from physical_agent.policy.approval import ApprovalEngine

    kill_switch.activate()  # touch kill file
    pe = PolicyEngine(registry, kill_switch)
    ae = ApprovalEngine()
    decision = ReasoningDecision(
        route=ReasoningRoute.DIRECT,
        capability_id="home.climate.turn_on",
        parameters={"temperature": 26},
    )
    graph, visited = _build_graph(pe, ae, decision)
    result = graph.invoke(_initial_state())
    assert result["policy_route"] is PolicyRoute.REJECTED
    assert "execute" not in visited


def test_rate_limit_rejects_no_execute(registry, kill_switch):
    from physical_agent.policy.approval import ApprovalEngine

    pe = PolicyEngine(registry, kill_switch, rate_limiter=RateLimiter(max_calls=1))
    ae = ApprovalEngine()
    decision = ReasoningDecision(
        route=ReasoningRoute.DIRECT,
        capability_id="home.climate.turn_on",
        parameters={"temperature": 26},
    )
    # 两张图共享同一 PolicyEngine（含 rate limiter），各自 fresh MockReasoningModel
    graph1, visited1 = _build_graph(pe, ae, decision)
    r1 = graph1.invoke(_initial_state(correlation_id="req-a"))
    assert r1["policy_route"] is PolicyRoute.APPROVED
    assert "execute" in visited1

    graph2, visited2 = _build_graph(pe, ae, decision)
    r2 = graph2.invoke(_initial_state(correlation_id="req-b"))
    assert r2["policy_route"] is PolicyRoute.REJECTED  # 第二次同 capability → 超限
    assert "execute" not in visited2


def test_stale_approved_current_reject_no_execute(registry, kill_switch):
    """stale-policy regression：初始注入旧 approved + 旧审批元数据，本轮 temp=100 必须 reject。"""
    from physical_agent.policy.approval import ApprovalEngine

    pe = PolicyEngine(registry, kill_switch)
    ae = ApprovalEngine()
    decision = ReasoningDecision(
        route=ReasoningRoute.PLAN,
        capability_id="home.climate.set_temperature",
        parameters={"temperature": 100},
    )
    graph, visited = _build_graph(pe, ae, decision)
    stale = _initial_state(
        policy_route=PolicyRoute.APPROVED,  # 旧 approved
        approval_id="apv_stale",
        canonical_request_hash="sha256:stale",
        needs_human_review=False,
    )
    result = graph.invoke(stale)
    assert result["policy_route"] is PolicyRoute.REJECTED
    assert "execute" not in visited
    # 旧审批元数据被无条件失效
    assert result["approval_id"] is None
    assert result["canonical_request_hash"] is None


# ---- audit：policy 生命周期事件 correlation_id 一致 ----

def test_policy_gate_handler_extract_failure_rejects(registry, kill_switch):
    """canonical request 提取失败（如 NOOP 到达 policy_gate）→ fail-closed REJECTED。"""
    from physical_agent.policy.approval import ApprovalEngine

    pe = PolicyEngine(registry, kill_switch)
    ae = ApprovalEngine()
    handler = make_policy_gate_handler(pe, ae)
    result = handler({"route": ReasoningRoute.NOOP, "correlation_id": "req-1"})
    assert result["policy_route"] is PolicyRoute.REJECTED
    assert result["approval_id"] is None
    assert result["canonical_request_hash"] is None


def test_extract_failure_invalidates_stale_approved_decision(registry, kill_switch):
    """REV2：canonical extraction failure 时，旧 approved decision / 旧 request 不得残留。

    初始 state 人为注入上一轮 approved PolicyDecision + 旧 canonical request +
    旧审批元数据，本轮 route 为不可达的 NOOP（触发 extraction fail-closed）。
    必须证明：policy_decision / current_request / approval_id /
    canonical_request_hash / needs_human_review 全部被无条件 invalidate。
    """
    from physical_agent.policy.approval import ApprovalEngine

    pe = PolicyEngine(registry, kill_switch)
    ae = ApprovalEngine()
    handler = make_policy_gate_handler(pe, ae)

    stale_decision = PolicyDecision(True, RiskTier.LOW_REVERSIBLE, "old approved", False, "req-1")
    stale_request = CapabilityRequest(
        capability_id="home.climate.turn_on",
        principal="human",
        correlation_id="req-1",
        parameters={"temperature": 26},
    )
    state = {
        "route": ReasoningRoute.NOOP,  # 触发 extraction fail-closed
        "correlation_id": "req-1",
        "policy_decision": stale_decision,  # 旧 approved
        "current_request": stale_request,  # 旧 canonical request
        "approval_id": "apv_stale",
        "canonical_request_hash": "sha256:stale",
        "needs_human_review": False,
    }
    result = handler(state)
    assert result["policy_route"] is PolicyRoute.REJECTED
    assert result["policy_decision"] is None  # 旧 approved 不残留
    assert result["current_request"] is None  # 旧 request 不残留
    assert result["approval_id"] is None
    assert result["canonical_request_hash"] is None
    assert result["needs_human_review"] is False


def test_evaluate_exception_invalidates_stale_approved_decision(registry, kill_switch, monkeypatch):
    """REV2：PolicyEngine.evaluate 异常时，旧 approved decision 不得残留。

    本轮 DIRECT reasoning 合法，但 evaluate 抛异常 → fail-closed REJECTED。
    必须证明旧 approved policy_decision / 旧 current_request / 旧审批元数据
    全部被无条件 invalidate，绝无旧授权复用。
    """
    from physical_agent.policy.approval import ApprovalEngine

    pe = PolicyEngine(registry, kill_switch)
    ae = ApprovalEngine()
    handler = make_policy_gate_handler(pe, ae)

    def boom(request, context=None):
        raise RuntimeError("unexpected policy engine failure")

    monkeypatch.setattr(pe, "evaluate", boom)

    stale_decision = PolicyDecision(True, RiskTier.LOW_REVERSIBLE, "old approved", False, "req-1")
    stale_request = CapabilityRequest(
        capability_id="home.climate.turn_on",
        principal="human",
        correlation_id="req-1",
        parameters={"temperature": 26},
    )
    state = {
        "route": ReasoningRoute.DIRECT,
        "reasoning": ReasoningDecision(
            route=ReasoningRoute.DIRECT,
            capability_id="home.climate.turn_on",
            parameters={"temperature": 26},
        ),
        "intent": UserIntent(text="turn on", principal="human", session_id="s1"),
        "correlation_id": "req-1",
        "policy_decision": stale_decision,  # 旧 approved
        "current_request": stale_request,  # 旧 canonical request
        "approval_id": "apv_stale",
        "canonical_request_hash": "sha256:stale",
        "needs_human_review": False,
    }
    result = handler(state)
    assert result["policy_route"] is PolicyRoute.REJECTED
    assert result["policy_decision"] is None  # 旧 approved 不残留
    assert result["current_request"] is None  # 旧 request 不残留
    assert result["approval_id"] is None
    assert result["canonical_request_hash"] is None
    assert result["needs_human_review"] is False


def test_unknown_capability_with_audit_fail_closed(registry, kill_switch, tmp_path):
    """未知 capability 触发 evaluate 异常，仍 fail-closed 并写审计。"""
    from physical_agent.policy.approval import ApprovalEngine

    audit = AuditStore(path=tmp_path / "w3-unknown.jsonl")
    pe = PolicyEngine(registry, kill_switch)
    ae = ApprovalEngine()
    decision = ReasoningDecision(
        route=ReasoningRoute.DIRECT,
        capability_id="home.unknown.thing",
    )
    graph, visited = _build_graph(pe, ae, decision, audit=audit)
    result = graph.invoke(_initial_state())
    assert result["policy_route"] is PolicyRoute.REJECTED
    assert "execute" not in visited
    types = {e.event_type for e in audit.events()}
    assert "policy_rejected" in types


def test_policy_audit_events_correlation_consistent(registry, kill_switch, tmp_path):
    from physical_agent.policy.approval import ApprovalEngine

    audit = AuditStore(path=tmp_path / "w3.jsonl")
    pe = PolicyEngine(registry, kill_switch)
    ae = ApprovalEngine()
    decision = ReasoningDecision(
        route=ReasoningRoute.PLAN,
        capability_id="home.climate.set_temperature",
        parameters={"temperature": 100},
    )
    graph, _ = _build_graph(pe, ae, decision, audit=audit)
    graph.invoke(_initial_state(correlation_id="req-42"))
    events = audit.events()
    assert events, "policy events should be recorded"
    assert all(e.correlation_id == "req-42" for e in events)
    types = {e.event_type for e in events}
    assert "policy_evaluated" in types
    assert "policy_rejected" in types
