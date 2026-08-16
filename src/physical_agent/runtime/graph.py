"""M1A-W1 REV2（经 M1A-W2 REV2 整改）：真实 LangGraph StateGraph 拓扑构建器。

W1 只建立**真实 LangGraph 拓扑骨架**，不实现业务逻辑：
- 生产代码不含 perceive/recall/reason/... 的"假成功"实现；
- 节点 handler 通过显式契约注入（支持同步与异步），测试注入 deterministic handler。

零物理执行：本模块不 import 任何 adapter / safety / execution 模块，
graph 骨架本身不做任何设备 actuation，不引用 CapabilityGateway 做真实执行。

W2 REV2 整改（P0）：Reason → Graph 边界改用 typed contract `ReasoningRoute`
（PLAN / DIRECT / NOOP 三态），non-actionable（NOOP）安全终态直达 END，
绝不进入 policy_gate / execute / verify。

W3 整改：Policy → Graph 边界改用 typed contract `PolicyRoute`
（APPROVED / REJECTED / NEEDS_APPROVAL，由本轮真实 PolicyDecision 确定性派生）；
`human_review` 节点支持 LangGraph interrupt/resume 审批挂起/恢复（需调用方
经 `build_graph(handlers, checkpointer=...)` 传入 checkpointer）。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from langgraph.graph import END, START, StateGraph

from physical_agent.runtime.planning import PolicyRoute, ReasoningRoute
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
    """Reason → Graph 边界（typed contract，非单一 bool）。

    - PLAN   → "plan"（planned actionable：先结构化为 Plan）
    - DIRECT → "policy_gate"（direct actionable：显式保留 W1 direct path）
    - NOOP   → "noop"（non-actionable / no-op：安全终态，映射到 END）
    - 缺失/未知 → "noop"（fail-closed：绝不进入 policy/execute/verify）
    """
    route = state.get("route")
    if route == ReasoningRoute.PLAN:
        return "plan"
    if route == ReasoningRoute.DIRECT:
        return "policy_gate"
    return "noop"


def route_after_policy(state: AgentState) -> str:
    """policy 路由（typed contract `PolicyRoute`，非字符串 verdict）。

    - APPROVED       → execute
    - NEEDS_APPROVAL → human_review（挂起边界）
    - REJECTED/缺失  → escalate（fail-closed，绝不执行）

    默认 fail-closed：未知/缺失一律走 escalate 终端，不执行。
    """
    route = state.get("policy_route")
    if route == PolicyRoute.APPROVED:
        return "execute"
    if route == PolicyRoute.NEEDS_APPROVAL:
        return "human_review"
    return "escalate"


def route_after_human_review(state: AgentState) -> str:
    """审批 resume 后的路由（W3）。

    - APPROVED（re-policy 通过 + approval 单次消费成功）→ execute boundary
    - 其余（拒绝 / 重放 / 过期 / 篡改 / re-policy 拒绝 / 消费失败）→ escalate（安全终止）

    默认 fail-closed：缺失/未知一律 escalate，绝不执行。
    """
    route = state.get("policy_route")
    if route == PolicyRoute.APPROVED:
        return "execute"
    return "escalate"


def route_after_verify(state: AgentState) -> str:
    """verify 路由（W4 REV2）：成功语义 = 达到 capability.required_verification_level。

    - `verification_satisfied` True → memory_update（成功终态）
    - 否则（False / 缺失）→ compensate boundary → END（fail-closed 安全终止）

    M1A-W4 MVP 暂不实现自动 retry：verification failure 一律 fail-closed 到
    compensate boundary，绝不回路由 execute（避免「execute → verify failed →
    execute duplicate rejected → ...」的 recursion loop，直至 LangGraph recursion
    limit）。正式 retry lifecycle 留待 MVP 整体 hardening。

    注意：不再用 `physical_effect == "confirmed"` 判定成功——V2 达到 required_level
    即可 satisfied，但 physical_effect 仍为 "pending"，绝不伪造 confirmed（V2 不冒充 V4）。
    """
    if state.get("verification_satisfied"):
        return "memory_update"
    return "compensate"


def build_graph(handlers: NodeHandlers, checkpointer: Any = None) -> Any:
    """用真实 langgraph StateGraph 构建 M1A 拓扑，返回编译后的图。

    `checkpointer`：W3 审批挂起/恢复所需的 LangGraph checkpointer（如
    `InMemorySaver`）。缺省 None 时不可中断（用于无审批路径）；需要
    interrupt/resume 时调用方必须显式传入。

    拓扑（对齐 ARCHITECTURE.md §2.1 控制流，含 W2 三态 + W3 policy/审批路由）：
        START → perceive → recall → reason
          reason ─(route)─┬→ plan ─→ policy_gate          (PLAN)
                          ├→ policy_gate                    (DIRECT)
                          └→ END                             (NOOP，安全终态)
          policy_gate ─┬→ APPROVED        → execute → verify
                       ├→ REJECTED        → escalate → END
                       └→ NEEDS_APPROVAL  → human_review ─(resume)─┬→ execute
                                                                    └→ escalate → END
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

    # Reason → Graph 边界（typed contract：PLAN / DIRECT / NOOP）
    builder.add_conditional_edges(
        "reason",
        route_after_reason,
        {"plan": "plan", "policy_gate": "policy_gate", "noop": END},
    )
    builder.add_edge("plan", "policy_gate")

    # policy 路由（typed contract PolicyRoute）
    builder.add_conditional_edges(
        "policy_gate",
        route_after_policy,
        {"execute": "execute", "escalate": "escalate", "human_review": "human_review"},
    )

    # 审批挂起/恢复：human_review 中断（interrupt），resume 后按审批结果路由
    builder.add_conditional_edges(
        "human_review",
        route_after_human_review,
        {"execute": "execute", "escalate": "escalate"},
    )

    # 执行 → 验证
    builder.add_edge("execute", "verify")

    # 验证路由（W4 REV2：成功 → memory_update；失败 → compensate boundary，不回 execute）
    builder.add_conditional_edges(
        "verify",
        route_after_verify,
        {"memory_update": "memory_update", "compensate": "compensate"},
    )

    # 终态 / 边界
    builder.add_edge("memory_update", END)
    builder.add_edge("compensate", END)
    builder.add_edge("escalate", END)

    if checkpointer is not None:
        return builder.compile(checkpointer=checkpointer)
    return builder.compile()
