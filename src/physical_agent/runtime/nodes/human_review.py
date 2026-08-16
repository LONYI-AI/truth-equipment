"""M1A-W3 Human Review 节点：审批挂起（interrupt）/ 恢复（resume）安全边界。

设计约束（W3 授权）：
- 使用 LangGraph 真实 `interrupt()` / `Command(resume=...)` + checkpointer，不自造
  checkpoint/resume、不用全局 dict 冒充持久恢复。
- 挂起后**不得执行**；resume 后**重新对同一 canonical request 执行当前 Policy 校验**，
  仅当当前 Policy 仍允许 + approval 单次消费成功，才授权到达 Execute boundary。
- 复用 M0 `ApprovalEngine.consume()`：单次使用 / 过期 / 精确请求绑定 / 防重放。
"""

from __future__ import annotations

from typing import Any

from langgraph.types import interrupt

from physical_agent.audit.store import AuditStore
from physical_agent.policy.approval import ApprovalEngine, ApprovalError
from physical_agent.policy.engine import PolicyEngine
from physical_agent.policy.risk import RiskContext
from physical_agent.runtime.graph import NodeHandler
from physical_agent.runtime.planning import PolicyRoute
from physical_agent.runtime.state import AgentState


def make_human_review_handler(
    policy_engine: PolicyEngine,
    approval_engine: ApprovalEngine,
    *,
    audit: AuditStore | None = None,
    risk_context: RiskContext | None = None,
) -> NodeHandler:
    """构造 Human Review handler（审批挂起/恢复）。

    - 首次进入：`interrupt(payload)` 挂起，返回审批请求元数据给调用方。
    - 恢复：`resume` 值 `{"decision": "approve"|"reject"}`。
      - reject / malformed → REJECTED（安全终止，绝不执行）。
      - approve → 对同一 canonical request 重新执行当前 Policy；仍允许则
        `ApprovalEngine.consume`（单次使用 + 精确绑定校验）；成功 → APPROVED。
    """

    def human_review(state: AgentState) -> dict[str, Any]:
        approval_id = state.get("approval_id")
        canonical_request_hash = state.get("canonical_request_hash")
        correlation_id = state.get("correlation_id", "")

        # 挂起：把审批请求元数据交给调用方，等待 Owner 审批后 resume。
        resume_value = interrupt(
            {
                "approval_id": approval_id,
                "canonical_request_hash": canonical_request_hash,
                "correlation_id": correlation_id,
            }
        )

        # —— 恢复（resume）——
        if not isinstance(resume_value, dict) or resume_value.get("decision") != "approve":
            if audit is not None:
                audit.append(
                    "approval_rejected",
                    correlation_id,
                    {"approval_id": approval_id, "reason": "not approved"},
                )
            return {"policy_route": PolicyRoute.REJECTED, "needs_human_review": False}

        request = state.get("current_request")
        if request is None:
            if audit is not None:
                audit.append(
                    "approval_rejected",
                    correlation_id,
                    {"approval_id": approval_id, "reason": "missing canonical request"},
                )
            return {"policy_route": PolicyRoute.REJECTED, "needs_human_review": False}

        # 批准不是永久通行证：对同一 canonical request 重新执行当前 Policy。
        try:
            decision = policy_engine.evaluate(request, risk_context)
        except Exception as exc:
            if audit is not None:
                audit.append(
                    "approval_rejected",
                    correlation_id,
                    {"approval_id": approval_id, "reason": f"re-policy failed: {exc}"},
                )
            return {"policy_route": PolicyRoute.REJECTED, "needs_human_review": False}

        if not decision.allowed:
            if audit is not None:
                audit.append(
                    "policy_rejected_after_approval",
                    correlation_id,
                    {"approval_id": approval_id, "capability_id": request.capability_id,
                     "policy_reason": decision.reason},
                )
            return {"policy_route": PolicyRoute.REJECTED, "needs_human_review": False}

        # 单次消费（绑定精确请求 + 过期 + 防重放）。
        try:
            approval_engine.consume(approval_id or "", request, int(decision.tier))
        except (ApprovalError, ValueError) as exc:
            if audit is not None:
                audit.append(
                    "approval_rejected",
                    correlation_id,
                    {"approval_id": approval_id, "reason": str(exc)},
                )
            return {"policy_route": PolicyRoute.REJECTED, "needs_human_review": False}

        if audit is not None:
            audit.append(
                "approval_consumed",
                correlation_id,
                {"approval_id": approval_id, "tier": int(decision.tier)},
            )

        return {"policy_route": PolicyRoute.APPROVED, "needs_human_review": False}

    return human_review
