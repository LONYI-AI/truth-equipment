"""Capability Model：所有物理动作必须被定义为 Capability。

对应 v3.0 §16 / §17。任何 HA entity 不得自动暴露给 LLM，
必须经 Adapter discovery → Capability Candidate → Policy classification
→ Allowlist → Capability Registry → Agent。
"""

from physical_agent.capability.registry import CapabilityRegistry, UnknownCapabilityError
from physical_agent.capability.request import CapabilityRequest
from physical_agent.capability.schema import (
    CapabilityDefinition,
    Operation,
    ParameterSpec,
    SideEffect,
    VerificationRequirement,
)

__all__ = [
    "CapabilityDefinition",
    "Operation",
    "ParameterSpec",
    "SideEffect",
    "VerificationRequirement",
    "CapabilityRequest",
    "CapabilityRegistry",
    "UnknownCapabilityError",
]
