"""Memory（SQLite）单元测试。"""

from __future__ import annotations

from physical_agent.memory.store import SqliteMemoryStore


def test_preference_set_get():
    store = SqliteMemoryStore()
    store.set_preference("preferred_bedroom_temp", 25)
    assert store.get_preference("preferred_bedroom_temp") == 25


def test_preference_missing_returns_none():
    store = SqliteMemoryStore()
    assert store.get_preference("nonexistent") is None


def test_preference_overwrite():
    store = SqliteMemoryStore()
    store.set_preference("k", 1)
    store.set_preference("k", 2)
    assert store.get_preference("k") == 2


def test_append_and_query_events():
    store = SqliteMemoryStore()
    store.append_event({"session_id": "s1", "correlation_id": "c1", "event_type": "x", "payload": {"a": 1}})
    events = store.query_events(session_id="s1")
    assert len(events) == 1
    assert events[0]["event_type"] == "x"
    assert events[0]["payload"] == {"a": 1}


def test_query_events_by_session_isolates():
    store = SqliteMemoryStore()
    store.append_event({"session_id": "s1", "correlation_id": "c1", "event_type": "x"})
    store.append_event({"session_id": "s2", "correlation_id": "c2", "event_type": "y"})
    assert len(store.query_events(session_id="s1")) == 1
    assert len(store.query_events()) == 2


def test_device_history():
    store = SqliteMemoryStore()
    store.record_device_state("mock.ac", {"power": "on"})
    store.record_device_state("mock.ac", {"power": "off"})
    # 查询未暴露，仅验证不抛异常 + 表可写
    assert True
