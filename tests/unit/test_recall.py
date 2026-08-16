"""M1A-W2 Recall 节点测试：只读检索、session 隔离、bounded、无写入。"""

from __future__ import annotations

import ast
import inspect

import pytest

from physical_agent.memory.store import SqliteMemoryStore
from physical_agent.runtime.nodes.recall import RecallError, make_recall_handler


def _store_with_events() -> SqliteMemoryStore:
    store = SqliteMemoryStore(":memory:")
    for i in range(5):
        store.append_event({"session_id": "A", "event_type": f"e{i}", "payload": {"i": i}})
    for i in range(3):
        store.append_event({"session_id": "B", "event_type": f"be{i}", "payload": {}})
    return store


def test_recall_reads_session_events():
    store = _store_with_events()
    handler = make_recall_handler(store, limit=10)
    result = handler({"session_id": "A"})
    ctx = result["memory_context"]
    assert len(ctx.events) == 5
    assert all(e["session_id"] == "A" for e in ctx.events)


def test_recall_does_not_leak_other_session():
    store = _store_with_events()
    handler = make_recall_handler(store, limit=10)
    result = handler({"session_id": "A"})
    ctx = result["memory_context"]
    assert all(e["session_id"] == "A" for e in ctx.events)  # 无 session B 事件


def test_recall_limit_is_bounded():
    store = _store_with_events()
    handler = make_recall_handler(store, limit=2)
    ctx = handler({"session_id": "A"})["memory_context"]
    assert len(ctx.events) == 2


def test_recall_reads_configured_preferences():
    store = SqliteMemoryStore(":memory:")
    store.set_preference("preferred_temperature", 26)
    store.set_preference("other_key", "x")  # 未配置的 key 不应被读取
    handler = make_recall_handler(store, preference_keys=("preferred_temperature",))
    ctx = handler({"session_id": "A"})["memory_context"]
    assert ctx.preferences == {"preferred_temperature": 26}


def test_recall_is_read_only_no_memory_write():
    """Recall 不产生 memory 写入（不 append_event / set_preference / record_device_state）。"""
    store = _store_with_events()
    before_events = len(store.query_events(session_id="A", limit=100))
    before_pref = store.get_preference("preferred_temperature")

    handler = make_recall_handler(store, preference_keys=("preferred_temperature",))
    handler({"session_id": "A"})

    after_events = len(store.query_events(session_id="A", limit=100))
    assert after_events == before_events  # 无新增事件
    assert store.get_preference("preferred_temperature") == before_pref  # 无偏好写入


def test_recall_missing_session_id_fails_closed():
    store = _store_with_events()
    handler = make_recall_handler(store)
    with pytest.raises(RecallError):
        handler({})


def test_recall_rejects_non_positive_limit():
    with pytest.raises(ValueError):
        make_recall_handler(SqliteMemoryStore(":memory:"), limit=0)


def test_recall_has_no_forbidden_imports():
    import physical_agent.runtime.nodes.recall as mod

    forbidden = ("physical_agent.execution", "physical_agent.safety.gateway", "physical_agent.policy.approval")
    for node in ast.walk(ast.parse(inspect.getsource(mod))):
        if isinstance(node, ast.ImportFrom) and node.module:
            assert node.module not in forbidden
        elif isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name not in forbidden
