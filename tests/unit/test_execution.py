"""执行状态机与协调器单元测试。"""

from __future__ import annotations

import pytest

from physical_agent.execution.state_machine import (
    ExecutionState,
    ExecutionStateMachine,
    IllegalTransitionError,
)


def test_full_success_path():
    sm = ExecutionStateMachine("c1")
    sm.advance(ExecutionState.AUTHORIZED)
    sm.advance(ExecutionState.DISPATCHED)
    sm.advance(ExecutionState.ACTUATION_OBSERVED)
    sm.advance(ExecutionState.DEVICE_EVIDENCE)
    sm.advance(ExecutionState.PHYSICAL_EFFECT)
    assert sm.is_success
    assert sm.is_terminal


def test_illegal_transition_raises():
    sm = ExecutionStateMachine("c1")
    sm.advance(ExecutionState.AUTHORIZED)
    with pytest.raises(IllegalTransitionError):
        # AUTHORIZED -> PHYSICAL_EFFECT 非法（不能跳过 DISPATCHED）
        sm.advance(ExecutionState.PHYSICAL_EFFECT)


def test_dispatch_cannot_jump_to_effect():
    sm = ExecutionStateMachine("c1")
    sm.advance(ExecutionState.AUTHORIZED)
    sm.advance(ExecutionState.DISPATCHED)
    with pytest.raises(IllegalTransitionError):
        sm.advance(ExecutionState.PHYSICAL_EFFECT)  # 必须先 ACTUATION_OBSERVED


def test_reject_path():
    sm = ExecutionStateMachine("c1")
    sm.advance(ExecutionState.REJECTED)
    assert sm.is_terminal
    assert not sm.is_success


def test_failed_path_from_dispatch():
    sm = ExecutionStateMachine("c1")
    sm.advance(ExecutionState.AUTHORIZED)
    sm.advance(ExecutionState.DISPATCHED)
    sm.advance(ExecutionState.FAILED)
    assert sm.is_terminal
    assert not sm.is_success
