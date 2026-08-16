"""Safety Kernel：Capability Gateway + WriteGate（v3.0 §15，项目最重要组件）。"""

from physical_agent.safety.gateway import CapabilityGateway
from physical_agent.safety.write_gate import GateResult, WriteGate

__all__ = ["CapabilityGateway", "WriteGate", "GateResult"]
