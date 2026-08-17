"""M1A-W5（Integration Hardening）NodeHandlers 组装：单一权威组装点。

集中把 Safety Kernel（gateway）+ Memory + Reasoning + Perception 组装成 11 个节点
handler。测试与产品入口都走这里，禁止各自拼一套不同架构。
"""

from __future__ import annotations

from physical_agent.audit.store import AuditStore
from physical_agent.memory.store import MemoryStore
from physical_agent.policy.risk import RiskContext
from physical_agent.runtime.graph import NodeHandlers
from physical_agent.runtime.nodes import (
    make_compensate_handler,
    make_escalate_handler,
    make_execute_handler,
    make_human_review_handler,
    make_memory_update_handler,
    make_perceive_handler,
    make_plan_handler,
    make_policy_gate_handler,
    make_reason_handler,
    make_recall_handler,
    make_verify_handler,
)
from physical_agent.runtime.nodes.perceive import WorldStateSource
from physical_agent.runtime.nodes.reason import ReasoningModel
from physical_agent.safety.gateway import CapabilityGateway


def build_node_handlers(
    gateway: CapabilityGateway,
    *,
    memory: MemoryStore,
    reasoning_model: ReasoningModel,
    perception_source: WorldStateSource,
    audit: AuditStore | None = None,
    risk_context: RiskContext | None = None,
) -> NodeHandlers:
    """组装 M1A StateGraph 的全部节点 handler。

    - Policy Gate / Human Review 复用 `gateway.policy` / `gateway.approval`（保证与
      Safety Kernel 共享同一 PolicyEngine/RateLimiter/KillSwitch/ApprovalEngine 实例）。
    - 所有节点写同一 `audit`（缺省 `gateway.audit`），保证单一 tamper-evident 链。
    - 不在此处 import tests；reasoning / perception / memory 均由调用方注入。
    """
    audit = audit if audit is not None else gateway.audit
    policy_engine = gateway.policy
    approval_engine = gateway.approval

    return NodeHandlers(
        perceive=make_perceive_handler(perception_source, audit=audit),
        recall=make_recall_handler(memory, audit=audit),
        reason=make_reason_handler(reasoning_model, audit=audit),
        plan=make_plan_handler(audit=audit),
        policy_gate=make_policy_gate_handler(policy_engine, approval_engine, audit=audit, risk_context=risk_context),
        execute=make_execute_handler(gateway, audit=audit),
        verify=make_verify_handler(audit=audit),
        compensate=make_compensate_handler(audit=audit),
        memory_update=make_memory_update_handler(memory, audit=audit),
        escalate=make_escalate_handler(audit=audit),
        human_review=make_human_review_handler(policy_engine, approval_engine, audit=audit, risk_context=risk_context),
    )
