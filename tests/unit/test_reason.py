"""M1A-W2 Reason 节点测试：injectable ReasoningModel → ReasoningDecision（确定性）。"""

from __future__ import annotations

import ast
import inspect

import pytest
from pydantic import ValidationError
from tests.mock_llm import MockReasoningModel

from physical_agent.runtime.base import UserIntent
from physical_agent.runtime.nodes.reason import make_reason_handler
from physical_agent.runtime.planning import (
    MemoryContext,
    ReasoningDecision,
    ReasoningRoute,
)
from physical_agent.runtime.state import WorldState


def _world_state() -> WorldState:
    return WorldState(devices={"climate.bedroom_ac": {"state": "off"}}, environment={"room_temperature": 28})


def _memory_context() -> MemoryContext:
    return MemoryContext(events=[{"event_type": "e0"}], preferences={"preferred_temperature": 26})


def test_reason_passes_world_state_to_model():
    model = MockReasoningModel()
    handler = make_reason_handler(model)
    handler({"messages": [], "world_state": _world_state(), "memory_context": _memory_context()})
    assert model.calls[0]["world_state"] is not None
    assert model.calls[0]["world_state"].environment["room_temperature"] == 28


def test_reason_passes_memory_context_to_model():
    model = MockReasoningModel()
    handler = make_reason_handler(model)
    handler({"messages": [], "world_state": _world_state(), "memory_context": _memory_context()})
    assert model.calls[0]["memory_context"].preferences == {"preferred_temperature": 26}


def test_reason_is_deterministic():
    """确定性输入 → 确定性 ReasoningDecision（Mock 预定义响应序列）。"""
    decision = ReasoningDecision(route=ReasoningRoute.PLAN, capability_id="home.climate.turn_on", rationale="r")
    model = MockReasoningModel([decision])
    handler = make_reason_handler(model)
    r1 = handler({"messages": [], "world_state": _world_state()})
    assert r1["reasoning"] == decision
    assert r1["route"] is ReasoningRoute.PLAN


def test_reason_planned_route_signal():
    """actionable（PLAN）→ typed 路由信号 route=PLAN，而非单一 bool。"""
    model = MockReasoningModel([ReasoningDecision(route=ReasoningRoute.PLAN, capability_id="home.climate.turn_on")])
    handler = make_reason_handler(model)
    result = handler({"messages": [], "world_state": _world_state()})
    assert result["route"] is ReasoningRoute.PLAN


def test_reason_direct_route_signal():
    """actionable（DIRECT）→ route=DIRECT，与「需要 plan」区分开。"""
    model = MockReasoningModel([ReasoningDecision(route=ReasoningRoute.DIRECT, capability_id="home.climate.turn_on")])
    handler = make_reason_handler(model)
    result = handler({"messages": [], "world_state": _world_state()})
    assert result["route"] is ReasoningRoute.DIRECT


def test_reason_non_actionable_produces_noop_route_signal():
    model = MockReasoningModel([ReasoningDecision(route=ReasoningRoute.NOOP, rationale="nothing to do")])
    handler = make_reason_handler(model)
    result = handler({"messages": [], "world_state": _world_state()})
    assert result["reasoning"].route is ReasoningRoute.NOOP
    assert result["reasoning"].capability_id is None
    assert result["route"] is ReasoningRoute.NOOP


@pytest.mark.parametrize(
    "route,capability_id",
    [
        (ReasoningRoute.PLAN, "home.climate.turn_on"),
        (ReasoningRoute.DIRECT, "home.climate.turn_on"),
        (ReasoningRoute.NOOP, None),
    ],
)
def test_reason_invalidates_prior_plan_for_every_route(route, capability_id):
    """stale-plan lifecycle invariant：每轮 ReasoningDecision 无条件 invalidate prior plan。

    覆盖 PLAN / DIRECT / NOOP 三态——旧 current_plan 均不得越过 Reason 边界。
    """
    decision = ReasoningDecision(route=route, capability_id=capability_id)
    model = MockReasoningModel([decision])
    handler = make_reason_handler(model)
    result = handler({"messages": [], "current_plan": {"stale": True}})
    assert result["current_plan"] is None
    assert result["route"] is route
    assert result["reasoning"] == decision


def test_reasoning_decision_plan_requires_capability_id():
    with pytest.raises(ValidationError):
        ReasoningDecision(route=ReasoningRoute.PLAN, capability_id=None)


def test_reasoning_decision_direct_requires_capability_id():
    with pytest.raises(ValidationError):
        ReasoningDecision(route=ReasoningRoute.DIRECT, capability_id=None)


def test_reasoning_decision_noop_rejects_capability_id():
    with pytest.raises(ValidationError):
        ReasoningDecision(route=ReasoningRoute.NOOP, capability_id="home.climate.turn_on")


def test_reason_does_not_clamp_parameters():
    """Reason 只提议，不 clamp 越界参数（temperature=100 原样保留）。"""
    decision = ReasoningDecision(
        route=ReasoningRoute.PLAN,
        capability_id="home.climate.turn_on",
        parameters={"temperature": 100},
    )
    assert decision.parameters["temperature"] == 100  # 不 clamp


def test_reason_has_no_forbidden_imports():
    import physical_agent.runtime.nodes.reason as mod

    forbidden = ("physical_agent.execution", "physical_agent.safety.gateway", "physical_agent.policy.approval")
    for node in ast.walk(ast.parse(inspect.getsource(mod))):
        if isinstance(node, ast.ImportFrom) and node.module:
            assert node.module not in forbidden
        elif isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name not in forbidden


def test_reason_handler_uses_injected_intent():
    model = MockReasoningModel()
    handler = make_reason_handler(model)
    intent = UserIntent(text="打开空调", principal="human", session_id="s1")
    handler({"messages": [], "intent": intent, "world_state": _world_state()})
    assert model.calls[0]["intent"].text == "打开空调"
