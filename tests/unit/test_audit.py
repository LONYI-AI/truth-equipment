"""Audit Store（tamper-evident）单元测试。"""

from __future__ import annotations

import pytest

from physical_agent.audit.store import AuditStore, ChainIntegrityError


def test_chain_verifies_clean():
    store = AuditStore()
    store.append("a", "c1", {"x": 1})
    store.append("b", "c1", {"x": 2})
    store.verify_chain()  # 不抛异常


def test_chain_detects_tamper():
    store = AuditStore()
    e1 = store.append("a", "c1", {"x": 1})
    store.append("b", "c1", {"x": 2})
    # 篡改第一条事件的数据
    e1.data = {"x": 999}
    with pytest.raises(ChainIntegrityError):
        store.verify_chain()


def test_chain_hash_is_sha256_hex():
    store = AuditStore()
    e = store.append("a", "c1", {})
    assert len(e.hash) == 64
    assert all(c in "0123456789abcdef" for c in e.hash)


def test_checkpoint_with_signing_key():
    store = AuditStore(signing_key=b"secret-key")
    store.append("a", "c1", {})
    cp = store.checkpoint()
    assert len(cp) == 64  # HMAC-SHA256 hex digest


def test_checkpoint_without_key_returns_lasthash():
    store = AuditStore()
    store.append("a", "c1", {})
    assert store.checkpoint() == store.last_hash


def test_events_are_append_only():
    store = AuditStore()
    store.append("a", "c1", {})
    store.append("b", "c2", {})
    assert [e.event_type for e in store.events()] == ["a", "b"]
