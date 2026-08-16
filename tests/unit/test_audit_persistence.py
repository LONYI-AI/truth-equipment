"""P0-5 持久审计链测试：重启恢复、篡改检测、checkpoint。"""

from __future__ import annotations

import json

import pytest

from physical_agent.audit.store import AuditStore, ChainIntegrityError


def _append_n(store: AuditStore, n: int) -> None:
    for i in range(n):
        store.append(f"event{i}", f"c{i}", {"i": i})


def test_restart_preserves_chain(tmp_path):
    path = tmp_path / "audit.jsonl"
    store = AuditStore(path=path)
    _append_n(store, 3)
    last = store.last_hash

    # 模拟重启：新实例从文件加载
    store2 = AuditStore(path=path)
    store2.load_and_verify()
    assert store2.last_hash == last
    assert len(store2.events()) == 3


def test_append_after_restart_continues_chain(tmp_path):
    path = tmp_path / "audit.jsonl"
    store = AuditStore(path=path)
    _append_n(store, 2)

    store2 = AuditStore(path=path)
    store2.load_and_verify()
    store2.append("post_restart", "c99", {})
    store2.verify_chain()


def test_modify_historical_event_detected(tmp_path):
    path = tmp_path / "audit.jsonl"
    store = AuditStore(path=path)
    _append_n(store, 3)

    # 篡改第 1 条
    lines = path.read_text(encoding="utf-8").splitlines()
    obj = json.loads(lines[0])
    obj["data"] = {"tampered": True}
    lines[0] = json.dumps(obj)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    store2 = AuditStore(path=path)
    with pytest.raises(ChainIntegrityError):
        store2.load_and_verify()


def test_truncate_without_checkpoint_undetectable(tmp_path):
    """无 checkpoint 时，纯截断无法被链校验发现（链仍自洽）——故需 checkpoint 兜底。"""
    path = tmp_path / "audit.jsonl"
    store = AuditStore(path=path)
    _append_n(store, 4)

    lines = path.read_text(encoding="utf-8").splitlines()
    path.write_text("\n".join(lines[:2]) + "\n", encoding="utf-8")  # 截断

    store2 = AuditStore(path=path)
    store2.load_and_verify()
    assert len(store2.events()) == 2


def test_tail_truncation_detected_with_checkpoint(tmp_path):
    """有签名 checkpoint 时，尾部截断必须被检测（checkpoint 链尾与重算链尾不一致）。"""
    path = tmp_path / "audit.jsonl"
    cp_path = tmp_path / "audit.checkpoint"
    store = AuditStore(path=path, signing_key=b"key", checkpoint_path=cp_path)
    _append_n(store, 4)
    store.checkpoint(persist=True)

    lines = path.read_text(encoding="utf-8").splitlines()
    path.write_text("\n".join(lines[:2]) + "\n", encoding="utf-8")  # 截断尾部

    store2 = AuditStore(path=path, signing_key=b"key", checkpoint_path=cp_path)
    with pytest.raises(ChainIntegrityError):
        store2.load_and_verify()


def test_checkpoint_tamper_detected(tmp_path):
    """checkpoint 被篡改（链尾被改）→ 签名校验失败。"""
    path = tmp_path / "audit.jsonl"
    cp_path = tmp_path / "audit.checkpoint"
    store = AuditStore(path=path, signing_key=b"key", checkpoint_path=cp_path)
    _append_n(store, 2)
    store.checkpoint(persist=True)

    saved = json.loads(cp_path.read_text(encoding="utf-8"))
    saved["last_hash"] = "0" * 64
    cp_path.write_text(json.dumps(saved), encoding="utf-8")

    store2 = AuditStore(path=path, signing_key=b"key", checkpoint_path=cp_path)
    with pytest.raises(ChainIntegrityError):
        store2.load_and_verify()


def test_reorder_detected(tmp_path):
    path = tmp_path / "audit.jsonl"
    store = AuditStore(path=path)
    _append_n(store, 3)

    lines = path.read_text(encoding="utf-8").splitlines()
    lines[0], lines[1] = lines[1], lines[0]  # 调换顺序
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    store2 = AuditStore(path=path)
    with pytest.raises(ChainIntegrityError):
        store2.load_and_verify()


def test_corrupt_json_detected(tmp_path):
    path = tmp_path / "audit.jsonl"
    store = AuditStore(path=path)
    _append_n(store, 1)
    with path.open("a", encoding="utf-8") as f:
        f.write("{not valid json}\n")

    store2 = AuditStore(path=path)
    with pytest.raises(ChainIntegrityError):
        store2.load_and_verify()


def test_checkpoint_persisted(tmp_path):
    path = tmp_path / "audit.jsonl"
    cp_path = tmp_path / "audit.checkpoint"
    store = AuditStore(path=path, signing_key=b"key", checkpoint_path=cp_path)
    _append_n(store, 2)
    cp = store.checkpoint(persist=True)
    assert cp_path.exists()
    saved = json.loads(cp_path.read_text(encoding="utf-8"))
    assert saved["last_hash"] == store.last_hash
    assert saved["checkpoint"] == cp


async def test_writes_fail_closed_on_corrupt(tmp_path, registry, mock_adapter, kill_switch):
    """审计文件损坏 → 写执行 fail closed。"""
    path = tmp_path / "audit.jsonl"
    path.write_text("corrupt line\n", encoding="utf-8")

    from physical_agent.adapters.registry import AdapterRegistry
    from physical_agent.capability.request import CapabilityRequest
    from physical_agent.policy.approval import ApprovalEngine
    from physical_agent.safety.gateway import CapabilityGateway

    audit = AuditStore(path=path)
    with pytest.raises(ChainIntegrityError):
        audit.load_and_verify()

    adapters = AdapterRegistry()
    adapters.register("home", mock_adapter)
    adapters.mark_loaded()

    gw = CapabilityGateway(
        registry=registry,
        adapters=adapters,
        kill_switch=kill_switch,
        audit=audit,
        approval_engine=ApprovalEngine(),
    )
    req = CapabilityRequest(capability_id="home.climate.turn_off", correlation_id="corrupt1")
    outcome = await gw.execute(req)
    assert outcome["status"] == "rejected"
    assert "audit" in outcome["reason"]
