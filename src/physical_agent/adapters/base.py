"""DeviceAdapter 协议与基础类型（v3.0 §24）。"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field


class Device(BaseModel):
    model_config = ConfigDict(extra="forbid")

    device_id: str
    device_type: str
    capabilities: list[str] = Field(default_factory=list)


class DeviceState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    device_id: str
    state: dict[str, Any] = Field(default_factory=dict)
    available: bool = True


class ExecutionEvidence(BaseModel):
    """Adapter 执行后的证据（供 VerificationEngine 消费）。"""

    model_config = ConfigDict(extra="forbid")

    correlation_id: str
    dispatched: bool = False
    actuation_observed: bool = False          # V2：执行器输出被观测
    device_evidence: bool = False              # V3：目标设备确认
    physical_effect_verified: bool = False     # V4：物理效果
    physical_effect: str = "pending"
    detail: dict[str, Any] = Field(default_factory=dict)


class ExecutionDomain(StrEnum):
    """The only execution environments an adapter registration may permit."""

    SIMULATION_ONLY = "simulation_only"
    PHYSICAL_ONLY = "physical_only"
    BOTH = "both"


@runtime_checkable
class DeviceAdapter(Protocol):
    """统一设备适配接口。"""

    async def discover(self) -> list[Device]: ...

    async def observe(self, device_id: str) -> DeviceState: ...

    async def execute(self, request: Any) -> ExecutionEvidence: ...

    async def verify(self, execution: ExecutionEvidence) -> ExecutionEvidence: ...
