"""Policy Engine：确定性的策略闸门（v3.0 §18）。不依赖 LLM。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from physical_agent.capability.registry import CapabilityRegistry
from physical_agent.capability.request import CapabilityRequest
from physical_agent.policy.kill_switch import KillSwitch
from physical_agent.policy.risk import RiskContext, RiskTier, classify_risk


class PolicyDeniedError(Exception):
    """策略拒绝。"""


@dataclass
class PolicyDecision:
    """一次策略判定的结果。"""

    allowed: bool
    tier: RiskTier
    reason: str
    requires_approval: bool
    correlation_id: str
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def __repr__(self) -> str:  # pragma: no cover - convenience
        return (
            f"PolicyDecision(allowed={self.allowed}, tier={self.tier.name}, "
            f"reason={self.reason!r}, requires_approval={self.requires_approval})"
        )


class RateLimiter:
    """滑动窗口速率限制（确定性）。"""

    def __init__(self, max_calls: int = 3, window_seconds: float = 60.0) -> None:
        self.max_calls = max_calls
        self.window_seconds = window_seconds
        self._events: dict[str, list[float]] = {}

    def _now(self) -> float:
        return datetime.now(UTC).timestamp()

    def check(self, key: str) -> bool:
        """返回是否放行（未超限）。"""
        now = self._now()
        window = self._events.setdefault(key, [])
        window[:] = [t for t in window if now - t <= self.window_seconds]
        if len(window) >= self.max_calls:
            return False
        window.append(now)
        return True


class PolicyEngine:
    """确定性策略引擎。

    校验顺序（v3.0 §15/§18）：
    1. Kill switch
    2. capability 注册（allowlist）
    3. schema / 参数边界
    4. 速率限制
    5. 上下文风险分级
    """

    def __init__(
        self,
        registry: CapabilityRegistry,
        kill_switch: KillSwitch | None = None,
        rate_limiter: RateLimiter | None = None,
    ) -> None:
        self.registry = registry
        self.kill_switch = kill_switch or KillSwitch()
        self.rate_limiter = rate_limiter or RateLimiter()

    @property
    def is_policy_loaded(self) -> bool:
        """policy 是否已加载（registry 非空）。M0.1 P0-3 安全栈健康检查用。"""
        return bool(self.registry.list())

    def evaluate(
        self,
        request: CapabilityRequest,
        context: RiskContext | None = None,
    ) -> PolicyDecision:
        context = context or RiskContext()

        # 1. kill switch（只读除外，P0-9：只读用 side_effect 判定，非 risk tier）
        definition = self.registry.get(request.capability_id)  # 抛 UnknownCapabilityError
        is_read_only = definition.is_read_only

        if not is_read_only:
            # 紧急停止（kill file）与组件级 kill 在所有模式生效；
            # 环境变量 AGENT_EXECUTION_ENABLED 属 physical 写闸门（WriteGate），
            # 由 gateway 在 PHYSICAL 模式下校验，不在此处阻断 simulation。
            if self.kill_switch.is_kill_file_active:
                return PolicyDecision(
                    allowed=False,
                    tier=RiskTier.SAFETY_SENSITIVE,
                    reason="kill switch active",
                    requires_approval=False,
                    correlation_id=request.correlation_id,
                )
            if self.kill_switch.is_killed(request.capability_id):
                return PolicyDecision(
                    allowed=False,
                    tier=RiskTier.SAFETY_SENSITIVE,
                    reason=f"capability {request.capability_id!r} killed",
                    requires_approval=False,
                    correlation_id=request.correlation_id,
                )

            # A compressor protection signal is a present safety constraint,
            # not merely a reason to request another approval.
            if context.historical_state == "rapid_cycling":
                return PolicyDecision(
                    allowed=False,
                    tier=RiskTier.SAFETY_SENSITIVE,
                    reason="rapid cycling detected",
                    requires_approval=False,
                    correlation_id=request.correlation_id,
                )

        # 2. schema / 参数边界（fail-closed：未知参数拒绝）
        errors = definition.validate_parameters(request.parameters)
        if errors:
            return PolicyDecision(
                allowed=False,
                tier=RiskTier.SAFETY_SENSITIVE,
                reason=f"schema violation: {errors}",
                requires_approval=False,
                correlation_id=request.correlation_id,
            )

        # 3. 速率限制
        if not is_read_only and not self.rate_limiter.check(request.capability_id):
            return PolicyDecision(
                allowed=False,
                tier=RiskTier.SAFETY_SENSITIVE,
                reason="rate limit exceeded",
                requires_approval=False,
                correlation_id=request.correlation_id,
            )

        # 4. 上下文风险分级
        ctx = RiskContext(
            principal=request.principal,
            device=definition.device_type,
            capability_id=request.capability_id,
            parameters=request.parameters,
            location=context.location,
            time_of_day=context.time_of_day,
            occupancy=context.occupancy,
            historical_state=context.historical_state,
            environment=context.environment,
        )
        tier, reason = classify_risk(default_tier=definition.default_risk_tier, context=ctx)

        requires_approval = tier >= RiskTier.SIGNIFICANT
        return PolicyDecision(
            allowed=True,
            tier=tier,
            reason=reason,
            requires_approval=requires_approval,
            correlation_id=request.correlation_id,
        )
