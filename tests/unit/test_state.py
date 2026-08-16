"""M1A-W1 REV2 状态模型测试：WorldState provenance 类型 + AgentState schema。"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

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
        observed_at="2026-08-16T09:00:00Z",
        source="simulation",
        provenance="simulated",
    )
    assert ws.devices["climate.bedroom_ac"]["state"] == "off"
    assert ws.environment["room"] == "bedroom"
    assert ws.observed_at != ""  # freshness 时间戳存在


def test_world_state_distinguishes_simulated_from_physical():
    """source/provenance 用显式 Literal，区分模拟状态与物理状态（W0.1 SIMULATED 语义）。"""
    simulated = WorldState(provenance="simulated")
    physical = WorldState(provenance="physical", source="physical")
    assert simulated.provenance == "simulated"
    assert physical.provenance == "physical"
    assert simulated.provenance != physical.provenance


def test_world_state_rejects_invalid_provenance():
    """provenance/source 是有限集合类型，拼写错误或任意字符串必须被拒绝。"""
    with pytest.raises(ValidationError):
        WorldState(provenance="simluated")  # 拼写错误
    with pytest.raises(ValidationError):
        WorldState(provenance="prod")
    with pytest.raises(ValidationError):
        WorldState(source="whatever")


def test_agent_state_schema_has_architecture_fields():
    annotations = AgentState.__annotations__
    required = {
        "messages",
        "world_state",
        "current_plan",
        "execution_history",
        "verification",
        "session_id",
        "correlation_id",
        "retry_count",
        "needs_human_review",
        # 审批挂起边界元数据（兼容 M0 ApprovalRequest）
        "approval_id",
        "canonical_request_hash",
        # 已论证的 graph 路由信号
        "has_plan",
        "policy_verdict",
    }
    assert required <= set(annotations)


def test_agent_state_verification_uses_m0_verification_evidence():
    """verification 复用 M0 冻结的 VerificationEvidence，不另造第二个 verification schema。"""
    from typing import get_type_hints

    hints = get_type_hints(AgentState)
    assert hints["verification"] == VerificationEvidence | None


def test_agent_state_does_not_invent_acceptance_only_fields():
    annotations = AgentState.__annotations__
    assert "physical_execution_attempted" not in annotations
    assert "executed_request" not in annotations
