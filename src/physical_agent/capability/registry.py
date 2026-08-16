"""CapabilityRegistry：已批准 capability 的注册表（v3.0 §17 / §35）。

只包含经 Allowlist 审查的 capability。未注册的 capability 一律拒绝。
"""

from __future__ import annotations

from physical_agent.capability.schema import CapabilityDefinition


class UnknownCapabilityError(KeyError):
    """请求了未注册的 capability。"""


class CapabilityRegistry:
    """线程安全的 capability 注册表（M0 为内存实现）。"""

    def __init__(self) -> None:
        self._defs: dict[str, CapabilityDefinition] = {}

    def register(self, definition: CapabilityDefinition) -> None:
        self._defs[definition.id] = definition

    def get(self, capability_id: str) -> CapabilityDefinition:
        try:
            return self._defs[capability_id]
        except KeyError:
            raise UnknownCapabilityError(
                f"capability {capability_id!r} is not registered"
            ) from None

    def list(self) -> list[str]:
        return sorted(self._defs)

    def __contains__(self, capability_id: str) -> bool:
        return capability_id in self._defs
