"""M1A-W2 Plan 节点：ReasoningDecision → 结构化 Plan（复用 M0 CapabilityRequest）。

Plan 不执行 parameter policy validation、不 clamp 参数、不校验 capability_id 是否注册
（这些属 Policy Gate / CapabilityDefinition.validate_parameters / registry 职责）。
Plan 只把 ReasoningDecision 忠实转成 structured Plan，参数原样透传。
"""

from __future__ import annotations

from typing import Any

from physical_agent.capability.request import CapabilityRequest
from physical_agent.runtime.graph import NodeHandler
from physical_agent.runtime.planning import Plan, ReasoningDecision
from physical_agent.runtime.state import AgentState


class PlanError(ValueError):
    """Plan 关键输入缺失或非法。"""


def make_plan_handler() -> NodeHandler:
    """构造 Plan handler。

    fail-closed：缺 ReasoningDecision / correlation_id / principal 时显式报错，
    不偷偷填造 identity 或 correlation ID。

    注意：经 typed 路由后，Plan 节点只会被 PLAN 决策到达；NOOP 决策在 Reason →
    Graph 边界即终态（END），不会进入 Plan。此处的 non-actionable 分支是防御性兜底。
    """

    def plan(state: AgentState) -> dict[str, Any]:
        decision: ReasoningDecision | None = state.get("reasoning")
        if decision is None:
            raise PlanError("plan requires ReasoningDecision")

        if not decision.is_actionable:
            # 防御性兜底（正常不可达：NOOP 已在 Reason 边界终态）
            return {"current_plan": None}

        correlation_id = state.get("correlation_id", "")
        if not correlation_id:
            raise PlanError("plan requires correlation_id")

        intent = state.get("intent")
        principal = intent.principal if intent is not None else ""
        if not principal:
            raise PlanError("plan requires principal (from UserIntent)")

        reason = decision.rationale or (intent.text if intent is not None else "")

        request = CapabilityRequest(
            capability_id=decision.capability_id or "",
            parameters=decision.parameters,  # 原样透传，不 clamp
            principal=principal,
            device_id=decision.device_id,
            correlation_id=correlation_id,
            reason=reason,
        )

        current_plan = Plan(
            session_id=state.get("session_id", ""),
            correlation_id=correlation_id,
            steps=[request],
        )
        return {"current_plan": current_plan}

    return plan
