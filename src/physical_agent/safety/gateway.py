"""CapabilityGateway：Physical Safety Kernel 的入口（v3.0 §15 + M0.1 整改）。

组合：CapabilityRegistry + PolicyEngine + WriteGate + ApprovalEngine
+ AdapterRegistry(routing) + ExecutionCoordinator + VerificationEngine + AuditStore。

**不依赖 LLM。** 任何物理动作必须经此网关。
"""

from __future__ import annotations

import uuid
from typing import Any

from physical_agent.adapters.registry import AdapterRegistry, UnknownNamespaceError
from physical_agent.audit.store import AuditStore
from physical_agent.capability.registry import CapabilityRegistry, UnknownCapabilityError
from physical_agent.capability.request import CapabilityRequest
from physical_agent.execution.coordinator import ExecutionCoordinator
from physical_agent.execution.state_machine import ExecutionMode, ExecutionState
from physical_agent.policy.approval import ApprovalEngine
from physical_agent.policy.engine import PolicyEngine
from physical_agent.policy.kill_switch import KillSwitch
from physical_agent.policy.risk import RiskContext
from physical_agent.safety.write_gate import WriteGate
from physical_agent.verification.engine import VerificationEngine


class CapabilityGateway:
    """Safety Kernel 编排入口（M0.1 完整版）。

    `mode`（P0-1 强化）：SIMULATION 派发到 mock 适配器且跳过 fail-closed 写闸门；
    PHYSICAL（默认，安全）派发到真实适配器并强制 fail-closed 写闸门。
    """

    def __init__(
        self,
        registry: CapabilityRegistry,
        adapters: AdapterRegistry,
        *,
        mode: ExecutionMode = ExecutionMode.PHYSICAL,
        policy_engine: PolicyEngine | None = None,
        kill_switch: KillSwitch | None = None,
        audit: AuditStore | None = None,
        verifier: VerificationEngine | None = None,
        coordinator: ExecutionCoordinator | None = None,
        approval_engine: ApprovalEngine | None = None,
    ) -> None:
        self.registry = registry
        self.adapters = adapters
        self.mode = mode
        self.kill_switch = kill_switch or KillSwitch()
        self.policy = policy_engine or PolicyEngine(registry, self.kill_switch)
        self.audit = audit or AuditStore()
        if self.mode == ExecutionMode.PHYSICAL and not self.audit.is_persistent_configured:
            raise ValueError("PHYSICAL mode requires AuditStore(path=...); memory audit is simulation-only")
        self.verifier = verifier or VerificationEngine()
        self.coordinator = coordinator or ExecutionCoordinator(mode=mode)
        self.approval = approval_engine or ApprovalEngine()
        self.write_gate = WriteGate(
            kill_switch=self.kill_switch,
            policy_engine=self.policy,
            audit=self.audit,
            adapters=self.adapters,
            approval_engine=self.approval,
        )

    # ---- 主执行入口 ----

    async def execute(
        self,
        request: CapabilityRequest,
        context: RiskContext | None = None,
    ) -> dict[str, Any]:
        """执行一次 capability 请求（完整 Safety Kernel 链路）。"""
        # 幂等/重放防护（P0-8）
        if self.coordinator.has(request.correlation_id):
            return {"status": "rejected", "reason": f"duplicate correlation_id {request.correlation_id!r}"}

        # Do not attempt an audit append that an unhealthy store must reject.
        # PHYSICAL operation has no safe degraded/auditless mode.
        if self.mode == ExecutionMode.PHYSICAL and not self.audit.is_physical_ready:
            return {"status": "rejected", "reason": "audit store not physically ready"}

        self.audit.append(
            "capability_requested", request.correlation_id,
            {"capability_id": request.capability_id, "principal": request.principal,
             "execution_mode": self.mode.value},
        )

        # 1. 注册 + policy
        try:
            decision = self.policy.evaluate(request, context)
            definition = self.registry.get(request.capability_id)
        except UnknownCapabilityError as exc:
            self.audit.append("capability_rejected", request.correlation_id, {"reason": str(exc)})
            return {"status": "rejected", "reason": str(exc)}

        self.audit.append(
            "policy_evaluated", request.correlation_id,
            {"tier": int(decision.tier), "allowed": decision.allowed,
             "requires_approval": decision.requires_approval, "reason": decision.reason},
        )

        if not decision.allowed:
            return {"status": "rejected", "reason": decision.reason}

        # 2. 审批（P0-4）：需要审批 → 生成 ApprovalRequest，进入 NEEDS_APPROVAL
        if decision.requires_approval:
            ar = self.approval.request_approval(request, int(decision.tier))
            self.coordinator.begin(request, decision)  # -> NEEDS_APPROVAL
            self.audit.append("needs_approval", request.correlation_id,
                              {"approval_id": ar.approval_id, "tier": int(decision.tier)})
            return {
                "status": "needs_approval",
                "approval_id": ar.approval_id,
                "tier": int(decision.tier),
                "reason": decision.reason,
                "correlation_id": request.correlation_id,
            }

        # 3. 写执行闸门（P0-3 fail-closed）：仅 PHYSICAL 模式需要；SIMULATION 不接触真实设备
        if not definition.is_read_only and self.mode == ExecutionMode.PHYSICAL:
            gate = self.write_gate.check(needs_approval=False)
            if not gate.allowed:
                self.audit.append("write_blocked", request.correlation_id, {"reason": gate.reason})
                return {"status": "rejected", "reason": gate.reason}

        return await self._dispatch(request, definition, decision)

    def approve(self, approval_id: str, approver: str = "owner") -> str:
        """人工授予审批（P0-4）。创建一次性 ApprovalGrant。返回 approval_id。"""
        grant = self.approval.grant(approval_id, approver=approver)
        self.audit.append("approval_granted", grant.approval_id,
                          {"approver": approver})
        return approval_id

    async def execute_approved(
        self,
        request: CapabilityRequest,
        approval_id: str,
        context: RiskContext | None = None,
    ) -> dict[str, Any]:
        """审批通过后执行（P0-4）：消费一次性 ApprovalGrant。"""
        definition = self.registry.get(request.capability_id)
        decision = self.policy.evaluate(request, context)

        # 消费审批（校验单次使用/过期/参数绑定/重放）
        try:
            self.approval.consume(approval_id, request, int(decision.tier))
        except Exception as exc:  # ApprovalError
            self.audit.append("approval_rejected", request.correlation_id, {"reason": str(exc)})
            return {"status": "rejected", "reason": str(exc)}

        # 推进 NEEDS_APPROVAL -> APPROVED -> AUTHORIZED
        self.coordinator.approve(request.correlation_id)
        self.audit.append("approved", request.correlation_id, {"approval_id": approval_id})

        # 写执行闸门（P0-3 fail-closed）：仅 PHYSICAL 模式需要
        if not definition.is_read_only and self.mode == ExecutionMode.PHYSICAL:
            gate = self.write_gate.check(needs_approval=True)
            if not gate.allowed:
                self.audit.append("write_blocked", request.correlation_id, {"reason": gate.reason})
                return {"status": "rejected", "reason": gate.reason}

        return await self._dispatch(request, definition, decision)

    # ---- 派发执行 ----

    async def _dispatch(self, request: CapabilityRequest, definition: Any, decision: Any) -> dict[str, Any]:
        # Adapter execution domains are an independent boundary from policy and
        # write-gate readiness. A mismatch fails closed before observe/execute.
        try:
            domain_allows_mode = self.adapters.allows(request.capability_id, self.mode)
        except UnknownNamespaceError as exc:
            self.audit.append("adapter_rejected", request.correlation_id, {"reason": str(exc)})
            return {"status": "rejected", "reason": str(exc)}
        if not domain_allows_mode:
            reason = f"adapter execution domain forbids {self.mode.value} mode"
            self.audit.append("adapter_rejected", request.correlation_id, {"reason": reason})
            return {"status": "rejected", "reason": reason}

        # 只读（P0-9 side_effect none）→ observe
        if definition.is_read_only:
            adapter = self.adapters.route(request.capability_id)
            state = await adapter.observe(request.device_id or "default")
            self.audit.append("observed", request.correlation_id, {"device": state.device_id})
            return {
                "status": "completed",
                "state": "OBSERVED",
                "verification_level": "V0",
                "physical_effect": "n/a",
                "correlation_id": request.correlation_id,
                "execution_mode": self.mode.value,
                "observed": state.state,
            }

        # 写执行
        adapter = self.adapters.route(request.capability_id)
        if not self.coordinator.has(request.correlation_id):
            # 不需要审批的请求，coordinator 尚未 begin
            self.coordinator.begin(request, decision)  # -> AUTHORIZED

        record = self.coordinator.get(request.correlation_id)
        evidence = await adapter.execute(request)

        if not evidence.dispatched:
            record.machine.advance(ExecutionState.FAILED)
            self.audit.append("dispatch_failed", request.correlation_id, {"detail": evidence.detail})
            return {"status": "failed", "reason": evidence.detail.get("error", "dispatch failed")}

        self.coordinator.mark_dispatched(request.correlation_id, evidence.model_dump())
        self.audit.append("dispatched", request.correlation_id,
                          {"capability_id": request.capability_id, "execution_mode": self.mode.value})

        # 验证
        verified = await adapter.verify(evidence)
        verification = self.verifier.verify(
            correlation_id=request.correlation_id,
            capability_id=request.capability_id,
            execution_evidence=verified.model_dump(),
        )
        self.audit.append("verification", request.correlation_id,
                          {"level": verification.level.value, "physical_effect": verification.physical_effect})

        self._advance_state(record, verification.level.value)
        self.audit.append("execution_state", request.correlation_id, {"state": record.state.value})

        required = definition.verification.required_level
        status = "completed" if verification.reached(required) else "partial"
        return {
            "status": status,
            "state": record.state.value,
            "verification_level": verification.level.value,
            "physical_effect": verification.physical_effect,
            "correlation_id": request.correlation_id,
            "execution_mode": self.mode.value,
        }

    def _advance_state(self, record: Any, level: str) -> None:
        """按验证层级推进状态机（V2→ACTUATION_OBSERVED，V3→DEVICE_EVIDENCE，V4→PHYSICAL_EFFECT）。"""
        rank = {"V0": 0, "V1": 0, "V2": 1, "V3": 2, "V4": 3}[level]
        steps = [
            (1, ExecutionState.ACTUATION_OBSERVED),
            (2, ExecutionState.DEVICE_EVIDENCE),
            (3, ExecutionState.PHYSICAL_EFFECT),
        ]
        for needed, state in steps:
            if rank >= needed and state not in record.machine.history:
                record.machine.advance(state)

    @staticmethod
    def new_correlation_id() -> str:
        return f"req_{uuid.uuid4().hex[:12]}"
