"""AdapterRegistry（M0.1 P0-7）：capability 命名空间 → approved adapter 路由。

映射：home.* → HomeAssistantAdapter；computer.* → ComputerAdapter；
mobile.* → MobileAdapter；camera.* → CameraAdapter。

Runtime 不得看到 AdapterRegistry 实例；Capability Gateway 独占 routing。
"""

from __future__ import annotations

from dataclasses import dataclass

from physical_agent.adapters.base import DeviceAdapter, ExecutionDomain
from physical_agent.execution.state_machine import ExecutionMode


class UnknownNamespaceError(KeyError):
    """capability 命名空间未映射到任何 adapter。"""


@dataclass(frozen=True)
class AdapterRegistration:
    """Explicit adapter execution domain; never infer it from adapter type."""

    adapter: DeviceAdapter
    execution_domain: ExecutionDomain

    def allows(self, mode: ExecutionMode) -> bool:
        return (
            self.execution_domain is ExecutionDomain.BOTH
            or (mode is ExecutionMode.SIMULATION and self.execution_domain is ExecutionDomain.SIMULATION_ONLY)
            or (mode is ExecutionMode.PHYSICAL and self.execution_domain is ExecutionDomain.PHYSICAL_ONLY)
        )


class AdapterRegistry:
    """命名空间 → adapter 路由表。"""

    def __init__(self) -> None:
        self._routes: dict[str, AdapterRegistration] = {}
        self._loaded = False

    def register(
        self,
        namespace: str,
        adapter: DeviceAdapter,
        *,
        execution_domain: ExecutionDomain,
    ) -> None:
        """Register an adapter with an explicit, fail-closed execution domain."""
        self._routes[namespace] = AdapterRegistration(adapter, execution_domain)

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
        return self.registration(capability_id).adapter

    def registration(self, capability_id: str) -> AdapterRegistration:
        ns = self._namespace_of(capability_id)
        registration = self._routes.get(ns)
        if registration is None:
            raise UnknownNamespaceError(
                f"no adapter registered for namespace {ns!r}"
            )
        return registration

    def allows(self, capability_id: str, mode: ExecutionMode) -> bool:
        """Whether the registered adapter is explicitly permitted in ``mode``."""
        return self.registration(capability_id).allows(mode)

    def namespaces(self) -> list[str]:
        return sorted(self._routes)
