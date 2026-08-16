"""风险模型（v3.0 §18/§19）。

Risk = f(principal, device, capability, parameters,
         location, time, occupancy, historical_state, environment)。
"""

from __future__ import annotations

from enum import IntEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class RiskTier(IntEnum):
    """风险等级（v3.0 §19）。数值越大越危险。"""

    READ_ONLY = 0          # 只读
    LOW_REVERSIBLE = 1     # 低风险、参数受限的可逆动作
    SIGNIFICANT = 2        # 重要设备状态变化
    SAFETY_SENSITIVE = 3   # 安全敏感动作（默认人工确认）


class RiskContext(BaseModel):
    """风险判定所需的上下文。缺省值均为"安全/正常"。"""

    model_config = ConfigDict(extra="forbid")

    principal: str = "agent"
    device: str = ""
    capability_id: str = ""
    parameters: dict[str, Any] = Field(default_factory=dict)
    location: str = "home"
    time_of_day: str = "day"          # day / night
    occupancy: str = "occupied"       # occupied / away / unknown
    historical_state: str = "normal"  # normal / rapid_cycling / unknown
    environment: str = "normal"       # normal / abnormal


def classify_risk(
    *,
    default_tier: int,
    context: RiskContext,
    override_rules: list[tuple[RiskTier, bool]] | None = None,
) -> tuple[RiskTier, str]:
    """根据上下文计算最终风险等级。

    规则（确定性，非 LLM）：
    - 连续快速启停（historical_state=rapid_cycling）→ 升到 SAFETY_SENSITIVE
    - 陌生 principal 控制安全敏感设备 → SAFETY_SENSITIVE
    - 异常环境 / 无人外出 + 重要设备 → SIGNIFICANT 起
    - 其余沿用 capability 默认等级

    返回 (最终等级, 原因)。
    """
    tier = RiskTier(default_tier)
    reasons: list[str] = []

    # 快速启停防护（压缩机保护）
    if context.historical_state == "rapid_cycling":
        return RiskTier.SAFETY_SENSITIVE, "rapid cycling detected"

    # 陌生主体 + 安全敏感
    if context.principal not in ("human", "automation", "agent") and tier >= RiskTier.SIGNIFICANT:
        return RiskTier.SAFETY_SENSITIVE, "unknown principal on significant action"

    # 无人/外出 + 重要设备状态变化
    if context.occupancy == "away" and tier >= RiskTier.SIGNIFICANT:
        reasons.append("occupancy=away")

    # 异常环境
    if context.environment == "abnormal":
        reasons.append("environment=abnormal")

    # 深夜 + 重要设备
    if context.time_of_day == "night" and tier >= RiskTier.SIGNIFICANT:
        reasons.append("time_of_day=night")

    if reasons and tier < RiskTier.SIGNIFICANT:
        tier = RiskTier.SIGNIFICANT
    elif reasons:
        tier = RiskTier.SAFETY_SENSITIVE

    if override_rules:
        for rule_tier, _flag in override_rules:
            if rule_tier > tier:
                tier = rule_tier

    reason = ", ".join(reasons) if reasons else "default"
    return tier, reason
