"""M1A-W2 REV2 状态模型：AgentState（LangGraph 状态 schema）+ WorldState。

设计约束（W0.1 语义 + M1A-W1 授权 + W2 REV2 整改）：
- 复用 M0 `VerificationEvidence` 作为验证状态（不另造第二个 verification schema）。
- `messages` 用 LangGraph 官方 `add_messages` reducer（按消息 ID 去重/更新，非 list 拼接）。
- WorldState 的 `source` / `provenance` 用显式 Literal 类型并校验组合一致性。
- `observed_at` 用 timezone-aware datetime（拒绝空值/naive/malformed 时间）。
- 复用 M0 `UserIntent`（intent）、M0 `CapabilityRequest`（经 Plan.steps）。
- Reason → Graph 路由用 typed contract `ReasoningRoute`（非单一 bool）。
- 审批挂起边界保留 `approval_id` / `canonical_request_hash`（兼容 M0 `ApprovalRequest`）。
"""

from __future__ import annotations

from datetime import UTC, datetime
from operator import add
from typing import Annotated, Any, Literal, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from physical_agent.runtime.base import UserIntent
from physical_agent.runtime.planning import (
    MemoryContext,
    Plan,
    ReasoningDecision,
    ReasoningRoute,
)
from physical_agent.verification.evidence import VerificationEvidence

# 有限集合类型：source / provenance 是安全相关字段（路由/验证需区分模拟 vs 物理）。
Source = Literal["simulation", "physical", "memory"]
Provenance = Literal["simulated", "physical"]


class WorldState(BaseModel):
    """感知到的世界状态（设备 + 环境）。

    - `source`：状态来源（simulation / physical / memory）。
    - `provenance`：SIMULATED VERIFICATION EVIDENCE 语义；M1A 恒为 simulated，
      真实物理感知（M1B+）才会出现 physical。
    - `observed_at`：timezone-aware datetime，表达状态新旧（freshness）。
    """

    model_config = ConfigDict(extra="forbid")

    devices: dict[str, dict[str, Any]] = Field(
        default_factory=dict,
        description="设备状态表：device_id -> 状态字段",
    )
    environment: dict[str, Any] = Field(
        default_factory=dict,
        description="环境状态（温度/占用/时段等）",
    )
    observed_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="感知时间戳（timezone-aware，用于 freshness 判断）",
    )
    source: Source = Field(
        default="simulation",
        description="状态来源：simulation / physical / memory",
    )
    provenance: Provenance = Field(
        default="simulated",
        description="证据来源标记：M1A 为 simulated；physical 仅出现在真实感知（M1B+）",
    )

    @field_validator("observed_at")
    @classmethod
    def _require_tz_aware(cls, v: datetime) -> datetime:
        if v.tzinfo is None or v.utcoffset() is None:
            raise ValueError("observed_at must be timezone-aware (reject naive datetime)")
        return v

    @model_validator(mode="after")
    def _check_source_provenance(self) -> WorldState:
        if self.source == "simulation" and self.provenance != "simulated":
            raise ValueError("simulation source requires 'simulated' provenance")
        if self.source == "physical" and self.provenance != "physical":
            raise ValueError("physical source requires 'physical' provenance")
        # memory 来源可承载 simulated 或 physical，不锁死未来 M1B+ 模型
        return self


class AgentState(TypedDict, total=False):
    """LangGraph 状态 schema（M1A-W2 REV2，架构级概念，见 ARCHITECTURE.md §2.1）。

    这是 graph 内部状态，不是 M0 `AgentResult` 的重复定义；M0 `AgentRuntime`
    协议（run/resume/cancel）保持不变。除架构字段外，附带**已论证的路由信号**
    （`route`、`policy_verdict`）与审批挂起元数据，均非验收专用字段。
    """

    # 会话消息（官方 add_messages reducer：按 ID 去重/更新，非 list 拼接）
    messages: Annotated[list[AnyMessage], add_messages]
    # 用户意图（复用 M0 UserIntent）
    intent: UserIntent | None
    # 当前感知的世界状态
    world_state: WorldState | None
    # 记忆检索上下文（Recall 输出）
    memory_context: MemoryContext | None
    # 推理决策（Reason 输出）
    reasoning: ReasoningDecision | None
    # 当前计划（Plan 输出，复用 M0 CapabilityRequest）
    current_plan: Plan | None
    # 执行历史（accumulate：append 语义）
    execution_history: Annotated[list[dict[str, Any]], add]
    # 验证结果：复用 M0 冻结的 VerificationEvidence（含 level / evidence / physical_effect）
    verification: VerificationEvidence | None
    # 会话 / 追踪
    session_id: str
    correlation_id: str
    # 重试计数（verify 失败时由上游节点维护，路由据此判断 retry vs compensate）
    retry_count: int
    # 是否需要人工审批（approval 挂起边界）
    needs_human_review: bool
    # 审批挂起边界元数据（兼容 M0 ApprovalRequest，供 W3 resume 使用）
    approval_id: str | None
    canonical_request_hash: str | None
    # —— 以下为 graph 路由信号（生产路由需要，非验收专用）——
    # Reason → Graph 路由状态（typed contract）：
    #   PLAN → plan 节点；DIRECT → policy_gate；NOOP/缺失 → 安全终态（END）
    route: ReasoningRoute
    # policy_gate 判定结果：approved / rejected / needs_approval
    policy_verdict: str
