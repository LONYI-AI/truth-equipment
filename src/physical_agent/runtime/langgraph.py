"""LangGraphRuntime：stable reference runtime（v3.0 §10）。

M0.1 状态：实现 AgentRuntime 协议 + 能力声明，强制经 CapabilityGateway。
真实 LangGraph 图在 M1A 接入；但**不返回空壳 completed**——任何动作都经 gateway，
不直连设备、不持有设备凭据。
"""

from __future__ import annotations

from physical_agent.policy.risk import RiskContext
from physical_agent.runtime.base import (
    AgentResult,
    RuntimeCapabilities,
    RuntimeContext,
    RuntimeEvent,
    UserIntent,
)
from physical_agent.runtime.mock import default_planner
from physical_agent.safety.gateway import CapabilityGateway


class LangGraphRuntime:
    """LangGraph 稳定参考 runtime。

    M0.1：planner 逻辑复用确定性 planner；推理节点（LangGraph）在 M1A 接入。
    所有 capability 执行强制经 gateway。
    """

    def __init__(self, gateway: CapabilityGateway) -> None:
        self._gateway = gateway
        self._sessions: dict[str, list[str]] = {}

    def capabilities(self) -> RuntimeCapabilities:
        return RuntimeCapabilities(
            native_resume=True,
            native_cancel=True,
            persistent_session_recovery=False,
            streaming=True,
            tool_bridge=True,
        )

    async def run(self, intent: UserIntent, context: RuntimeContext) -> AgentResult:
        self._sessions.setdefault(context.session_id, []).append(context.correlation_id)
        requests = default_planner(intent, context.correlation_id)
        if not requests:
            return AgentResult(
                session_id=context.session_id,
                correlation_id=context.correlation_id,
                status="completed",
                message="LangGraphRuntime: no actionable capability for intent",
            )
        results = []
        for req in requests:
            outcome = await self._gateway.execute(
                req,
                RiskContext(
                    location=context.location,
                    time_of_day=context.time_of_day,
                    occupancy=context.occupancy,
                    environment=context.environment,
                ),
            )
            results.append(outcome)

        statuses = {r["status"] for r in results}
        if "rejected" in statuses:
            status = "rejected"
        elif "needs_approval" in statuses:
            status = "needs_approval"
        elif "failed" in statuses:
            status = "failed"
        else:
            status = "completed"

        return AgentResult(
            session_id=context.session_id,
            correlation_id=context.correlation_id,
            status=status,
            capabilities=results,
            message=f"LangGraphRuntime executed {len(results)} capability request(s)",
        )

    async def resume(self, session_id: str, event: RuntimeEvent) -> AgentResult:
        return AgentResult(
            session_id=session_id,
            correlation_id="",
            status="completed",
            message="LangGraphRuntime resume",
        )

    async def cancel(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)
