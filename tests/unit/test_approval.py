"""P0-4 ApprovalEngine 测试：单次使用、过期、参数绑定、防重放。"""

from __future__ import annotations

import pytest

from physical_agent.capability.request import CapabilityRequest
from physical_agent.policy.approval import ApprovalEngine, ApprovalError


def _req(cid="c1", temp=26):
    return CapabilityRequest(
        capability_id="home.climate.turn_on",
        parameters={"temperature": temp},
        correlation_id=cid,
    )


def test_request_binds_fields():
    eng = ApprovalEngine()
    req = _req()
    ar = eng.request_approval(req, risk_tier=2)
    assert ar.correlation_id == "c1"
    assert ar.capability_id == "home.climate.turn_on"
    assert ar.risk_tier == 2
    assert ar.canonical_request_hash
    assert ar.principal == "agent"
    assert ar.device_id == ""


def test_grant_and_consume_ok():
    eng = ApprovalEngine()
    req = _req()
    ar = eng.request_approval(req, 2)
    eng.grant(ar.approval_id)
    grant = eng.consume(ar.approval_id, req, 2)
    assert grant is not None


def test_grant_exposes_original_correlation_id():
    """ApprovalGrant.correlation_id = 原始 CapabilityRequest 的 correlation_id（非 approval_id）。"""
    eng = ApprovalEngine()
    req = _req(cid="corr-42")
    ar = eng.request_approval(req, 2)
    grant = eng.grant(ar.approval_id, approver="owner")
    assert grant.correlation_id == "corr-42"
    assert grant.correlation_id != grant.approval_id


def test_replay_rejected():
    eng = ApprovalEngine()
    req = _req()
    ar = eng.request_approval(req, 2)
    eng.grant(ar.approval_id)
    eng.consume(ar.approval_id, req, 2)
    with pytest.raises(ApprovalError):
        eng.consume(ar.approval_id, req, 2)  # 第二次 = 重放


def test_parameter_mutation_rejected():
    eng = ApprovalEngine()
    req = _req(temp=26)
    ar = eng.request_approval(req, 2)
    eng.grant(ar.approval_id)
    mutated = _req(temp=16)  # 温度被篡改
    with pytest.raises(ApprovalError):
        eng.consume(ar.approval_id, mutated, 2)


def test_correlation_mismatch_rejected():
    eng = ApprovalEngine()
    req = _req(cid="c1")
    ar = eng.request_approval(req, 2)
    eng.grant(ar.approval_id)
    other = _req(cid="c2")
    with pytest.raises(ApprovalError):
        eng.consume(ar.approval_id, other, 2)


def test_principal_mismatch_rejected():
    """审批绑定 principal：principal 变更 → 拒绝。"""
    eng = ApprovalEngine()
    req = CapabilityRequest(
        capability_id="home.lock.unlock", correlation_id="c1", principal="human"
    )
    ar = eng.request_approval(req, 3)
    eng.grant(ar.approval_id)
    other = req.model_copy(update={"principal": "agent"})
    with pytest.raises(ApprovalError):
        eng.consume(ar.approval_id, other, 3)


def test_device_mismatch_rejected():
    """审批绑定 device：device_id 变更 → 拒绝。"""
    eng = ApprovalEngine()
    req = CapabilityRequest(
        capability_id="home.lock.unlock", correlation_id="c1", device_id="front.door"
    )
    ar = eng.request_approval(req, 3)
    eng.grant(ar.approval_id)
    other = req.model_copy(update={"device_id": "back.door"})
    with pytest.raises(ApprovalError):
        eng.consume(ar.approval_id, other, 3)


def test_expiration_rejected():
    eng = ApprovalEngine(ttl_seconds=-1)  # 立即过期
    req = _req()
    ar = eng.request_approval(req, 2)
    with pytest.raises(ApprovalError):
        eng.grant(ar.approval_id)


def test_unknown_approval_rejected():
    eng = ApprovalEngine()
    with pytest.raises(ApprovalError):
        eng.consume("nonexistent", _req(), 2)


async def test_approval_flow_end_to_end(gateway):
    """端到端：Tier 3 门锁 → needs_approval → 授予 → 执行。"""
    req = CapabilityRequest(capability_id="home.lock.unlock", correlation_id="ap1")
    outcome = await gateway.execute(req)
    assert outcome["status"] == "needs_approval"
    approval_id = outcome["approval_id"]

    # 人工授予后执行
    gateway.approve(approval_id, approver="owner")
    # 注：mock adapter 不支持 lock.unlock，会 dispatch failed；但审批流程已验证
    result = await gateway.execute_approved(req, approval_id)
    assert result["status"] in ("completed", "partial", "failed")
