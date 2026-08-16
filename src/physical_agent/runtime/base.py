"""AgentRuntime 协议与基础类型（v3.0 §9 + M0.1 P0-2）。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field


@dataclass(frozen=True)
class RuntimeCapabilities:
    """Runtime 实际能力声明（M0.1 P0-2）。

    不假设任何 framework 原生支持 resume/cancel。每个 runtime 必须显式声明。
    """

    native_resume: bool = False
    native_cancel: bool = False
    persistent_session_recovery: bool = False
    streaming: bool = False
    tool_bridge: bool = False

    def summary(self) -> dict[str, bool]:
        return {
            "native_resume": self.native_resume,
            "native_cancel": self.native_cancel,
            "persistent_session_recovery": self.persistent_session_recovery,
            "streaming": self.streaming,
            "tool_bridge": self.tool_bridge,
        }


class UserIntent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    principal: str = "human"
    session_id: str = ""


class RuntimeContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    correlation_id: str
    session_id: str = ""
    # 感知/风险上下文（供 Policy 使用）
    location: str = "home"
    time_of_day: str = "day"
    occupancy: str = "occupied"
    environment: str = "normal"


class RuntimeEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_type: str
    payload: dict[str, Any] = Field(default_factory=dict)


class AgentResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str
    correlation_id: str
    status: str  # completed / rejected / failed / cancelled / needs_approval
    capabilities: list[dict[str, Any]] = Field(default_factory=list)
    message: str = ""
    evidence: dict[str, Any] = Field(default_factory=dict)


@runtime_checkable
class AgentRuntime(Protocol):
    def capabilities(self) -> RuntimeCapabilities: ...

    async def run(self, intent: UserIntent, context: RuntimeContext) -> AgentResult: ...

    async def resume(self, session_id: str, event: RuntimeEvent) -> AgentResult: ...

    async def cancel(self, session_id: str) -> None: ...
