"""P0-8 correlation idempotency / 并发测试。"""

from __future__ import annotations

import asyncio

import pytest

from physical_agent.capability.request import CapabilityRequest
from physical_agent.execution.coordinator import DuplicateCorrelationError, ExecutionCoordinator
from physical_agent.policy.engine import PolicyDecision
from physical_agent.policy.risk import RiskTier


def test_coordinator_rejects_duplicate_correlation():
    coord = ExecutionCoordinator()
    req = CapabilityRequest(capability_id="home.climate.turn_off", correlation_id="dup1")
    decision = PolicyDecision(allowed=True, tier=RiskTier.LOW_REVERSIBLE, reason="ok",
                              requires_approval=False, correlation_id="dup1")
    coord.begin(req, decision)
    with pytest.raises(DuplicateCorrelationError):
        coord.begin(req, decision)


async def test_gateway_rejects_duplicate_correlation(gateway):
    req = CapabilityRequest(capability_id="home.climate.turn_off", correlation_id="dup2")
    first = await gateway.execute(req)
    assert first["status"] == "completed"
    second = await gateway.execute(req)  # 相同 correlation_id
    assert second["status"] == "rejected"
    assert "duplicate" in second["reason"]


async def test_concurrent_distinct_correlations(gateway):
    """并发不同 correlation_id → 各自独立，无覆盖。"""
    async def one(i: int):
        req = CapabilityRequest(capability_id="home.climate.turn_off", correlation_id=f"cc{i}")
        return await gateway.execute(req)

    # 3 个（在速率限制 3/min 内）
    results = await asyncio.gather(*[one(i) for i in range(3)])
    assert all(r["status"] == "completed" for r in results)


async def test_concurrent_same_correlation_only_one_succeeds(gateway):
    """并发相同 correlation_id → 只有一个成功（幂等）。"""
    reqs = [CapabilityRequest(capability_id="home.climate.turn_off", correlation_id="same")
            for _ in range(10)]

    async def one(req):
        return await gateway.execute(req)

    results = await asyncio.gather(*[one(r) for r in reqs])
    succeeded = [r for r in results if r["status"] == "completed"]
    rejected = [r for r in results if r["status"] == "rejected"]
    # 恰好一个成功，其余因重复 correlation 被拒绝
    assert len(succeeded) == 1
    assert len(rejected) == 9
    assert all("duplicate" in r["reason"] for r in rejected)
