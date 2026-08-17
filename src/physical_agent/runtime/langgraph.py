"""LangGraphRuntime：正式 M1A Simulation Runtime（真实 StateGraph + 真实 resume）。

M1A-W5（Integration Hardening）把 M0-W4 测试中已验证的 StateGraph 正式接线到
`AgentRuntime` 协议：

- `run()`：构造本轮 AgentState（messages / intent / session_id / correlation_id /
  **request-scoped risk_context**），经真实编译图 `ainvoke`。命中审批挂起（interrupt）
  → 返回 `needs_approval`；否则解释终态为 `completed / rejected / failed`。
- `resume()`：用真实 LangGraph `Command(resume={"decision": ...})` + checkpointer
  恢复挂起会话（不再保留占位 resume）。
- `cancel()`：丢弃会话簿记。

安全语义：
- 正式执行路径恒为 Perceive → Recall → Reason → Plan → Policy → Approval →
  Execute → Verify（经注入的 NodeHandlers / graph），**不再依赖旧 `default_planner`**。
- `risk_context` 是本轮 request-scoped **输入上下文**（非 authorization state），
  每轮 `run()` 无条件覆盖上一轮，防止 stale risk context 污染下一轮。授权事实来源
  始终是 PolicyDecision / Approval lifecycle / canonical CapabilityRequest。
"""

from __future__ import annotations

from typing import Any

from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from physical_agent.audit.store import AuditStore
from physical_agent.memory.store import MemoryStore, SqliteMemoryStore
from physical_agent.policy.risk import RiskContext
from physical_agent.runtime.assembly import build_node_handlers
from physical_agent.runtime.base import (
    AgentResult,
    RuntimeCapabilities,
    RuntimeContext,
    RuntimeEvent,
    UserIntent,
)
from physical_agent.runtime.graph import NodeHandlers, build_graph
from physical_agent.runtime.nodes.perceive import PerceptionSnapshot, WorldStateSource
from physical_agent.runtime.nodes.reason import ReasoningModel
from physical_agent.runtime.planning import PolicyRoute, ReasoningRoute
from physical_agent.runtime.reasoning import RuleBasedReasoningModel
from physical_agent.safety.gateway import CapabilityGateway


class _EmptyPerceptionSource:
    """无设备已知时的空感知源（供单参构造默认自组装使用，不声称任何设备状态）。"""

    def read_snapshot(self) -> PerceptionSnapshot:
        return PerceptionSnapshot(devices={}, environment={})


class LangGraphRuntime:
    """M1A Simulation 正式 Runtime（真实 LangGraph StateGraph + 真实 resume）。"""

    def __init__(
        self,
        gateway: CapabilityGateway,
        *,
        graph: Any | None = None,
        handlers: NodeHandlers | None = None,
        checkpointer: Any | None = None,
        audit: AuditStore | None = None,
        memory: MemoryStore | None = None,
        reasoning_model: ReasoningModel | None = None,
        perception_source: WorldStateSource | None = None,
        risk_context: RiskContext | None = None,
    ) -> None:
        self._gateway = gateway
        self._audit = audit if audit is not None else gateway.audit
        self._risk_context = risk_context

        # 默认自组装（保持 LangGraphRuntime(gateway) 单参构造向后兼容；正式入口经
        # composition root 显式传入 graph/handlers）。二者共用同一 build_node_handlers。
        self._memory = memory if memory is not None else SqliteMemoryStore(":memory:")
        self._reasoning_model = reasoning_model if reasoning_model is not None else RuleBasedReasoningModel()
        self._perception_source = perception_source if perception_source is not None else _EmptyPerceptionSource()
        self._handlers = handlers if handlers is not None else build_node_handlers(
            gateway,
            memory=self._memory,
            reasoning_model=self._reasoning_model,
            perception_source=self._perception_source,
            audit=self._audit,
            risk_context=risk_context,
        )
        self._checkpointer = checkpointer if checkpointer is not None else InMemorySaver()
        self._graph = graph if graph is not None else build_graph(self._handlers, checkpointer=self._checkpointer)

        # session_id -> {"thread_id", "correlation_id", "finalized"}
        # finalized=True 后禁止再次 resume（stale/replay approval 防护）。
        self._sessions: dict[str, dict[str, Any]] = {}

    def capabilities(self) -> RuntimeCapabilities:
        return RuntimeCapabilities(
            native_resume=True,
            native_cancel=True,
            persistent_session_recovery=False,
            streaming=True,
            tool_bridge=True,
        )

    def _build_risk_context(self, intent: UserIntent, context: RuntimeContext) -> RiskContext:
        """把本轮 RuntimeContext 派生为 request-scoped RiskContext（纯输入，非授权状态）。"""
        return RiskContext(
            principal=intent.principal or "agent",
            location=context.location,
            time_of_day=context.time_of_day,
            occupancy=context.occupancy,
            environment=context.environment,
        )

    async def run(self, intent: UserIntent, context: RuntimeContext) -> AgentResult:
        correlation_id = context.correlation_id or self._gateway.new_correlation_id()
        session_id = context.session_id or f"sess-{correlation_id}"
        thread_id = session_id

        # 本轮 request-scoped risk context：无条件覆盖上一轮（stale 防护）。
        risk = self._build_risk_context(intent, context)

        self._audit.append(
            "user_input_received",
            correlation_id,
            {"text": intent.text, "principal": intent.principal},
        )

        initial_state: dict[str, Any] = {
            "messages": [HumanMessage(content=intent.text)],
            "intent": intent,
            "session_id": session_id,
            "correlation_id": correlation_id,
            "risk_context": risk,
        }
        config = {"configurable": {"thread_id": thread_id}}

        result = await self._graph.ainvoke(initial_state, config)
        self._sessions[session_id] = {
            "thread_id": thread_id,
            "correlation_id": correlation_id,
            "finalized": False,
        }

        if "__interrupt__" in result:
            payload = result["__interrupt__"][0].value
            return AgentResult(
                session_id=session_id,
                correlation_id=correlation_id,
                status="needs_approval",
                message="此动作需要批准。",
                evidence={
                    "approval_id": payload.get("approval_id"),
                    "canonical_request_hash": payload.get("canonical_request_hash"),
                },
            )

        return self._finalize(result, session_id, correlation_id)

    async def resume(self, session_id: str, event: RuntimeEvent) -> AgentResult:
        session = self._sessions.get(session_id)
        if session is None:
            return AgentResult(
                session_id=session_id,
                correlation_id="",
                status="failed",
                message="unknown session (cannot resume)",
            )
        if session.get("finalized"):
            # stale/replay approval：会话已终结，禁止再次 resume（绝不二次 execute）
            return AgentResult(
                session_id=session_id,
                correlation_id=session["correlation_id"],
                status="rejected",
                message="approval replay rejected (session already finalized)",
            )

        thread_id = session["thread_id"]
        correlation_id = session["correlation_id"]
        decision = event.payload.get("decision", "reject") if isinstance(event.payload, dict) else "reject"

        result = await self._graph.ainvoke(
            Command(resume={"decision": decision}),
            {"configurable": {"thread_id": thread_id}},
        )
        return self._finalize(result, session_id, correlation_id)

    async def cancel(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)

    # ---- 终态解释 ----

    def _finalize(self, state: dict[str, Any], session_id: str, correlation_id: str) -> AgentResult:
        route = state.get("route")
        policy_route = state.get("policy_route")
        verification = state.get("verification")
        satisfied = bool(state.get("verification_satisfied"))
        outcome = state.get("execution_outcome")
        reasoning_failed = bool(state.get("reasoning_failed"))

        # Reasoning 失败（模型异常/malformed）必须与正常 non-actionable NOOP 区分：
        # 前者 failed，后者 completed/no actionable capability。
        if reasoning_failed:
            status, message = "failed", "reasoning failed"
        elif route == ReasoningRoute.NOOP:
            status, message = "completed", "no actionable capability for intent"
        elif policy_route == PolicyRoute.REJECTED:
            reason = state.get("policy_reject_reason") or "policy decision denied"
            status, message = "rejected", f"policy rejected: {reason}"
        elif satisfied:
            level = verification.level.value if verification is not None else ""
            status = "completed"
            message = f"SIMULATION 执行完成。\nVerification: {level} satisfied"
        else:
            status, message = "failed", "verification failed (fail-closed to safe terminal)"

        self._audit.append("session_complete", correlation_id, {"status": status})

        # 标记会话终结：禁止再次 resume（stale/replay 防护）
        session = self._sessions.get(session_id)
        if session is not None:
            session["finalized"] = True

        capabilities = [outcome] if outcome else []
        evidence = {
            "verification_level": verification.level.value if verification is not None else None,
            "verification_satisfied": satisfied,
            "policy_route": policy_route.value if policy_route is not None else None,
            "execution_mode": "simulation",
        }
        return AgentResult(
            session_id=session_id,
            correlation_id=correlation_id,
            status=status,
            message=message,
            capabilities=capabilities,
            evidence=evidence,
        )
