"""M1A-W4 Verify 节点：把 Execute 的 gateway outcome 转成 M0 `VerificationEvidence`。

设计约束（W4 授权）：
- **成功语义 = capability.required_verification_level 是否达到**，不要求
  `physical_effect == "confirmed"`。`status == "completed"`（gateway 判定
  `VerificationEvidence.reached(required)`）即 satisfied。
- **V2 不得冒充 V4**：`physical_effect` 原样保留（V2 → "pending"），路由用独立
  信号 `verification_satisfied`，不伪造 `physical_effect="confirmed"` 让路由通过。
- 所有模拟 VerificationEvidence 明确带 `evidence["provenance"] == "simulated"`。
- 复用 M0 `VerificationEvidence` / `VerificationLevel`，不重建验证 schema。
"""

from __future__ import annotations

from typing import Any

from physical_agent.capability.schema import VerificationLevel
from physical_agent.runtime.graph import NodeHandler
from physical_agent.runtime.state import AgentState
from physical_agent.verification.evidence import VerificationEvidence


def make_verify_handler() -> NodeHandler:
    """构造 Verify handler（sync：仅做 outcome → VerificationEvidence 的确定性映射）。"""

    def verify(state: AgentState) -> dict[str, Any]:
        outcome = state.get("execution_outcome") or {}
        status = outcome.get("status")
        level_raw = outcome.get("verification_level", "V1")
        physical_effect = outcome.get("physical_effect", "pending")
        correlation_id = outcome.get("correlation_id") or state.get("correlation_id", "")

        request = state.get("current_request")
        capability_id = (
            request.capability_id if request is not None else outcome.get("capability_id", "")
        )

        # 达到 required_level（gateway 已判定 reached(required)）即 satisfied；
        # physical_effect 保持真实值（pending/confirmed），绝不伪造 confirmed。
        satisfied = status == "completed"

        verification = VerificationEvidence(
            correlation_id=correlation_id,
            capability_id=capability_id,
            level=VerificationLevel(level_raw),
            evidence={"provenance": "simulated", "execution": outcome},
            physical_effect=physical_effect,
        )

        return {
            "verification": verification,
            "verification_satisfied": satisfied,
        }

    return verify
