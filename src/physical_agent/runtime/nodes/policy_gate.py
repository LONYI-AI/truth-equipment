"""M1A-W3 Policy Gate 节点：canonical request → 复用 M0 PolicyEngine 确定性判定。

设计约束（W3 授权）：
- **复用 M0** `PolicyEngine` / `ApprovalEngine` / `AuditStore`，不重建第二套 policy/approval。
- Policy route 用 typed contract `PolicyRoute`，由本轮真实 `PolicyDecision` 确定性派生。
- 只处理**一个明确的本轮 `CapabilityRequest`**（PLAN → `current_plan.steps`；DIRECT → reasoning）。
- **stale-policy invariant**：每次 policy_gate 调用无条件 invalidate 上一轮 policy/approval 授权状态。
- 任何 missing / unknown / exception / malformed / inconsistent → fail-closed（REJECTED），绝不进入 execute。
"""

from __future__ import annotations

from typing import Any

from physical_agent.audit.store import AuditStore
from physical_agent.capability.request import CapabilityRequest
from physical_agent.policy.approval import ApprovalEngine
from physical_agent.policy.engine import PolicyDecision, PolicyEngine
from physical_agent.policy.risk import RiskContext
from physical_agent.runtime.graph import NodeHandler
from physical_agent.runtime.planning import PolicyRoute, ReasoningRoute
from physical_agent.runtime.state import AgentState


class PolicyGateError(ValueError):
    """Policy Gate 无法确定唯一 canonical request（fail-closed）。"""


def derive_policy_route(decision: PolicyDecision) -> PolicyRoute:
    """由本轮真实 M0 `PolicyDecision` 确定性派生 `PolicyRoute`（非 LLM、非字符串）。"""
    if not decision.allowed:
        return PolicyRoute.REJECTED
    if decision.requires_approval:
        return PolicyRoute.NEEDS_APPROVAL
    return PolicyRoute.APPROVED


def extract_canonical_request(state: AgentState) -> CapabilityRequest:
    """确定本轮唯一 canonical CapabilityRequest。

    - PLAN   → `current_plan.steps` 必须恰有 1 个 step，且 correlation_id 与本轮一致。
    - DIRECT → 由本轮 `ReasoningDecision` 确定性转换为 M0 CapabilityRequest（参数原样透传）。
    - 其他 / 缺失 / 矛盾 → raise PolicyGateError（fail-closed）。
    """
    route = state.get("route")
    correlation_id = state.get("correlation_id", "")

    if route == ReasoningRoute.PLAN:
        plan = state.get("current_plan")
        if plan is None or len(plan.steps) != 1:
            raise PolicyGateError("PLAN requires exactly one current_plan.step")
        step = plan.steps[0]
        if not correlation_id:
            raise PolicyGateError("PLAN requires correlation_id")
        if plan.correlation_id != correlation_id or step.correlation_id != correlation_id:
            raise PolicyGateError("current_plan correlation_id mismatch with this round")
        if not step.capability_id:
            raise PolicyGateError("current_plan.step missing capability_id")
        if not step.principal:
            raise PolicyGateError("current_plan.step missing principal")
        return step

    if route == ReasoningRoute.DIRECT:
        reasoning = state.get("reasoning")
        if reasoning is None or reasoning.route != ReasoningRoute.DIRECT:
            raise PolicyGateError("DIRECT requires this round's ReasoningDecision")
        if not reasoning.capability_id:
            raise PolicyGateError("DIRECT reasoning missing capability_id")
        if not correlation_id:
            raise PolicyGateError("DIRECT requires correlation_id")
        intent = state.get("intent")
        principal = intent.principal if intent is not None else ""
        if not principal:
            raise PolicyGateError("DIRECT requires principal (from UserIntent)")
        return CapabilityRequest(
            capability_id=reasoning.capability_id,
            parameters=reasoning.parameters,  # 原样透传，不 clamp
            principal=principal,
            device_id=reasoning.device_id,
            correlation_id=correlation_id,
            reason=reasoning.rationale or (intent.text if intent is not None else ""),
        )

    raise PolicyGateError(f"policy_gate unreachable for route={route!r}")


def make_policy_gate_handler(
    policy_engine: PolicyEngine,
    approval_engine: ApprovalEngine,
    *,
    audit: AuditStore | None = None,
    risk_context: RiskContext | None = None,
) -> NodeHandler:
    """构造 Policy Gate handler（复用 M0 PolicyEngine + ApprovalEngine）。

    - 提取唯一 canonical request（PLAN/DIRECT）。
    - evaluate 复用 M0 PolicyEngine（kill switch / registry / schema / rate limit / risk）。
    - 无条件 invalidate 上一轮 policy/approval 授权状态（stale-policy invariant）。
    - NEEDS_APPROVAL 时复用 M0 ApprovalEngine.request_approval 生成审批。
    - 任何异常 → fail-closed（REJECTED）。
    """

    def policy_gate(state: AgentState) -> dict[str, Any]:
        # fail-closed：canonical request 提取失败 → REJECTED（绝不进入 execute）
        try:
            request = extract_canonical_request(state)
        except PolicyGateError as exc:
            return _reject(state, str(exc))

        correlation_id = request.correlation_id
        # 优先取本轮 per-request 风险上下文（Runtime 从 RuntimeContext 派生），缺省回退构造时值
        effective_risk = state.get("risk_context") or risk_context
        try:
            decision = policy_engine.evaluate(request, effective_risk)
        except Exception as exc:  # UnknownCapabilityError 等 → fail-closed
            if audit is not None:
                audit.append("policy_rejected", correlation_id, {"reason": str(exc)})
            return _reject(state, str(exc))

        route = derive_policy_route(decision)

        if audit is not None:
            audit.append(
                "policy_evaluated",
                correlation_id,
                {
                    "tier": int(decision.tier),
                    "allowed": decision.allowed,
                    "requires_approval": decision.requires_approval,
                    "reason": decision.reason,
                },
            )

        # stale-policy invariant：无条件 invalidate 上一轮 policy/approval 授权状态，
        # 再由本轮结果重新建立。
        updates: dict[str, Any] = {
            "current_request": request,
            "policy_decision": decision,
            "policy_route": route,
            "approval_id": None,
            "canonical_request_hash": None,
            "needs_human_review": False,
        }

        if route == PolicyRoute.REJECTED:
            if audit is not None:
                audit.append("policy_rejected", correlation_id, {"reason": decision.reason})
            return updates

        if route == PolicyRoute.NEEDS_APPROVAL:
            ar = approval_engine.request_approval(request, int(decision.tier))
            updates["approval_id"] = ar.approval_id
            updates["canonical_request_hash"] = ar.canonical_request_hash
            updates["needs_human_review"] = True
            if audit is not None:
                audit.append(
                    "needs_approval",
                    correlation_id,
                    {"approval_id": ar.approval_id, "tier": int(decision.tier)},
                )
            return updates

        # APPROVED
        return updates

    return policy_gate


def _reject(state: AgentState, reason: str) -> dict[str, Any]:
    """fail-closed 拒绝：无条件 invalidate 上一轮全部 policy/approval 授权状态。

    stale-policy invariant（REV2）：canonical extraction failure 或 PolicyEngine
    exception 都必须证明「旧 approved decision 不残留」。因此除 `approval_id` /
    `canonical_request_hash` / `needs_human_review` 外，还必须显式清空
    `policy_decision` 与 `current_request`——否则上一轮的 approved decision / 旧
    canonical request 会经 partial state merge 残留，被误当成本轮授权。
    """
    return {
        "policy_route": PolicyRoute.REJECTED,
        "policy_decision": None,
        "current_request": None,
        "approval_id": None,
        "canonical_request_hash": None,
        "needs_human_review": False,
        "policy_reject_reason": reason,
    }
