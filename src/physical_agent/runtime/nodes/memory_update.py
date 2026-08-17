"""M1A-W5（Integration Hardening）Memory Update 节点：把本轮真实成功结果写入 MemoryStore。

设计约束：
- **只写成功**：仅当 `verification_satisfied` 为 True 且 execution outcome status
  == "completed" 时才写 memory；失败/拒绝/验证未达一律不写（绝不让失败执行写成成功记忆）。
- **session / correlation scoped**：写入的 event 必须携带 `session_id` 与 `correlation_id`，
  使 recall 只能按 session 检索、audit 可全程追踪。
- 复用 M0 `MemoryStore.append_event`，不新建第二套 memory subsystem。
"""

from __future__ import annotations

from typing import Any

from physical_agent.audit.store import AuditStore
from physical_agent.memory.store import MemoryStore
from physical_agent.runtime.graph import NodeHandler
from physical_agent.runtime.state import AgentState

# 写入 memory 的事件类型（供 recall / 审计识别「成功动作」）
EVENT_ACTION_COMPLETED = "action_completed"


def make_memory_update_handler(
    store: MemoryStore,
    *,
    audit: AuditStore | None = None,
) -> NodeHandler:
    """构造 Memory Update handler（sync）。

    只有成功闭环（verification_satisfied + execution completed）才 append_event；
    否则返回空更新（不写任何 memory），并审计 `memory_skipped`（failure 不落成功记忆）。
    """

    def memory_update(state: AgentState) -> dict[str, Any]:
        session_id = state.get("session_id", "")
        correlation_id = state.get("correlation_id", "")

        satisfied = bool(state.get("verification_satisfied"))
        outcome = state.get("execution_outcome") or {}
        verification = state.get("verification")
        request = state.get("current_request")

        if not satisfied or outcome.get("status") != "completed":
            # 失败/拒绝/验证未达：绝不写成成功记忆
            if audit is not None:
                audit.append(
                    "memory_skipped",
                    correlation_id,
                    {
                        "verification_satisfied": satisfied,
                        "execution_status": outcome.get("status"),
                    },
                )
            return {}

        capability_id = (
            request.capability_id if request is not None else outcome.get("capability_id", "")
        )
        level = verification.level.value if verification is not None else outcome.get("verification_level", "")

        store.append_event(
            {
                "session_id": session_id,
                "correlation_id": correlation_id,
                "event_type": EVENT_ACTION_COMPLETED,
                "payload": {
                    "capability_id": capability_id,
                    "parameters": request.parameters if request is not None else {},
                    "device_id": request.device_id if request is not None else "",
                    "verification_level": level,
                    "physical_effect": verification.physical_effect if verification is not None else "pending",
                    "provenance": "simulated",
                },
            }
        )

        if audit is not None:
            audit.append(
                "memory_updated",
                correlation_id,
                {"capability_id": capability_id, "verification_level": level},
            )

        return {}

    return memory_update
