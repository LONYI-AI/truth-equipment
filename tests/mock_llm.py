"""Mock LLM（M1A simulation）——确定性的 ReasoningModel 替身。

不调用真实 DeepSeek / OpenAI / Ollama / 互联网 / API key。
记录收到的输入（供测试断言 world_state / memory_context 被传入），
并按预定义序列返回 ReasoningDecision。
"""

from __future__ import annotations

from typing import Any

from physical_agent.runtime.base import UserIntent
from physical_agent.runtime.nodes.reason import ReasoningModel
from physical_agent.runtime.planning import MemoryContext, ReasoningDecision, ReasoningRoute
from physical_agent.runtime.state import WorldState


class MockReasoningModel(ReasoningModel):
    """确定性推理模型：预定义 responses 序列 + 输入记录。"""

    def __init__(self, responses: list[ReasoningDecision] | None = None) -> None:
        self._responses: list[ReasoningDecision] = list(responses or [])
        self._calls: list[dict[str, Any]] = []

    @property
    def calls(self) -> list[dict[str, Any]]:
        """每次 reason 调用收到的输入快照。"""
        return self._calls

    def reason(
        self,
        *,
        messages: list[Any],
        intent: UserIntent | None,
        world_state: WorldState | None,
        memory_context: MemoryContext | None,
    ) -> ReasoningDecision:
        self._calls.append(
            {
                "messages": list(messages),
                "intent": intent,
                "world_state": world_state,
                "memory_context": memory_context,
            }
        )
        if self._responses:
            return self._responses.pop(0)
        # 默认：non-actionable（NOOP），不制造假 capability
        return ReasoningDecision(route=ReasoningRoute.NOOP, rationale="mock default: non-actionable")
