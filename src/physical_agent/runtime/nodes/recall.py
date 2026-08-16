"""M1A-W2 Recall 节点：从 MemoryStore 只读检索 → MemoryContext。

复用 M0 `MemoryStore`（Protocol）/ `SqliteMemoryStore`，禁止新建第二套 memory
subsystem、禁止部署 Qdrant。Recall 是 READ-ONLY：不 append_event / 不 set_preference /
不 record_device_state（这些属 memory_update / 后续流程）。
"""

from __future__ import annotations

from typing import Any

from physical_agent.memory.store import MemoryStore
from physical_agent.runtime.graph import NodeHandler
from physical_agent.runtime.planning import MemoryContext
from physical_agent.runtime.state import AgentState


class RecallError(ValueError):
    """Recall 关键输入缺失（session_id）。"""


def make_recall_handler(
    store: MemoryStore,
    *,
    limit: int = 20,
    preference_keys: tuple[str, ...] = ("preferred_temperature",),
) -> NodeHandler:
    """构造 Recall handler。

    - 只读检索：本会话 recent events（bounded，倒序）+ 配置的 preference keys。
    - session-scoped：不读取其他 session 的事件（`query_events(session_id=...)`）。
    - 不产生任何 memory 写入。
    """
    if limit <= 0:
        raise ValueError("recall limit must be positive")

    def recall(state: AgentState) -> dict[str, Any]:
        session_id = state.get("session_id")
        if not session_id:
            raise RecallError("recall requires session_id (missing key input)")

        events = store.query_events(session_id=session_id, limit=limit)
        preferences: dict[str, Any] = {}
        for key in preference_keys:
            value = store.get_preference(key)
            if value is not None:
                preferences[key] = value

        return {"memory_context": MemoryContext(events=events, preferences=preferences)}

    return recall
