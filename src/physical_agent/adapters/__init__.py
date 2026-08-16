"""Adapter 层：统一设备适配（v3.0 §24/§25）。"""

from physical_agent.adapters.base import (
    Device,
    DeviceAdapter,
    DeviceState,
    ExecutionDomain,
    ExecutionEvidence,
)
from physical_agent.adapters.mock import MockAdapter, MockDevice
from physical_agent.adapters.registry import AdapterRegistration, AdapterRegistry, UnknownNamespaceError

__all__ = [
    "Device",
    "DeviceState",
    "DeviceAdapter",
    "ExecutionDomain",
    "ExecutionEvidence",
    "MockDevice",
    "MockAdapter",
    "AdapterRegistry",
    "AdapterRegistration",
    "UnknownNamespaceError",
]
