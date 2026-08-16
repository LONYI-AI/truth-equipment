"""Verification 层：物理验证证据（v3.0 §22/§23）。"""

from physical_agent.verification.engine import VerificationEngine
from physical_agent.verification.evidence import VerificationEvidence

__all__ = ["VerificationEvidence", "VerificationEngine"]
