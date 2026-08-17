"""M1A-W2 Reason 节点：injectable ReasoningModel → ReasoningDecision。

Reason 只负责推理提议，绝不：
- 调用真实 DeepSeek / OpenAI / Ollama / 互联网 / API key（测试用 Mock LLM）。
- 调 PolicyEngine / 判断 risk tier 作为最终授权 / consume approval。
- execute / verify / clamp 参数 / 自动"修正"越界参数。

W2 REV3 整改（stale-plan lifecycle invariant）：
- **每一轮 ReasoningDecision 无条件 invalidate 任何 prior `current_plan`**（对
  PLAN / DIRECT / NOOP 均输出 `current_plan=None`）。
- 只有 `plan` 节点是 `current-plan` 的唯一生产者（为本轮生成新 Plan）；
  DIRECT / NOOP 均不得携带旧 Plan 越过 Reason 边界。
"""

from __future__ import annotations

from typing import Any, Protocol

from physical_agent.audit.store import AuditStore
from physical_agent.runtime.base import UserIntent
from physical_agent.runtime.graph import NodeHandler
from physical_agent.runtime.planning import (
    MemoryContext,
    ReasoningDecision,
    ReasoningRoute,
)
from physical_agent.runtime.state import AgentState, WorldState


class ReasoningModel(Protocol):
    """可注入的推理模型契约（W2 测试用 deterministic Mock LLM）。"""

    def reason(
        self,
        *,
        messages: list[Any],
        intent: UserIntent | None,
        world_state: WorldState | None,
        memory_context: MemoryContext | None,
    ) -> ReasoningDecision: ...


def make_reason_handler(model: ReasoningModel, *, audit: AuditStore | None = None) -> NodeHandler:
    """构造 Reason handler。

    输出 `reasoning`（ReasoningDecision）+ typed 路由信号 `route`（ReasoningRoute）。
    每轮无条件输出 `current_plan=None`，使任何 prior plan 失效；只有 `plan` 节点
    可以为本轮生成新 Plan（stale-plan lifecycle invariant）。

    fail-closed：`model.reason()` 抛任何异常（malformed model output）都不得让 graph
    崩溃或泄漏进 policy/execute——统一降级为 `route=NOOP` 安全终态（END），并置
    `reasoning_failed=True` + 写 `reason_failed` 审计。正常 non-actionable（模型返回
    NOOP）与模型异常/malformed 必须可区分：前者 completed，后者 failed（见
    `LangGraphRuntime._finalize`）。
    """

    def reason(state: AgentState) -> dict[str, Any]:
        correlation_id = state.get("correlation_id", "")
        try:
            decision = model.reason(
                messages=list(state.get("messages", [])),
                intent=state.get("intent"),
                world_state=state.get("world_state"),
                memory_context=state.get("memory_context"),
            )
        except Exception as exc:  # malformed model output → fail-closed，标记 failed
            if audit is not None:
                audit.append(
                    "reason_failed",
                    correlation_id,
                    {"error": str(exc), "route": ReasoningRoute.NOOP},
                )
            return {
                "reasoning": None,
                "route": ReasoningRoute.NOOP,
                "reasoning_failed": True,
                # invariant：每轮无条件 invalidate prior current_plan
                "current_plan": None,
            }

        if audit is not None:
            audit.append(
                "reason_complete",
                correlation_id,
                {
                    "route": decision.route,
                    "capability_id": decision.capability_id,
                    "actionable": decision.is_actionable,
                },
            )

        return {
            "reasoning": decision,
            "route": decision.route,
            "reasoning_failed": False,
            # invariant：每轮 ReasoningDecision 无条件 invalidate prior current_plan；
            # 只有 plan 节点为本轮重新生成 Plan。
            "current_plan": None,
        }

    return reason
