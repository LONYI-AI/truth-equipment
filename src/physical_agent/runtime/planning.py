"""M1A-W2 领域模型：MemoryContext / ReasoningRoute / ReasoningDecision / Plan。

设计约束（W2 REV2 授权）：
- 复用 M0 `CapabilityRequest`（不另造 ToolRequestV2 / ActionRequest 等重复类型）。
- 所有 Pydantic 模型 `extra="forbid"`（不接受任意额外安全相关字段）。
- Reason → Graph 路由用**无歧义的 typed contract**（`ReasoningRoute` 三态），
  不再使用单一 `bool` 同时表示「是否 actionable」与「是否需要 plan」。
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from physical_agent.capability.request import CapabilityRequest


class ReasoningRoute(StrEnum):
    """Reason → Graph 的路由状态（typed contract，三态无歧义）。

    - ``PLAN``：actionable，需要先经 `plan` 节点结构化为 `Plan`
      （planned actionable request）。
    - ``DIRECT``：actionable，直接进入 `policy_gate`（direct actionable request，
      显式保留 W1 direct path 语义）。
    - ``NOOP``：non-actionable / no-op，安全终态，**绝不**进入
      policy_gate / execute / verify。

    路由只依据本枚举；不得用「是否 actionable」的 bool 混同「是否需要 plan」。
    """

    PLAN = "plan"
    DIRECT = "direct"
    NOOP = "noop"


class PolicyRoute(StrEnum):
    """Policy → Graph 的路由状态（typed contract，派生自 M0 `PolicyDecision`）。

    - ``APPROVED``：allowed=True 且 requires_approval=False → execute boundary。
    - ``REJECTED``：allowed=False（或任何 fail-closed 判定）→ escalate / 安全终止。
    - ``NEEDS_APPROVAL``：allowed=True 且 requires_approval=True → human_review（挂起）。

    路由只依据本枚举，且**必须由本轮真实 `PolicyDecision` 确定性派生**：
    不得 LLM 决定、不得字符串猜测、不得缺失时默认 approved、不得异常时沿用旧 verdict。
    """

    APPROVED = "approved"
    REJECTED = "rejected"
    NEEDS_APPROVAL = "needs_approval"


class MemoryContext(BaseModel):
    """Recall 节点的检索结果（只读，session-scoped，bounded）。

    不把整个 MemoryStore 对象塞进状态；只承载本会话的 recent events + 配置的 preference keys。
    """

    model_config = ConfigDict(extra="forbid")

    events: list[dict[str, Any]] = Field(
        default_factory=list,
        description="本会话 recent events（按时间倒序，bounded）",
    )
    preferences: dict[str, Any] = Field(
        default_factory=dict,
        description="已配置的 preference key -> value",
    )


class ReasoningDecision(BaseModel):
    """Reason 节点的推理结果（严格模型）。

    - `route` 为 PLAN / DIRECT 时必须给出 capability_id；
    - `route` 为 NOOP 时不得携带 capability_id（不制造假 capability）。
    Reason 只负责推理提议，不做 Policy/风险判定/参数 clamp/execute。
    """

    model_config = ConfigDict(extra="forbid")

    route: ReasoningRoute = Field(
        default=ReasoningRoute.NOOP,
        description="无歧义路由状态（PLAN / DIRECT / NOOP）",
    )
    capability_id: str | None = Field(
        default=None,
        description="提议的 capability id（route 为 PLAN/DIRECT 时必填）",
    )
    device_id: str = Field(default="", description="目标设备")
    parameters: dict[str, Any] = Field(
        default_factory=dict,
        description="提议参数（**不 clamp**，参数合法性属 Policy Gate 职责）",
    )
    rationale: str = Field(default="", description="推理依据（供审计）")

    @property
    def is_actionable(self) -> bool:
        """派生属性：是否有可执行请求（PLAN / DIRECT）。

        仅用于一致性校验与可读性；**路由一律使用 `route`**，不依赖本 bool。
        """
        return self.route != ReasoningRoute.NOOP

    @model_validator(mode="after")
    def _check_route_consistency(self) -> ReasoningDecision:
        if self.is_actionable and not self.capability_id:
            raise ValueError("actionable reasoning (PLAN/DIRECT) requires capability_id")
        if not self.is_actionable and self.capability_id:
            raise ValueError("non-actionable reasoning (NOOP) must not carry capability_id")
        return self


class Plan(BaseModel):
    """Plan 节点的结构化计划。

    steps 直接复用 M0 `CapabilityRequest`（每个 step 正确绑定 capability_id /
    parameters / principal / device_id / correlation_id / reason）。
    """

    model_config = ConfigDict(extra="forbid")

    session_id: str
    correlation_id: str
    steps: list[CapabilityRequest] = Field(default_factory=list)
