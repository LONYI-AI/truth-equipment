"""M1A-W4 Execute 节点：经 CapabilityGateway.execute_authorized_simulation 派发。

设计约束（W4 授权）：
- **SIMULATION-only**：只调用 `CapabilityGateway.execute_authorized_simulation`
  （该入口硬性保证 mode != SIMULATION → REJECT，绝不触碰 PHYSICAL adapter）。
- 复用 M0 安全链路：Gateway → Adapter → VerificationEngine → Coordinator → Audit，
  不重建第二套执行/验证，不直连设备。
- 读 `state.current_request`（本轮 canonical CapabilityRequest，W3 policy_gate 产出）
  与 `state.policy_decision`（本轮真实 M0 PolicyDecision），二者缺失 → fail-closed。
- 不实现 retry/compensate 业务；执行结果写 `execution_outcome` 供 Verify 消费。
"""

from __future__ import annotations

from typing import Any

from physical_agent.runtime.graph import NodeHandler
from physical_agent.runtime.state import AgentState
from physical_agent.safety.gateway import CapabilityGateway


def make_execute_handler(gateway: CapabilityGateway) -> NodeHandler:
    """构造 Execute handler（async：gateway 派发为 async）。

    fail-closed：缺 canonical request 或 policy_decision 时不执行，写 rejected outcome
    （路由到 verify → verification_satisfied=False → retry/compensate，绝不静默成功）。
    """

    async def execute(state: AgentState) -> dict[str, Any]:
        request = state.get("current_request")
        decision = state.get("policy_decision")
        if request is None or decision is None:
            return {
                "execution_outcome": {
                    "status": "rejected",
                    "reason": "missing canonical request or policy decision",
                },
            }

        outcome = await gateway.execute_authorized_simulation(request, decision)
        return {
            "execution_outcome": outcome,
            "execution_history": [outcome],
        }

    return execute
