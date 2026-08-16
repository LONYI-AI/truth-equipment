"""CapabilityRequest：一次 capability 调用的结构化请求。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class CapabilityRequest(BaseModel):
    """Agent 发出的能力请求。永远不直接触发物理动作，
    必须经 Policy Engine / Capability Gateway 审批。"""

    model_config = ConfigDict(extra="forbid")

    capability_id: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    principal: str = Field(
        default="agent",
        description="触发者身份（agent / automation / human）",
    )
    device_id: str = Field(default="", description="目标设备（只读/多设备时使用）")
    correlation_id: str = Field(description="全链路追踪 ID")
    reason: str = Field(default="", description="意图/理由（供审计）")
