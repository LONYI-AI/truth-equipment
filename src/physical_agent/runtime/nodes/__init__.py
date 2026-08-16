"""M1A-W4 节点：Perceive / Recall / Reason / Plan / Policy Gate / Human Review / Execute / Verify。

W2 暴露 perceive/recall/reason/plan 构造工厂；W3 新增 policy_gate / human_review；
W4 新增 execute（SIMULATION-only gateway 派发）/ verify（outcome → VerificationEvidence）。
"""

from physical_agent.runtime.nodes.execute import make_execute_handler
from physical_agent.runtime.nodes.human_review import make_human_review_handler
from physical_agent.runtime.nodes.perceive import (
    PerceptionSnapshot,
    WorldStateSource,
    make_perceive_handler,
)
from physical_agent.runtime.nodes.plan import PlanError, make_plan_handler
from physical_agent.runtime.nodes.policy_gate import (
    PolicyGateError,
    derive_policy_route,
    extract_canonical_request,
    make_policy_gate_handler,
)
from physical_agent.runtime.nodes.reason import ReasoningModel, make_reason_handler
from physical_agent.runtime.nodes.recall import RecallError, make_recall_handler
from physical_agent.runtime.nodes.verify import make_verify_handler

__all__ = [
    "PerceptionSnapshot",
    "WorldStateSource",
    "make_perceive_handler",
    "make_recall_handler",
    "RecallError",
    "ReasoningModel",
    "make_reason_handler",
    "make_plan_handler",
    "PlanError",
    "PolicyGateError",
    "derive_policy_route",
    "extract_canonical_request",
    "make_policy_gate_handler",
    "make_human_review_handler",
    "make_execute_handler",
    "make_verify_handler",
]
