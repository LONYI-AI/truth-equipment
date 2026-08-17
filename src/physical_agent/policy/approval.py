"""ApprovalEngine（M0.1 P0-4 强化）：真实审批流程，单次使用 + 过期 + 防重放。

绑定语义（P0-4 强化）：
- 一次审批绑定 **principal + device + 完整 canonical request**
  （capability_id + parameters + principal + device_id 的稳定序列化哈希）。
- consume 时校验 correlation_id、principal、device_id、capability_id、
  canonical_request_hash、risk_tier 全部一致，任何不匹配/过期/重放 → ApprovalError。
"""

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
    """一次审批请求（绑定 principal + device + 完整 canonical request）。"""

    approval_id: str
    correlation_id: str
    principal: str
    capability_id: str
    device_id: str
    canonical_request_hash: str
    risk_tier: int
    issued_at: str
    expires_at: str

    @staticmethod
    def canonical_request(
        principal: str, device_id: str, capability_id: str, parameters: dict
    ) -> str:
        """完整 canonical request 的稳定序列化（排序键、UTF-8、紧凑分隔符）。"""
        obj = {
            "principal": principal,
            "device_id": device_id,
            "capability_id": capability_id,
            "parameters": parameters,
        }
        return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))

    @staticmethod
    def hash_request(
        principal: str, device_id: str, capability_id: str, parameters: dict
    ) -> str:
        """完整 canonical request 的 SHA-256 哈希。"""
        canonical = ApprovalRequest.canonical_request(principal, device_id, capability_id, parameters)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass
class ApprovalGrant:
    """一次审批授予。单次使用、过期、绑定精确请求、拒绝参数篡改、防重放。"""

    approval_id: str
    approver: str
    granted_at: str
    correlation_id: str = ""  # 原始 CapabilityRequest 的 correlation_id（供审计，非 approval_id）
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
            canonical_request_hash=ApprovalRequest.hash_request(
                request.principal, request.device_id, request.capability_id, request.parameters
            ),
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
                                  granted_at=self._now().isoformat(),
                                  correlation_id=ar.correlation_id)
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
            # 绑定精确请求：correlation_id、principal、device、capability、完整请求哈希、risk 必须一致
            if ar.correlation_id != request.correlation_id:
                raise ApprovalError("correlation_id mismatch")
            if ar.principal != request.principal:
                raise ApprovalError("principal mismatch")
            if ar.device_id != request.device_id:
                raise ApprovalError("device_id mismatch")
            if ar.capability_id != request.capability_id:
                raise ApprovalError("capability_id mismatch")
            expected_hash = ApprovalRequest.hash_request(
                request.principal, request.device_id, request.capability_id, request.parameters
            )
            if ar.canonical_request_hash != expected_hash:
                raise ApprovalError("request mutation detected (principal/device/capability/parameters)")
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
