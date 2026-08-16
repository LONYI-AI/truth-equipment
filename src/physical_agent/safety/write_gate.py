"""WriteGate（M0.1 P0-3）：fail-closed 生产写执行闸门。

生产写执行仅当以下**全部**成立才允许：
1. 显式 AGENT_EXECUTION_ENABLED=true（缺失/false → fail-closed 拒绝）
2. policy 已加载
3. audit store 健康（哈希链已校验）
4. adapter allowlist 已加载
5. approval engine 健康（若 capability 需要审批）

只读观察不受此闸门限制。
"""

from __future__ import annotations

from dataclasses import dataclass

from physical_agent.adapters.registry import AdapterRegistry
from physical_agent.audit.store import AuditStore
from physical_agent.policy.approval import ApprovalEngine
from physical_agent.policy.engine import PolicyEngine
from physical_agent.policy.kill_switch import KillSwitch


@dataclass
class GateResult:
    allowed: bool
    reason: str


class WriteGate:
    """确定性写执行闸门（不依赖 LLM）。"""

    def __init__(
        self,
        *,
        kill_switch: KillSwitch,
        policy_engine: PolicyEngine,
        audit: AuditStore,
        adapters: AdapterRegistry,
        approval_engine: ApprovalEngine,
    ) -> None:
        self.kill_switch = kill_switch
        self.policy_engine = policy_engine
        self.audit = audit
        self.adapters = adapters
        self.approval_engine = approval_engine

    def check(self, *, needs_approval: bool) -> GateResult:
        # 1. 环境变量显式 true（fail-closed）
        if not self.kill_switch.env_explicitly_enabled:
            return GateResult(False, "AGENT_EXECUTION_ENABLED != true (fail-closed)")
        if self.kill_switch.is_active:
            return GateResult(False, "kill switch active")

        # 2. policy 已加载（registry 非空）
        if not self.policy_engine.is_policy_loaded:
            return GateResult(False, "policy not loaded")

        # 3. PHYSICAL mode requires persistent, verified, signed audit with
        # a runtime checkpoint policy; an in-memory audit is simulation-only.
        if not self.audit.is_physical_ready:
            return GateResult(False, "audit store not physically ready")

        # 4. adapter allowlist 已加载
        if not self.adapters.is_allowlist_loaded:
            return GateResult(False, "adapter allowlist not loaded")

        # 5. approval engine 健康（仅当需要审批时）
        if needs_approval and not self.approval_engine.is_healthy():
            return GateResult(False, "approval engine not healthy")

        return GateResult(True, "ok")
