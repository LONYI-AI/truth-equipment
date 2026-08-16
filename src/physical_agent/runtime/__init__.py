"""Runtime 层：统一 AgentRuntime 接口（v3.0 §9）。"""

from physical_agent.runtime.base import (
    AgentResult,
    AgentRuntime,
    RuntimeCapabilities,
    RuntimeContext,
    RuntimeEvent,
    UserIntent,
)
from physical_agent.runtime.deepseek_harness import DeepSeekHarnessRuntime
from physical_agent.runtime.langgraph import LangGraphRuntime
from physical_agent.runtime.mock import MockRuntime

__all__ = [
    "UserIntent",
    "RuntimeContext",
    "RuntimeEvent",
    "AgentResult",
    "AgentRuntime",
    "RuntimeCapabilities",
    "MockRuntime",
    "LangGraphRuntime",
    "DeepSeekHarnessRuntime",
]
