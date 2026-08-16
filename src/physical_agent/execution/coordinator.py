"""执行协调器：把 Policy 批准的请求派发到 Adapter，并推进状态机。

M0.1 P0-8：correlation ID 唯一性 + 幂等 + 防重放。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from physical_agent.capability.request import CapabilityRequest
from physical_agent.execution.state_machine import ExecutionState, ExecutionStateMachine
from physical_agent.policy.engine import PolicyDecision, PolicyDeniedError


class DuplicateCorrelationError(Exception):
    """重复 correlation_id（重放防护）。"""


@dataclass
class ExecutionRecord:
    """一次执行的生命周期记录。"""

    correlation_id: str
    capability_id: str
    parameters: dict[str, Any]
    machine: ExecutionStateMachine
    decision: PolicyDecision | None = None
    adapter_result: Any = None
    started_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    @property
    def state(self) -> ExecutionState:
        return self.machine.state


class ExecutionCoordinator:
    """协调执行：确保顺序经 Policy → dispatch → 状态推进，并保证 correlation 唯一。"""

    def __init__(self) -> None:
        self._records: dict[str, ExecutionRecord] = {}

    def _ensure_unique(self, correlation_id: str) -> None:
        if correlation_id in self._records:
            raise DuplicateCorrelationError(
                f"duplicate correlation_id {correlation_id!r} (replay rejected)"
            )

    def begin(self, request: CapabilityRequest, decision: PolicyDecision) -> ExecutionRecord:
        if not decision.allowed:
            raise PolicyDeniedError(decision.reason)

        self._ensure_unique(request.correlation_id)

        machine = ExecutionStateMachine(request.correlation_id)
        # 需要审批的请求先进入 NEEDS_APPROVAL，而非直接 AUTHORIZED
        if decision.requires_approval:
            machine.advance(ExecutionState.NEEDS_APPROVAL)
        else:
            machine.advance(ExecutionState.AUTHORIZED)

        record = ExecutionRecord(
            correlation_id=request.correlation_id,
            capability_id=request.capability_id,
            parameters=request.parameters,
            machine=machine,
            decision=decision,
        )
        self._records[request.correlation_id] = record
        return record

    def approve(self, correlation_id: str) -> None:
        """审批通过：NEEDS_APPROVAL → APPROVED → AUTHORIZED。"""
        record = self._records[correlation_id]
        record.machine.advance(ExecutionState.APPROVED)
        record.machine.advance(ExecutionState.AUTHORIZED)

    def mark_dispatched(self, correlation_id: str, result: Any = None) -> None:
        record = self._records[correlation_id]
        record.adapter_result = result
        record.machine.advance(ExecutionState.DISPATCHED)

    def advance(self, correlation_id: str, state: ExecutionState) -> None:
        self._records[correlation_id].machine.advance(state)

    def get(self, correlation_id: str) -> ExecutionRecord:
        return self._records[correlation_id]

    def has(self, correlation_id: str) -> bool:
        return correlation_id in self._records
