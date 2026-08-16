"""VerificationEngine：把 Adapter 的执行证据转成 VerificationEvidence。"""

from __future__ import annotations

from physical_agent.capability.schema import VerificationLevel
from physical_agent.verification.evidence import VerificationEvidence


class VerificationEngine:
    """确定性验证引擎。

    根据 Adapter 返回的证据类型判定达到的 V 层级：
    - dispatch 成功 → V1
    - actuator output 证据 → V2
    - device acknowledgement 证据 → V3
    - physical effect 证据 → V4
    """

    def verify(
        self,
        *,
        correlation_id: str,
        capability_id: str,
        execution_evidence: dict,
    ) -> VerificationEvidence:
        level = VerificationLevel.V1  # 至少已派发

        if execution_evidence.get("actuation_observed"):
            level = VerificationLevel.V2
        if execution_evidence.get("device_evidence"):
            level = VerificationLevel.V3
        if execution_evidence.get("physical_effect_verified"):
            level = VerificationLevel.V4

        effect = execution_evidence.get("physical_effect", "pending")

        return VerificationEvidence(
            correlation_id=correlation_id,
            capability_id=capability_id,
            level=level,
            evidence=execution_evidence,
            physical_effect=effect,
        )
