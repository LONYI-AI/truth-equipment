"""M1A-W5（Integration Hardening）ReasoningModel provider：可配置的确定性推理提供方。

设计约束：
- 实现 `ReasoningModel` 契约（见 `runtime/nodes/reason.py`），**不把 LLM 写死在业务节点**：
  Reason 节点只依赖注入的 `ReasoningModel` Protocol；生产第一版提供一个**可配置的**
  确定性 provider（`RuleBasedReasoningModel`），测试继续注入 `MockReasoningModel`。
- 本 provider 是 M1A Simulation 的确定性 NL→ReasoningDecision 映射（非真实 LLM）。
  真实 DeepSeek / OpenAI / Ollama 属后续 M1B+ hardening，不在此轮引入。
- 无法匹配任何规则 → `ReasoningDecision(route=NOOP)`（non-actionable 安全终态），
  绝不臆造 capability、绝不进 policy/execute。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from physical_agent.runtime.base import UserIntent
from physical_agent.runtime.planning import MemoryContext, ReasoningDecision, ReasoningRoute
from physical_agent.runtime.state import WorldState

# 温度提取：优先匹配「数字 + 温度单位」，否则裸数字（保守提取，边界交由 Policy Gate 校验）
_TEMP_DEGREE_RE = re.compile(r"(\d+)\s*(?:度|℃|°C|°c|°F|°f)")
_TEMP_BARE_RE = re.compile(r"(\d+)")

# 模式识别（空调）
_MODE_MAP: dict[str, str] = {
    "制冷": "cool",
    "制热": "heat",
    "除湿": "dry",
    "送风": "fan_only",
    "cool": "cool",
    "heat": "heat",
}

_DEFAULT_TEMPERATURE = 26
_DEFAULT_MODE = "cool"


@dataclass(frozen=True)
class ReasoningRule:
    """一条确定性推理规则：关键词 → capability + 要提取的参数键。"""

    capability_id: str
    device_id: str
    keywords: tuple[str, ...]
    param_keys: tuple[str, ...] = ()


def default_ac_rules() -> list[ReasoningRule]:
    """M1A Simulation 默认规则集（空调场景，可被调用方覆盖/替换）。"""
    return [
        # 关闭空调（无需审批，risk=1）
        ReasoningRule(
            capability_id="home.climate.turn_off",
            device_id="climate.bedroom_ac",
            keywords=("关空调", "关闭空调", "关冷气", "关机", "turn off"),
        ),
        # 打开 / 调到指定温度（需审批，risk=2）：turn_on 携带 temperature + mode
        ReasoningRule(
            capability_id="home.climate.turn_on",
            device_id="climate.bedroom_ac",
            keywords=(
                "开空调", "打开空调", "制冷", "制热", "调", "设", "温度",
                "turn on", "set to", "set temperature",
            ),
            param_keys=("temperature", "mode"),
        ),
    ]


def extract_temperature(text: str) -> int:
    """从自然语言提取目标温度（默认 26）。"""
    m = _TEMP_DEGREE_RE.search(text)
    if m is None:
        m = _TEMP_BARE_RE.search(text)
    if m is None:
        return _DEFAULT_TEMPERATURE
    return int(m.group(1))


def extract_mode(text: str) -> str:
    """从自然语言提取空调模式（默认 cool）。"""
    lower = text.lower()
    for key, mode in _MODE_MAP.items():
        if key in lower:
            return mode
    return _DEFAULT_MODE


class RuleBasedReasoningModel:
    """可配置的确定性 ReasoningModel provider（M1A Simulation 第一版）。

    - `rules`：规则列表（按顺序匹配，首个命中生效）；缺省用 `default_ac_rules()`。
    - `reason()`：把 `intent.text` 映射为 `ReasoningDecision(route=PLAN)`；
      无命中 → NOOP（安全终态）。
    - 参数提取是确定性的（非 LLM）：temperature / mode；参数合法性交由 Policy Gate 校验，
      本 provider **不 clamp**（与 Reason 节点契约一致）。
    """

    def __init__(self, rules: list[ReasoningRule] | None = None) -> None:
        self._rules: list[ReasoningRule] = list(rules) if rules is not None else default_ac_rules()

    @property
    def rules(self) -> list[ReasoningRule]:
        return list(self._rules)

    def reason(
        self,
        *,
        messages: list[Any],
        intent: UserIntent | None,
        world_state: WorldState | None,
        memory_context: MemoryContext | None,
    ) -> ReasoningDecision:
        if intent is None or not intent.text:
            return ReasoningDecision(route=ReasoningRoute.NOOP, rationale="empty intent")

        text = intent.text
        lower = text.lower()
        for rule in self._rules:
            if not any(kw in lower for kw in rule.keywords):
                continue

            params: dict[str, Any] = {}
            if "temperature" in rule.param_keys:
                params["temperature"] = extract_temperature(text)
            if "mode" in rule.param_keys:
                params["mode"] = extract_mode(text)

            return ReasoningDecision(
                route=ReasoningRoute.PLAN,
                capability_id=rule.capability_id,
                device_id=rule.device_id,
                parameters=params,
                rationale=text,
            )

        # 无命中：non-actionable 安全终态
        return ReasoningDecision(route=ReasoningRoute.NOOP, rationale="no matching rule")
