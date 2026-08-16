"""M1A-W1 REV2：真实 LangGraph StateGraph 拓扑构建器。

W1 只建立**真实 LangGraph 拓扑骨架**，不实现业务逻辑：
- 生产代码不含 perceive/recall/reason/... 的"假成功"实现；
- 节点 handler 通过显式契约注入（支持同步与异步），测试注入 deterministic handler。

零物理执行：本模块不 import 任何 adapter / safety / execution 模块，
graph 骨架本身不做任何设备 actuation，不引用 CapabilityGateway 做真实执行。

审批挂起/恢复：W1 只定义 `human_review` 边界节点 + 状态契约（session_id /
correlation_id / approval_id / canonical_request_hash），不实现 checkpoint/resume
机制（该机制属 W3，届时依官方文档选定）。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from langgraph.graph import END, START, StateGraph

from physical_agent.runtime.state import AgentState

# 节点 handler 契约：同步或异步皆可（官方 LangGraph 支持 sync/async 节点）。
SyncNodeHandler = Callable[[AgentState], dict[str, Any]]
AsyncNodeHandler = Callable[[AgentState], Awaitable[dict[str, Any]]]
NodeHandler = SyncNodeHandler | AsyncNodeHandler


@dataclass
class NodeHandlers:
    """可注入的节点 handler 集合（显式契约，支持 sync/async）。

    W1 不提供业务实现；所有 handler 由调用方注入。缺任一 handler 时 build_graph 报错，
    绝不提供空壳 completed 行为。
    """

    perceive: NodeHandler
    recall: NodeHandler
    reason: NodeHandler
    plan: NodeHandler
    policy_gate: NodeHandler
    execute: NodeHandler
    verify: NodeHandler
    compensate: NodeHandler
    memory_update: NodeHandler
    escalate: NodeHandler
    human_review: NodeHandler


# 拓扑中的节点名（测试据此断言 EXPECTED_NODE_NAMES_PRESENT）。
NODE_NAMES: tuple[str, ...] = (
    "perceive",
    "recall",
    "reason",
    "plan",
    "policy_gate",
    "execute",
    "verify",
    "compensate",
    "memory_update",
    "escalate",
    "human_review",
)


def route_after_reason(state: AgentState) -> str:
    """直接决策边界：reason 产出了需进一步结构化的计划 → plan；否则 → policy_gate。"""
    return "plan" if state.get("has_plan") else "policy_gate"


def route_after_policy(state: AgentState) -> str:
    """policy 路由：approved → execute；needs_approval → human_review；否则 → escalate。

    默认 fail-closed：未知/缺失判定一律走 escalate 终端，不执行。
    """
    verdict = state.get("policy_verdict", "rejected")
    if verdict == "approved":
        return "execute"
    if verdict == "needs_approval":
        return "human_review"
    return "escalate"


def route_after_verify(state: AgentState) -> str:
    """verify 路由，派生自 M0 `VerificationEvidence` 语义（不另造 verdict dict）：

    - physical_effect == "confirmed" → memory_update（成功）
    - 否则视为失败：retry_count < 2 → execute（重试）；retry_count >= 2 → compensate（耗尽）

    注意：W1 只编码路由逻辑，不实现 retry 计数递增等完整业务行为（属后续 M1A slice）。
    """
    verification = state.get("verification")
    if verification is not None and verification.physical_effect == "confirmed":
        return "memory_update"
    retry_count = state.get("retry_count", 0)
    if retry_count < 2:
        return "execute"
    return "compensate"


def build_graph(handlers: NodeHandlers) -> Any:
    """用真实 langgraph StateGraph 构建 M1A 拓扑，返回编译后的图。

    拓扑（对齐 ARCHITECTURE.md §2.1 控制流）：
        START → perceive → recall → reason
          reason ─(has_plan?)─┬→ plan ─→ policy_gate
                              └→ policy_gate（直接决策）
          policy_gate ─┬→ approved  → execute → verify
                       ├→ rejected  → escalate → END
                       └→ needs_approval → human_review → END（挂起边界）
          verify ─┬→ confirmed → memory_update → END
                  ├→ retry<2 → execute
                  └→ retry>=2 → compensate → END
    """
    builder = StateGraph(AgentState)

    for name in NODE_NAMES:
        handler = getattr(handlers, name)
        if handler is None:  # pragma: no cover - defensive
            raise ValueError(f"missing node handler: {name!r}")
        builder.add_node(name, handler)

    # 线性链：START → perceive → recall → reason
    builder.add_edge(START, "perceive")
    builder.add_edge("perceive", "recall")
    builder.add_edge("recall", "reason")

    # 直接决策边界
    builder.add_conditional_edges(
        "reason",
        route_after_reason,
        {"plan": "plan", "policy_gate": "policy_gate"},
    )
    builder.add_edge("plan", "policy_gate")

    # policy 路由
    builder.add_conditional_edges(
        "policy_gate",
        route_after_policy,
        {"execute": "execute", "escalate": "escalate", "human_review": "human_review"},
    )

    # 执行 → 验证
    builder.add_edge("execute", "verify")

    # 验证路由
    builder.add_conditional_edges(
        "verify",
        route_after_verify,
        {"memory_update": "memory_update", "execute": "execute", "compensate": "compensate"},
    )

    # 终态 / 边界
    builder.add_edge("memory_update", END)
    builder.add_edge("compensate", END)
    builder.add_edge("escalate", END)
    builder.add_edge("human_review", END)

    return builder.compile()
