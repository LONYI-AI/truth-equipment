"""Execution 层：执行状态机与协调器（v3.0 §21）。"""

from physical_agent.execution.coordinator import ExecutionCoordinator, ExecutionRecord
from physical_agent.execution.state_machine import (
    ExecutionMode,
    ExecutionState,
    ExecutionStateMachine,
    IllegalTransitionError,
)

__all__ = [
    "ExecutionMode",
    "ExecutionState",
    "ExecutionStateMachine",
    "IllegalTransitionError",
    "ExecutionCoordinator",
    "ExecutionRecord",
]
