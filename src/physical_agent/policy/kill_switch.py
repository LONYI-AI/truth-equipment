"""Kill Switch（v3.0 §20 + M0.1 P0-3）：fail-closed 执行开关。

P0-3 关键语义：
- AGENT_EXECUTION_ENABLED 缺失时默认 false（安全默认），写执行被拒绝。
- 只有显式 AGENT_EXECUTION_ENABLED=true 时才可能允许写。
- 只读观察始终可用。
"""

from __future__ import annotations

import os
from pathlib import Path


class KillSwitch:
    """全局物理执行开关。触发后：LLM 可聊天、可观察，但不可执行任何物理动作。

    支持粒度：
    - global：AGENT_EXECUTION_ENABLED != true 或 kill file 存在
    - 组件级：kill capability / kill adapter / kill device / kill runtime
    """

    ENV_KEY = "AGENT_EXECUTION_ENABLED"

    def __init__(self, kill_file: Path | None = None) -> None:
        self._kill_file = kill_file or Path(".kill_switch")
        self._killed_components: set[str] = set()

    @property
    def env_explicitly_enabled(self) -> bool:
        """环境变量是否显式为 true（fail-closed：缺失/false/其他值 → False）。"""
        return os.environ.get(self.ENV_KEY, "false").lower() == "true"

    @property
    def is_active(self) -> bool:
        """全局 kill switch 是否激活（激活 = 写动作被禁止）。"""
        # fail-closed：环境变量非显式 true → 视为 kill（禁止写）
        if not self.env_explicitly_enabled:
            return True
        return self._kill_file.exists()

    @property
    def is_kill_file_active(self) -> bool:
        """仅凭 kill file 判断（不依赖环境变量；供 policy 在 simulation/physical 统一使用）。"""
        return self._kill_file.exists()

    def activate(self) -> None:
        self._kill_file.touch()

    def deactivate(self) -> None:
        if self._kill_file.exists():
            self._kill_file.unlink()

    def kill(self, component: str) -> None:
        """按组件禁用（capability/adapter/device/runtime）。"""
        self._killed_components.add(component)

    def unkill(self, component: str) -> None:
        self._killed_components.discard(component)

    def is_killed(self, component: str) -> bool:
        return component in self._killed_components

    def assert_writes_enabled(self, component: str = "") -> None:
        """写动作前调用；被 kill 时抛异常。"""
        from physical_agent.policy.engine import PolicyDeniedError

        if self.is_active:
            raise PolicyDeniedError("AGENT_EXECUTION_ENABLED != true (fail-closed)")
        if component and self.is_killed(component):
            raise PolicyDeniedError(f"component {component!r} killed")
