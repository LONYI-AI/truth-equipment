"""验证证据模型（v3.0 §22/§23）。

关键语义：IR 回读（V2）只能证明"执行器输出信号"，不能证明设备执行（V3/V4）。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from physical_agent.capability.schema import VerificationLevel


class VerificationEvidence(BaseModel):
    """一次物理验证的证据。带样本量与置信信息（禁止未实测数字）。"""

    model_config = ConfigDict(extra="forbid")

    correlation_id: str
    capability_id: str
    level: VerificationLevel = Field(
        description="达到的最高验证层级 V0-V4"
    )
    evidence: dict[str, Any] = Field(
        default_factory=dict,
        description="各层级证据，含 sample_size/conditions/FPR/FNR/CI（如有实测）",
    )
    physical_effect: str = Field(
        default="pending",
        description="物理效果结论：pending / confirmed / failed / inconclusive",
    )
    timestamp: str = Field(
        default_factory=lambda: datetime.now(UTC).isoformat()
    )

    def reached(self, required: VerificationLevel) -> bool:
        """是否达到所需层级。"""
        order = ["V0", "V1", "V2", "V3", "V4"]
        return order.index(self.level.value) >= order.index(required.value)
