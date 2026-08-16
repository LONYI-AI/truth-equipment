"""ApprovalEngine（M0.1 P0-4）：真实审批流程，单次使用 + 过期 + 防重放。"""

from __future__ import annotations

import hashlib
import json
import threading
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from physical_agent.capability.request import CapabilityRequest


class ApprovalError(Exception):
    """审批相关错误。"""


@dataclass
class ApprovalRequest:
    """一次审批请求（绑定精确的 capability 请求）。"""

    approval_id: str
    correlation_id: str
    principal: str
    capability_id: str
    device_id: str
    canonical_parameters_hash: str
    risk_tier: int
    issued_at: str
    expires_at: str

    @staticmethod
    def canonical_parameters(parameters: dict) -> str:
        """参数规范化哈希（排序键、稳定序列化）。"""
        canonical = json.dumps(parameters, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass
class ApprovalGrant:
    """一次审批授予。单次使用、过期、绑定精确请求、拒绝参数篡改、防重放。"""

    approval_id: str
    approver: str
    granted_at: str
    consumed: bool = False
    _consumed: bool = field(default=False, init=False, repr=False)

    @property
    def is_consumed(self) -> bool:
        return self._consumed

    def mark_consumed(self) -> None:
        if self._consumed:
            raise ApprovalError("approval grant already consumed (replay rejected)")
        self._consumed = True


class ApprovalEngine:
    """确定性审批引擎（不依赖 LLM）。"""

    def __init__(self, ttl_seconds: float = 300.0) -> None:
        self.ttl_seconds = ttl_seconds
        self._requests: dict[str, ApprovalRequest] = {}
        self._grants: dict[str, ApprovalGrant] = {}
        self._lock = threading.Lock()

    def _now(self) -> datetime:
        return datetime.now(UTC)

    def request_approval(self, request: CapabilityRequest, risk_tier: int) -> ApprovalRequest:
        approval_id = f"apv_{uuid.uuid4().hex[:12]}"
        now = self._now()
        ar = ApprovalRequest(
            approval_id=approval_id,
            correlation_id=request.correlation_id,
            principal=request.principal,
            capability_id=request.capability_id,
            device_id=request.device_id,
            canonical_parameters_hash=ApprovalRequest.canonical_parameters(request.parameters),
            risk_tier=risk_tier,
            issued_at=now.isoformat(),
            expires_at=(now + timedelta(seconds=self.ttl_seconds)).isoformat(),
        )
        with self._lock:
            self._requests[approval_id] = ar
        return ar

    def grant(self, approval_id: str, approver: str = "owner") -> ApprovalGrant:
        with self._lock:
            ar = self._requests.get(approval_id)
            if ar is None:
                raise ApprovalError(f"unknown approval_id {approval_id!r}")
            if self._is_expired(ar):
                raise ApprovalError("approval request expired")
            grant = ApprovalGrant(approval_id=approval_id, approver=approver,
                                  granted_at=self._now().isoformat())
            self._grants[approval_id] = grant
            return grant

    def consume(self, approval_id: str, request: CapabilityRequest, risk_tier: int) -> ApprovalGrant:
        """校验并消费审批授予。任何不匹配/过期/重放 → 抛 ApprovalError。"""
        with self._lock:
            ar = self._requests.get(approval_id)
            grant = self._grants.get(approval_id)
            if ar is None or grant is None:
                raise ApprovalError(f"no grant for approval_id {approval_id!r}")
            if self._is_expired(ar):
                raise ApprovalError("approval request expired")
            if grant.is_consumed:
                raise ApprovalError("approval grant already consumed (replay rejected)")
            # 绑定精确请求：correlation_id、capability、参数哈希、risk 必须一致
            if ar.correlation_id != request.correlation_id:
                raise ApprovalError("correlation_id mismatch")
            if ar.capability_id != request.capability_id:
                raise ApprovalError("capability_id mismatch")
            if ar.canonical_parameters_hash != ApprovalRequest.canonical_parameters(request.parameters):
                raise ApprovalError("parameter mutation detected")
            if ar.risk_tier != risk_tier:
                raise ApprovalError("risk tier mismatch")
            grant.mark_consumed()
            return grant

    def _is_expired(self, ar: ApprovalRequest) -> bool:
        try:
            expires = datetime.fromisoformat(ar.expires_at)
        except ValueError:
            return True
        return self._now() > expires

    def is_healthy(self) -> bool:
        """审批引擎是否健康（M0.1 P0-3 安全栈检查用）。"""
        return True
