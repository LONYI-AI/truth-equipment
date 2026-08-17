"""M1A-W5（Integration Hardening）终端边界节点：Compensate / Escalate。

M1A Simulation MVP 语义：verification failure 一律 fail-closed 到安全终态，不实现
真实回滚/升级动作（正式 retry / compensate lifecycle 记录为后续 hardening 项）。
这两个节点只做一件事：写入审计事件并安全终止（返回空更新 → END），绝不执行任何设备动作。
"""

from __future__ import annotations

from typing import Any

from physical_agent.audit.store import AuditStore
from physical_agent.runtime.graph import NodeHandler
from physical_agent.runtime.state import AgentState


def make_compensate_handler(*, audit: AuditStore | None = None) -> NodeHandler:
    """构造 Compensate handler（安全终态 boundary，不实现真实补偿动作）。"""

    def compensate(state: AgentState) -> dict[str, Any]:
        correlation_id = state.get("correlation_id", "")
        outcome = state.get("execution_outcome") or {}
        if audit is not None:
            audit.append(
                "compensated",
                correlation_id,
                {
                    "reason": outcome.get("reason", "verification failed"),
                    "execution_status": outcome.get("status"),
                },
            )
        return {}

    return compensate


def make_escalate_handler(*, audit: AuditStore | None = None) -> NodeHandler:
    """构造 Escalate handler（policy 拒绝 / 审批拒绝的安全终态 boundary）。"""

    def escalate(state: AgentState) -> dict[str, Any]:
        correlation_id = state.get("correlation_id", "")
        reason = state.get("policy_reject_reason") or "policy rejected"
        if audit is not None:
            audit.append(
                "escalated",
                correlation_id,
                {"reason": reason},
            )
        return {}

    return escalate
