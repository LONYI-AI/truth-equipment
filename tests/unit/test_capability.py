"""Capability schema 与 registry 单元测试。"""

from __future__ import annotations

import pytest

from physical_agent.capability.registry import CapabilityRegistry, UnknownCapabilityError
from physical_agent.capability.schema import CapabilityDefinition, ParameterSpec, VerificationLevel


def test_parameter_number_in_bounds():
    spec = ParameterSpec(type="integer", minimum=16, maximum=30)
    assert spec.check_value(20) is None
    assert spec.check_value(16) is None
    assert spec.check_value(30) is None


def test_parameter_number_out_of_bounds():
    spec = ParameterSpec(type="integer", minimum=16, maximum=30)
    assert "below minimum" in spec.check_value(10)
    assert "above maximum" in spec.check_value(100)


def test_parameter_wrong_type():
    spec = ParameterSpec(type="integer", minimum=16, maximum=30)
    assert "expected integer" in spec.check_value("warm")


def test_parameter_enum():
    spec = ParameterSpec(type="string", enum=["cool", "heat"])
    assert spec.check_value("cool") is None
    assert "not in allowed enum" in spec.check_value("turbo")


def test_parameter_required_missing():
    spec = ParameterSpec(type="integer", minimum=16, maximum=30, required=True)
    assert "required parameter missing" in spec.check_value(None)


def test_validate_parameters_rejects_unknown():
    cap = CapabilityDefinition(
        id="home.climate.turn_on",
        device_type="climate",
        parameters={"temperature": ParameterSpec(type="integer", minimum=16, maximum=30)},
    )
    errors = cap.validate_parameters({"temperature": 26, "hack": "x"})
    assert "hack" in errors
    assert "unknown parameter" in errors["hack"]


def test_validate_parameters_ok():
    cap = CapabilityDefinition(
        id="home.climate.turn_on",
        device_type="climate",
        parameters={"temperature": ParameterSpec(type="integer", minimum=16, maximum=30)},
    )
    assert cap.validate_parameters({"temperature": 26}) == {}


def test_registry_get_unknown_raises():
    reg = CapabilityRegistry()
    with pytest.raises(UnknownCapabilityError):
        reg.get("home.climate.turn_on")


def test_registry_list_sorted():
    reg = CapabilityRegistry()
    reg.register(CapabilityDefinition(id="b", device_type="x"))
    reg.register(CapabilityDefinition(id="a", device_type="x"))
    assert reg.list() == ["a", "b"]


def test_verification_level_order():
    from physical_agent.verification.evidence import VerificationEvidence
    ev = VerificationEvidence(
        correlation_id="c", capability_id="home.climate.turn_on", level=VerificationLevel.V2
    )
    assert ev.reached(VerificationLevel.V1)
    assert ev.reached(VerificationLevel.V2)
    assert not ev.reached(VerificationLevel.V3)
