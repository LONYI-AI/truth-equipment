"""Policy Engine 与风险分级单元测试。"""

from __future__ import annotations

from physical_agent.capability.request import CapabilityRequest
from physical_agent.policy.risk import RiskContext, RiskTier, classify_risk


def test_classify_default_tier():
    tier, _ = classify_risk(default_tier=1, context=RiskContext())
    assert tier == RiskTier.LOW_REVERSIBLE


def test_rapid_cycling_escalates():
    tier, reason = classify_risk(
        default_tier=1, context=RiskContext(historical_state="rapid_cycling")
    )
    assert tier == RiskTier.SAFETY_SENSITIVE
    assert "rapid cycling" in reason


def test_away_significant_action_escalates():
    tier, _ = classify_risk(
        default_tier=2, context=RiskContext(occupancy="away")
    )
    assert tier == RiskTier.SAFETY_SENSITIVE


def test_normal_context_stays_low():
    tier, _ = classify_risk(default_tier=1, context=RiskContext(occupancy="occupied"))
    assert tier == RiskTier.LOW_REVERSIBLE


def test_policy_read_only_always_allowed(policy_engine):
    req = CapabilityRequest(
        capability_id="home.sensor.read_temperature",
        correlation_id="c1",
    )
    decision = policy_engine.evaluate(req)
    assert decision.allowed
    assert decision.tier == RiskTier.READ_ONLY


def test_policy_rejects_out_of_bounds(policy_engine):
    req = CapabilityRequest(
        capability_id="home.climate.turn_on",
        parameters={"temperature": 100},
        correlation_id="c2",
    )
    decision = policy_engine.evaluate(req)
    assert not decision.allowed
    assert "schema violation" in decision.reason


def test_policy_rejects_unknown_capability(policy_engine):
    import pytest

    from physical_agent.capability.registry import UnknownCapabilityError
    req = CapabilityRequest(capability_id="home.garage.open", correlation_id="c3")
    with pytest.raises(UnknownCapabilityError):
        policy_engine.evaluate(req)


def test_policy_tier3_requires_approval(policy_engine):
    req = CapabilityRequest(capability_id="home.lock.unlock", correlation_id="c4")
    decision = policy_engine.evaluate(req)
    assert decision.allowed
    assert decision.requires_approval
    assert decision.tier == RiskTier.SAFETY_SENSITIVE


def test_policy_tier1_no_approval(policy_engine):
    req = CapabilityRequest(
        capability_id="home.climate.turn_on",
        parameters={"temperature": 26, "mode": "cool"},
        correlation_id="c5",
    )
    decision = policy_engine.evaluate(req)
    assert decision.allowed
    assert not decision.requires_approval
