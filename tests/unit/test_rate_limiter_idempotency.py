"""P0-1 regression：RateLimiter 幂等准入（request/correlation-aware）。

证明：
- 同 capability + 同 correlation_id 的 re-policy 幂等放行且只占一个 slot；
- 不同 correlation_id 正常受限；
- 不存在 consume_rate_limit 之类 public bypass。
"""

from __future__ import annotations

import inspect

from physical_agent.capability.request import CapabilityRequest
from physical_agent.policy.engine import PolicyEngine, RateLimiter


def test_rate_limiter_idempotent_same_correlation():
    rl = RateLimiter(max_calls=1)
    assert rl.check("home.climate.turn_on", "corr-1") is True  # 初次准入，占 1 slot
    assert rl.check("home.climate.turn_on", "corr-1") is True  # 同 correlation 幂等，不重复计数
    assert rl.check("home.climate.turn_on", "corr-2") is False  # 不同 correlation → 超限拒绝


def test_rate_limiter_different_correlation_normal_limit():
    rl = RateLimiter(max_calls=2)
    assert rl.check("cap", "c1") is True
    assert rl.check("cap", "c2") is True
    assert rl.check("cap", "c3") is False  # 第 3 个不同 correlation → 超限


def test_no_consume_rate_limit_bypass_param():
    """PolicyEngine.evaluate 不得暴露 consume_rate_limit 之类的 boolean bypass。"""
    sig = inspect.signature(PolicyEngine.evaluate)
    assert "consume_rate_limit" not in sig.parameters


def test_policy_engine_evaluate_idempotent_same_request(registry, kill_switch):
    """同 request（同 correlation）初次 evaluate + resume re-evaluate 均允许，只占一个 slot。"""
    pe = PolicyEngine(registry, kill_switch, rate_limiter=RateLimiter(max_calls=1))
    req = CapabilityRequest(
        capability_id="home.climate.turn_on",
        parameters={"temperature": 26},
        correlation_id="corr-a",
        principal="human",
    )
    assert pe.evaluate(req).allowed is True  # 初次准入
    assert pe.evaluate(req).allowed is True  # resume re-evaluate（同 correlation）幂等允许


def test_policy_engine_evaluate_second_correlation_rejected(registry, kill_switch):
    """第二个不同 correlation_id 的请求正常受限（不被幂等放行）。"""
    pe = PolicyEngine(registry, kill_switch, rate_limiter=RateLimiter(max_calls=1))
    first = CapabilityRequest(
        capability_id="home.climate.turn_on",
        parameters={"temperature": 26},
        correlation_id="corr-a",
        principal="human",
    )
    assert pe.evaluate(first).allowed is True

    second = CapabilityRequest(
        capability_id="home.climate.turn_on",
        parameters={"temperature": 26},
        correlation_id="corr-b",
        principal="human",
    )
    decision = pe.evaluate(second)
    assert decision.allowed is False
    assert "rate limit" in decision.reason
