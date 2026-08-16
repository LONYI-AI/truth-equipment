"""VerificationEngine 单元测试。"""

from __future__ import annotations

from physical_agent.capability.schema import VerificationLevel
from physical_agent.verification.engine import VerificationEngine


def test_dispatch_only_yields_v1():
    eng = VerificationEngine()
    ev = eng.verify(
        correlation_id="c1",
        capability_id="home.climate.turn_on",
        execution_evidence={"dispatched": True},
    )
    assert ev.level == VerificationLevel.V1


def test_actuation_yields_v2():
    eng = VerificationEngine()
    ev = eng.verify(
        correlation_id="c1",
        capability_id="home.climate.turn_on",
        execution_evidence={"dispatched": True, "actuation_observed": True},
    )
    assert ev.level == VerificationLevel.V2


def test_device_evidence_yields_v3():
    eng = VerificationEngine()
    ev = eng.verify(
        correlation_id="c1",
        capability_id="home.climate.turn_on",
        execution_evidence={
            "dispatched": True,
            "actuation_observed": True,
            "device_evidence": True,
        },
    )
    assert ev.level == VerificationLevel.V3


def test_physical_effect_yields_v4():
    eng = VerificationEngine()
    ev = eng.verify(
        correlation_id="c1",
        capability_id="home.climate.turn_on",
        execution_evidence={
            "dispatched": True,
            "actuation_observed": True,
            "device_evidence": True,
            "physical_effect_verified": True,
            "physical_effect": "confirmed",
        },
    )
    assert ev.level == VerificationLevel.V4
    assert ev.physical_effect == "confirmed"


def test_ir_readback_does_not_imply_device_execution():
    """关键语义：IR 回读（V2）≠ 设备执行（V3/V4）。"""
    eng = VerificationEngine()
    ev = eng.verify(
        correlation_id="c1",
        capability_id="home.climate.turn_on",
        # 只有 actuation_observed（IR waveform），无 device_evidence
        execution_evidence={"dispatched": True, "actuation_observed": True},
    )
    assert ev.level == VerificationLevel.V2
    assert not ev.reached(VerificationLevel.V3)
    assert not ev.reached(VerificationLevel.V4)
