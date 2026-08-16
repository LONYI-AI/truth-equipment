"""Capability 定义与参数 schema（v3.0 §16）。"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class VerificationLevel(StrEnum):
    """物理验证层级（v3.0 §22）。"""

    V0 = "V0"  # Request Accepted
    V1 = "V1"  # Command Dispatched
    V2 = "V2"  # Actuation Observed
    V3 = "V3"  # Device Evidence
    V4 = "V4"  # Physical Effect Verified


class ParameterSpec(BaseModel):
    """单个参数的约束定义。"""

    model_config = ConfigDict(extra="forbid")

    type: Literal["number", "integer", "string", "boolean"] = Field(
        description="参数类型"
    )
    minimum: float | int | None = None
    maximum: float | int | None = None
    enum: list[Any] | None = None
    required: bool = True
    description: str = ""

    def check_value(self, value: Any) -> str | None:
        """校验单个值，返回错误信息；合法则返回 None。"""
        if value is None:
            if self.required:
                return "required parameter missing"
            return None

        if self.type == "number" or self.type == "integer":
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                return f"expected {self.type}, got {type(value).__name__}"
            if self.type == "integer" and isinstance(value, float):
                return "expected integer, got float"
            if self.minimum is not None and value < self.minimum:
                return f"value {value} below minimum {self.minimum}"
            if self.maximum is not None and value > self.maximum:
                return f"value {value} above maximum {self.maximum}"

        if self.type == "string" and not isinstance(value, str):
            return f"expected string, got {type(value).__name__}"

        if self.type == "boolean" and not isinstance(value, bool):
            return f"expected boolean, got {type(value).__name__}"

        if self.enum is not None and value not in self.enum:
            return f"value {value!r} not in allowed enum {self.enum}"

        return None


class VerificationRequirement(BaseModel):
    """动作要求达到的最低验证层级。"""

    model_config = ConfigDict(extra="forbid")

    required_level: VerificationLevel = VerificationLevel.V2


class SideEffect(StrEnum):
    """副作用类型（M0.1 P0-9）。与风险等级分离，独立表示。"""

    NONE = "none"                      # 无副作用（只读/观察）
    REVERSIBLE_WRITE = "reversible_write"
    IRREVERSIBLE_WRITE = "irreversible_write"


class Operation(StrEnum):
    """操作类型（M0.1 P0-9）。"""

    OBSERVE = "observe"
    EXECUTE = "execute"


class CapabilityDefinition(BaseModel):
    """一个 Capability 的完整定义（v3.0 §16 + M0.1 P0-9）。"""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(description="如 home.climate.set_temperature")
    device_type: str = Field(description="如 climate / light / computer")
    parameters: dict[str, ParameterSpec] = Field(default_factory=dict)
    risk: dict[str, int] = Field(default_factory=lambda: {"default": 1})
    verification: VerificationRequirement = Field(
        default_factory=VerificationRequirement
    )
    # 副作用与操作类型：安全属性不得由 risk tier 整数隐式推断（P0-9）
    side_effect: SideEffect = SideEffect.REVERSIBLE_WRITE
    operation: Operation = Operation.EXECUTE

    @property
    def default_risk_tier(self) -> int:
        return self.risk.get("default", 1)

    @property
    def is_read_only(self) -> bool:
        """只读 = 无副作用（显式声明，不依赖 risk tier）。"""
        return self.side_effect == SideEffect.NONE

    def validate_parameters(self, parameters: dict[str, Any]) -> dict[str, str]:
        """校验参数字典，返回 {参数名: 错误信息}；空字典表示全部合法。"""
        errors: dict[str, str] = {}
        # 未知参数一律拒绝（fail-closed）
        for key in parameters:
            if key not in self.parameters:
                errors[key] = f"unknown parameter {key!r}"

        for name, spec in self.parameters.items():
            err = spec.check_value(parameters.get(name))
            if err is not None:
                errors[name] = err
        return errors
