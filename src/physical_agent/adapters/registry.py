"""AdapterRegistry（M0.1 P0-7）：capability 命名空间 → approved adapter 路由。

映射：home.* → HomeAssistantAdapter；computer.* → ComputerAdapter；
mobile.* → MobileAdapter；camera.* → CameraAdapter。

Runtime 不得看到 AdapterRegistry 实例；Capability Gateway 独占 routing。
"""

from __future__ import annotations

from physical_agent.adapters.base import DeviceAdapter


class UnknownNamespaceError(KeyError):
    """capability 命名空间未映射到任何 adapter。"""


class AdapterRegistry:
    """命名空间 → adapter 路由表。"""

    def __init__(self) -> None:
        self._routes: dict[str, DeviceAdapter] = {}
        self._loaded = False

    def register(self, namespace: str, adapter: DeviceAdapter) -> None:
        """注册一个命名空间（如 'home'、'computer'）到 adapter。"""
        self._routes[namespace] = adapter

    def mark_loaded(self) -> None:
        self._loaded = True

    @property
    def is_allowlist_loaded(self) -> bool:
        return self._loaded and bool(self._routes)

    @staticmethod
    def _namespace_of(capability_id: str) -> str:
        # home.climate.turn_on → "home"
        return capability_id.split(".", 1)[0]

    def route(self, capability_id: str) -> DeviceAdapter:
        ns = self._namespace_of(capability_id)
        adapter = self._routes.get(ns)
        if adapter is None:
            raise UnknownNamespaceError(
                f"no adapter registered for namespace {ns!r}"
            )
        return adapter

    def namespaces(self) -> list[str]:
        return sorted(self._routes)
