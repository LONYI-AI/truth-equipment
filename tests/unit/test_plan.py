"""M1A-W2 Plan 节点测试：ReasoningDecision → structured Plan（复用 CapabilityRequest）。"""

from __future__ import annotations

import ast
import inspect

import pytest

from physical_agent.capability.request import CapabilityRequest
from physical_agent.runtime.base import UserIntent
from physical_agent.runtime.nodes.plan import PlanError, make_plan_handler
from physical_agent.runtime.planning import Plan, ReasoningDecision, ReasoningRoute


def _decision(**kw) -> ReasoningDecision:
    base = dict(
        route=ReasoningRoute.PLAN,
        capability_id="home.climate.turn_on",
        device_id="climate.bedroom_ac",
        parameters={"temperature": 26, "mode": "cool"},
        rationale="用户想开空调",
    )
    base.update(kw)
    return ReasoningDecision(**base)


def _state(**kw):
    base = {
        "session_id": "s1",
        "correlation_id": "c1",
        "intent": UserIntent(text="打开空调到26度", principal="human", session_id="s1"),
    }
    base.update(kw)
    return base


def test_plan_produces_structured_plan():
    handler = make_plan_handler()
    result = handler({"reasoning": _decision(), **_state()})
    plan = result["current_plan"]
    assert isinstance(plan, Plan)
    assert len(plan.steps) == 1


def test_plan_steps_use_real_capability_request():
    handler = make_plan_handler()
    plan = handler({"reasoning": _decision(), **_state()})["current_plan"]
    assert isinstance(plan.steps[0], CapabilityRequest)
    assert plan.steps[0].capability_id == "home.climate.turn_on"


def test_plan_preserves_correlation_id():
    handler = make_plan_handler()
    plan = handler({"reasoning": _decision(), **_state(correlation_id="req_abc123")})["current_plan"]
    assert plan.correlation_id == "req_abc123"
    assert plan.steps[0].correlation_id == "req_abc123"


def test_plan_preserves_principal():
    handler = make_plan_handler()
    state = _state(intent=UserIntent(text="x", principal="owner", session_id="s1"))
    plan = handler({"reasoning": _decision(), **state})["current_plan"]
    assert plan.steps[0].principal == "owner"


def test_plan_preserves_device_capability_parameters():
    handler = make_plan_handler()
    plan = handler({"reasoning": _decision(), **_state()})["current_plan"]
    step = plan.steps[0]
    assert step.device_id == "climate.bedroom_ac"
    assert step.capability_id == "home.climate.turn_on"
    assert step.parameters == {"temperature": 26, "mode": "cool"}


def test_plan_does_not_clamp_out_of_bounds_temperature():
    """temperature=100 原样透传，不 silent clamp（参数合法性属 Policy Gate）。"""
    handler = make_plan_handler()
    plan = handler({"reasoning": _decision(parameters={"temperature": 100}), **_state()})["current_plan"]
    assert plan.steps[0].parameters["temperature"] == 100


def test_plan_uses_reasoning_rationale_as_reason():
    handler = make_plan_handler()
    plan = handler({"reasoning": _decision(rationale="降温需求"), **_state()})["current_plan"]
    assert plan.steps[0].reason == "降温需求"


def test_plan_non_actionable_returns_no_plan():
    """防御性兜底：NOOP 决策不产出 plan（正常路径中 NOOP 在 Reason 边界已终态）。"""
    handler = make_plan_handler()
    result = handler({"reasoning": ReasoningDecision(route=ReasoningRoute.NOOP), **_state()})
    assert result["current_plan"] is None


def test_plan_missing_reasoning_fails_closed():
    handler = make_plan_handler()
    with pytest.raises(PlanError):
        handler({**_state()})


def test_plan_missing_correlation_id_fails_closed():
    handler = make_plan_handler()
    with pytest.raises(PlanError):
        handler({"reasoning": _decision(), **_state(correlation_id="")})


def test_plan_missing_principal_fails_closed():
    handler = make_plan_handler()
    # 无 intent → 无 principal
    with pytest.raises(PlanError):
        handler({"reasoning": _decision(), **_state(intent=None)})


def test_plan_has_no_forbidden_imports():
    import physical_agent.runtime.nodes.plan as mod

    forbidden = ("physical_agent.execution", "physical_agent.safety.gateway", "physical_agent.policy.approval")
    for node in ast.walk(ast.parse(inspect.getsource(mod))):
        if isinstance(node, ast.ImportFrom) and node.module:
            assert node.module not in forbidden
        elif isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name not in forbidden
