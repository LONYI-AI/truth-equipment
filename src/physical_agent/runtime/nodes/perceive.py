"""M1A-W2 Perceive 节点：从只读 PerceptionSource 读取 snapshot → WorldState。

只读边界：Perceive 不执行命令、不写设备、不调用 CapabilityGateway / Policy /
Adapter.execute()。生产代码不 import tests；source 通过显式 Protocol 注入。
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from physical_agent.runtime.graph import NodeHandler
from physical_agent.runtime.state import AgentState, WorldState


class PerceptionSnapshot(BaseModel):
    """感知快照：设备状态 + 环境状态（不含时间戳/来源，由 perceive 组装）。"""

    model_config = ConfigDict(extra="forbid")

    devices: dict[str, dict[str, Any]] = Field(default_factory=dict)
    environment: dict[str, Any] = Field(default_factory=dict)


class WorldStateSource(Protocol):
    """只读感知源契约。职责只有：读取 snapshot。不得执行任何副作用。"""

    def read_snapshot(self) -> PerceptionSnapshot: ...


def make_perceive_handler(
    source: WorldStateSource,
    *,
    clock: Callable[[], datetime] | None = None,
) -> NodeHandler:
    """构造 Perceive handler。

    - `source`：注入的只读感知源（测试用 Fake HA / deterministic fixture）。
    - `clock`：注入的确定性时钟（测试用固定 datetime，禁止 sleep / wall-clock race）。

    M1A Perceive 输出恒为 source="simulation"、provenance="simulated"，
    绝不声称真实物理感知。不篡改 session_id / correlation_id / intent / messages。
    """
    _now = clock if clock is not None else (lambda: datetime.now(UTC))

    def perceive(state: AgentState) -> dict[str, Any]:
        snapshot = source.read_snapshot()
        world_state = WorldState(
            devices=snapshot.devices,
            environment=snapshot.environment,
            observed_at=_now(),
            source="simulation",
            provenance="simulated",
        )
        return {"world_state": world_state}

    return perceive
