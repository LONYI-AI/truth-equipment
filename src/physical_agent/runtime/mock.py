"""MockRuntime：确定性的参考实现（v3.0 §9 / §44 M0-C）。

不调用真实 LLM。用确定性 planner 把意图映射为 CapabilityRequest，
并强制经 CapabilityGateway（Safety Kernel）执行，绝不直连设备。
"""

from __future__ import annotations

from collections.abc import Callable

from physical_agent.capability.request import CapabilityRequest
from physical_agent.policy.risk import RiskContext
from physical_agent.runtime.base import (
    AgentResult,
    RuntimeCapabilities,
    RuntimeContext,
    RuntimeEvent,
    UserIntent,
)
from physical_agent.safety.gateway import CapabilityGateway


# 默认 planner：文本 → capability 请求列表（确定性，非 LLM）
def default_planner(intent: UserIntent, correlation_id: str) -> list[CapabilityRequest]:
    text = intent.text
    lower = text.lower()
    if "开空调" in text or "打开空调" in text or "turn on" in lower:
        return [
            CapabilityRequest(
                capability_id="home.climate.turn_on",
                parameters={"temperature": 26, "mode": "cool"},
                principal=intent.principal,
                correlation_id=correlation_id,
                reason=text,
            )
        ]
    if "关空调" in text or "关闭空调" in text or "turn off" in lower:
        return [
            CapabilityRequest(
                capability_id="home.climate.turn_off",
                parameters={},
                principal=intent.principal,
                correlation_id=correlation_id,
                reason=text,
            )
        ]
    if "温度" in text or "set_temperature" in lower:
        return [
            CapabilityRequest(
                capability_id="home.climate.set_temperature",
                parameters={"temperature": 26},
                principal=intent.principal,
                correlation_id=correlation_id,
                reason=text,
            )
        ]
    return []


class MockRuntime:
    """确定性参考 runtime，满足 AgentRuntime 协议。"""

    def __init__(
        self,
        gateway: CapabilityGateway,
        planner: Callable[[UserIntent, str], list[CapabilityRequest]] | None = None,
    ) -> None:
        self._gateway = gateway
        self._planner = planner or default_planner
        self._sessions: dict[str, list[str]] = {}  # session_id -> correlation_ids

    def capabilities(self) -> RuntimeCapabilities:
        # MockRuntime 是内存实现：原生支持 resume/cancel，无跨进程持久化
        return RuntimeCapabilities(
            native_resume=True,
            native_cancel=True,
            persistent_session_recovery=False,
            streaming=False,
            tool_bridge=True,
        )

    async def run(self, intent: UserIntent, context: RuntimeContext) -> AgentResult:
        correlation_id = context.correlation_id
        self._sessions.setdefault(context.session_id, []).append(correlation_id)

        requests = self._planner(intent, correlation_id)
        if not requests:
            return AgentResult(
                session_id=context.session_id,
                correlation_id=correlation_id,
                status="completed",
                message="no actionable capability for intent",
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
            correlation_id=correlation_id,
            status=status,
            capabilities=results,
            message=f"executed {len(results)} capability request(s)",
        )

    async def resume(self, session_id: str, event: RuntimeEvent) -> AgentResult:
        # MockRuntime：resume 用于人工审批后继续（简化实现）
        return AgentResult(
            session_id=session_id,
            correlation_id="",
            status="completed",
            message="resume is a no-op in MockRuntime",
        )

    async def cancel(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)
