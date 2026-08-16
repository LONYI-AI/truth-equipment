"""M1A-W2 REV2 状态模型测试：WorldState 类型/一致性 + AgentState schema。"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from physical_agent.runtime.planning import MemoryContext, Plan, ReasoningDecision, ReasoningRoute
from physical_agent.runtime.state import AgentState, WorldState
from physical_agent.verification.evidence import VerificationEvidence


def test_world_state_default_provenance_is_simulated():
    ws = WorldState()
    assert ws.provenance == "simulated"
    assert ws.source == "simulation"


def test_world_state_carries_devices_environment_and_freshness():
    ws = WorldState(
        devices={"climate.bedroom_ac": {"state": "off", "temperature": 28}},
        environment={"room": "bedroom"},
        observed_at=datetime(2026, 8, 16, 9, 0, 0, tzinfo=UTC),
        source="simulation",
        provenance="simulated",
    )
    assert ws.devices["climate.bedroom_ac"]["state"] == "off"
    assert ws.environment["room"] == "bedroom"
    assert ws.observed_at.tzinfo is not None  # timezone-aware


def test_world_state_observed_at_is_timezone_aware_by_default():
    ws = WorldState()
    assert ws.observed_at.tzinfo is not None
    assert ws.observed_at.utcoffset() is not None


def test_world_state_rejects_naive_observed_at():
    with pytest.raises(ValidationError):
        WorldState(observed_at=datetime(2026, 8, 16, 9, 0, 0))  # naive


def test_world_state_distinguishes_simulated_from_physical():
    simulated = WorldState(provenance="simulated")
    physical = WorldState(provenance="physical", source="physical")
    assert simulated.provenance == "simulated"
    assert physical.provenance == "physical"


def test_world_state_rejects_invalid_provenance():
    with pytest.raises(ValidationError):
        WorldState(provenance="simluated")  # 拼写错误
    with pytest.raises(ValidationError):
        WorldState(provenance="prod")
    with pytest.raises(ValidationError):
        WorldState(source="whatever")


def test_world_state_rejects_inconsistent_source_provenance():
    # simulation + physical provenance 必须被拒绝
    with pytest.raises(ValidationError):
        WorldState(source="simulation", provenance="physical")
    # physical + simulated provenance 必须被拒绝
    with pytest.raises(ValidationError):
        WorldState(source="physical", provenance="simulated")


def test_world_state_memory_source_allows_either_provenance():
    # memory 来源可承载 simulated 或 physical（不锁死未来 M1B+）
    assert WorldState(source="memory", provenance="simulated").provenance == "simulated"
    assert WorldState(source="memory", provenance="physical").provenance == "physical"


def test_agent_state_schema_has_architecture_fields():
    annotations = AgentState.__annotations__
    required = {
        "messages",
        "intent",
        "world_state",
        "memory_context",
        "reasoning",
        "current_plan",
        "execution_history",
        "verification",
        "session_id",
        "correlation_id",
        "retry_count",
        "needs_human_review",
        "approval_id",
        "canonical_request_hash",
        "route",
        "policy_verdict",
    }
    assert required <= set(annotations)


def test_agent_state_verification_uses_m0_verification_evidence():
    from typing import get_type_hints

    hints = get_type_hints(AgentState)
    assert hints["verification"] == VerificationEvidence | None


def test_agent_state_reuses_m0_and_w2_types():
    from typing import get_type_hints

    from physical_agent.runtime.base import UserIntent

    hints = get_type_hints(AgentState)
    assert hints["intent"] == UserIntent | None
    assert hints["memory_context"] == MemoryContext | None
    assert hints["reasoning"] == ReasoningDecision | None
    assert hints["current_plan"] == Plan | None
    assert hints["route"] == ReasoningRoute


def test_agent_state_routing_uses_typed_contract_not_bool():
    """W2 REV2：路由信号是 typed contract `route`，不再是 bool `has_plan`。"""
    annotations = AgentState.__annotations__
    assert "route" in annotations
    assert "has_plan" not in annotations


def test_agent_state_does_not_invent_acceptance_only_fields():
    annotations = AgentState.__annotations__
    assert "physical_execution_attempted" not in annotations
    assert "executed_request" not in annotations
