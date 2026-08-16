"""执行状态机（v3.0 §21 + M0.1 P0-4）。

禁止用 `success = API returned 200` 作为执行成功。
生命周期（含审批）：
REQUESTED → NEEDS_APPROVAL → APPROVED → AUTHORIZED → DISPATCHED
→ ACTUATION_OBSERVED → DEVICE_EVIDENCE → PHYSICAL_EFFECT。
"""

from __future__ import annotations

from enum import StrEnum


class ExecutionState(StrEnum):
    REQUESTED = "REQUESTED"
    NEEDS_APPROVAL = "NEEDS_APPROVAL"
    APPROVED = "APPROVED"
    AUTHORIZED = "AUTHORIZED"
    DISPATCHED = "DISPATCHED"
    ACTUATION_OBSERVED = "ACTUATION_OBSERVED"
    DEVICE_EVIDENCE = "DEVICE_EVIDENCE"
    PHYSICAL_EFFECT = "PHYSICAL_EFFECT"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


# 合法迁移表
_TRANSITIONS: dict[ExecutionState, set[ExecutionState]] = {
    ExecutionState.REQUESTED: {
        ExecutionState.NEEDS_APPROVAL,
        ExecutionState.AUTHORIZED,
        ExecutionState.REJECTED,
        ExecutionState.CANCELLED,
    },
    ExecutionState.NEEDS_APPROVAL: {ExecutionState.APPROVED, ExecutionState.REJECTED, ExecutionState.CANCELLED},
    ExecutionState.APPROVED: {ExecutionState.AUTHORIZED, ExecutionState.CANCELLED},
    ExecutionState.AUTHORIZED: {ExecutionState.DISPATCHED, ExecutionState.CANCELLED, ExecutionState.FAILED},
    ExecutionState.DISPATCHED: {ExecutionState.ACTUATION_OBSERVED, ExecutionState.FAILED, ExecutionState.CANCELLED},
    ExecutionState.ACTUATION_OBSERVED: {ExecutionState.DEVICE_EVIDENCE, ExecutionState.FAILED},
    ExecutionState.DEVICE_EVIDENCE: {ExecutionState.PHYSICAL_EFFECT, ExecutionState.FAILED},
    ExecutionState.PHYSICAL_EFFECT: set(),  # 终态
    ExecutionState.FAILED: set(),
    ExecutionState.CANCELLED: set(),
    ExecutionState.REJECTED: set(),
}

_TERMINAL = {
    ExecutionState.PHYSICAL_EFFECT,
    ExecutionState.FAILED,
    ExecutionState.CANCELLED,
    ExecutionState.REJECTED,
}


class IllegalTransitionError(Exception):
    """非法状态迁移。"""


class ExecutionStateMachine:
    """单次动作执行的显式状态机。"""

    def __init__(self, correlation_id: str) -> None:
        self.correlation_id = correlation_id
        self.state = ExecutionState.REQUESTED
        self.history: list[ExecutionState] = [ExecutionState.REQUESTED]

    @property
    def is_terminal(self) -> bool:
        return self.state in _TERMINAL

    @property
    def is_success(self) -> bool:
        return self.state == ExecutionState.PHYSICAL_EFFECT

    def advance(self, next_state: ExecutionState) -> None:
        if next_state not in _TRANSITIONS[self.state]:
            raise IllegalTransitionError(
                f"illegal transition {self.state.value} -> {next_state.value} "
                f"for {self.correlation_id}"
            )
        self.state = next_state
        self.history.append(next_state)

    def __repr__(self) -> str:  # pragma: no cover - convenience
        return f"ExecutionStateMachine({self.state.value})"
