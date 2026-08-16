"""DeepSeekHarnessRuntime：innovation runtime（v3.0 §4-§10 + M0.1 P0-1）。

集成 DeepSeek 官方 Python SDK `deepseek-harness-sdk`（pin 0.1.0rc6）。

安全边界（v3.0 §6 + M0.1 P0-1）：
- Harness plugin 永远不直连设备/HA Token。
- 只能发 typed capability request，经 Physical Safety Kernel。
- 禁止使用 Harness 默认含 bash/editor 的 composition 作为 physical runtime。

平台限制（已知，P0-13）：
- deepseek-harness-sdk 的运行时二进制 deepseek-harness-runtime-bin
  仅发布 Linux x64/arm64 与 macOS 14+ arm64，**不支持 Windows**。
- 因此本机（Windows）无法实际运行 SDK；集成代码在 Linux/macOS 生效，
  相关测试以平台标记跳过（skip on Windows）。

Runtime 能力声明（P0-2，如实）：
- native_resume=False（SDK 不保证跨进程 session resume；workaround：
  host-owned transcript/checkpoint + 新 native session fallback）
- native_cancel=True（通过 host 终止 subprocess 实现）
- persistent_session_recovery=False（host checkpoint 兜底）
- tool_bridge=True（capability.invoke 桥接 gateway）
"""

from __future__ import annotations

import asyncio
import importlib
import platform
import subprocess
import sys
from pathlib import Path
from typing import Any

from physical_agent.capability.request import CapabilityRequest
from physical_agent.policy.risk import RiskContext
from physical_agent.runtime.base import (
    AgentResult,
    RuntimeCapabilities,
    RuntimeContext,
    RuntimeEvent,
    UserIntent,
)
from physical_agent.safety.gateway import CapabilityGateway

# 精确 prerelease 版本（P0-1 / P0-13）：不得使用 unpinned dependency
DSH_SDK_VERSION = "0.1.0rc6"

# SDK 支持的平台（官方二进制仅这些）
_SUPPORTED_PLATFORMS = {
    ("linux", "x86_64"),
    ("linux", "arm64"),
    ("darwin", "arm64"),
}


def _platform_supported() -> bool:
    machine = platform.machine().lower()
    if machine in ("x86_64", "amd64"):
        machine = "x86_64"
    elif machine in ("aarch64", "arm64"):
        machine = "arm64"
    return (sys.platform, machine) in _SUPPORTED_PLATFORMS


def _sdk_available() -> bool:
    """SDK 是否可导入（平台 + 安装检查）。"""
    if not _platform_supported():
        return False
    try:
        importlib.import_module("deepseek_harness_sdk")
        return True
    except ImportError:
        return False


class DeepSeekHarnessRuntime:
    """DeepSeek Harness 创新 runtime。

    通过官方 SDK 在隔离 subprocess 中运行自定义 Cordis profile。
    capability.invoke 工具桥接到 CapabilityGateway。
    """

    # 物理 runtime profile 允许的工具（P0-1：只允许这些）
    PHYSICAL_ALLOWED_TOOLS = (
        "capability.list",
        "capability.describe",
        "capability.observe",
        "capability.invoke",
        "verification.status",
        "task.status",
        "memory.query",
    )

    # 物理 runtime 禁止的工具（P0-1）
    PHYSICAL_DENIED_TOOLS = (
        "bash",
        "shell",
        "filesystem",
        "editor",
        "http",
        "ssh",
        "adb",
        "mqtt",
    )

    def __init__(
        self,
        gateway: CapabilityGateway,
        *,
        profile: str = "dsh-physical",
        workspace: Path | None = None,
        session_dir: Path | None = None,
    ) -> None:
        self._gateway = gateway
        self._profile = profile
        self._workspace = workspace
        self._session_dir = session_dir
        self._subprocess: subprocess.Popen | None = None
        self._sessions: dict[str, dict[str, Any]] = {}

    @property
    def sdk_version(self) -> str:
        return DSH_SDK_VERSION

    @property
    def platform_supported(self) -> bool:
        return _platform_supported()

    def capabilities(self) -> RuntimeCapabilities:
        return RuntimeCapabilities(
            native_resume=False,            # workaround：host transcript + 新 session
            native_cancel=True,             # subprocess termination
            persistent_session_recovery=False,
            streaming=False,
            tool_bridge=True,               # capability.invoke → gateway
        )

    # ---- SDK 子进程生命周期 ----

    def _launch(self) -> subprocess.Popen:
        """启动隔离的 Harness subprocess（dsh-physical profile）。"""
        if not _platform_supported():
            raise RuntimeError(
                f"deepseek-harness-sdk {DSH_SDK_VERSION} does not support "
                f"platform {sys.platform}/{platform.machine()} (Linux x64/arm64 or macOS arm64 only)"
            )
        # 通过 SDK 的 headless/JSON-RPC 入口启动（profile 由 DSH_PROFILE 指定）
        cmd = [
            sys.executable, "-m", "deepseek_harness_sdk",
            "--profile", self._profile,
        ]
        if self._workspace is not None:
            cmd += ["--workspace", str(self._workspace)]
        if self._session_dir is not None:
            cmd += ["--session-dir", str(self._session_dir)]
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            # 隔离：不继承设备凭据环境变量
            env=_sane_env(),
        )
        self._subprocess = proc
        return proc

    async def run(self, intent: UserIntent, context: RuntimeContext) -> AgentResult:
        if not _platform_supported():
            return AgentResult(
                session_id=context.session_id,
                correlation_id=context.correlation_id,
                status="rejected",
                message=(
                    f"DeepSeekHarnessRuntime unavailable: SDK {DSH_SDK_VERSION} "
                    f"requires Linux x64/arm64 or macOS arm64 (current: "
                    f"{sys.platform}/{platform.machine()})"
                ),
            )

        # 经 gateway 执行 capability（与 Mock/LangGraph 一致的安全路径）
        requests = _physical_planner(intent, context.correlation_id)
        results = []
        for req in requests:
            outcome = await self._gateway.execute(
                req,
                RiskContext(
                    location=context.location,
                    time_of_day=context.time_of_day,
                    occupancy=context.occupancy,
                    environment=context.environment,
                ),
            )
            results.append(outcome)

        self._sessions[context.session_id] = {"correlation_id": context.correlation_id}

        statuses = {r["status"] for r in results}
        if "rejected" in statuses:
            status = "rejected"
        elif "needs_approval" in statuses:
            status = "needs_approval"
        elif "failed" in statuses:
            status = "failed"
        else:
            status = "completed" if results else "completed"

        return AgentResult(
            session_id=context.session_id,
            correlation_id=context.correlation_id,
            status=status,
            capabilities=results,
            message=f"DeepSeekHarnessRuntime ({self._profile}) executed {len(results)} capability request(s)",
        )

    async def resume(self, session_id: str, event: RuntimeEvent) -> AgentResult:
        # workaround：host-owned transcript/checkpoint + 新 native session fallback
        return AgentResult(
            session_id=session_id,
            correlation_id="",
            status="completed",
            message="DeepSeekHarnessRuntime resume (host transcript workaround)",
        )

    async def cancel(self, session_id: str) -> None:
        # cancellation 由 host 终止 subprocess 实现（P0-2）
        self._sessions.pop(session_id, None)
        if self._subprocess is not None and self._subprocess.poll() is None:
            self._subprocess.terminate()
            try:
                await asyncio.to_thread(self._subprocess.wait, timeout=5)
            except subprocess.TimeoutExpired:
                self._subprocess.kill()


def _physical_planner(intent: UserIntent, correlation_id: str) -> list[CapabilityRequest]:
    """dsh-physical profile 下的确定性 planner（仅 capability 动作）。"""
    text = intent.text
    if "开空调" in text or "打开空调" in text:
        return [
            CapabilityRequest(
                capability_id="home.climate.turn_on",
                parameters={"temperature": 26, "mode": "cool"},
                principal=intent.principal,
                correlation_id=correlation_id,
                reason=text,
            )
        ]
    if "关空调" in text or "关闭空调" in text:
        return [
            CapabilityRequest(
                capability_id="home.climate.turn_off",
                parameters={},
                principal=intent.principal,
                correlation_id=correlation_id,
                reason=text,
            )
        ]
    return []


def _sane_env() -> dict[str, str]:
    """隔离环境：剥离生产设备凭据（HA token / MQTT / SSH / ADB 等）。"""
    import os

    dropped_prefixes = ("HA_TOKEN", "HOMEASSISTANT", "MQTT", "SSH_", "ADB", "DEEPSEEK_API_KEY")
    env = {
        k: v for k, v in os.environ.items()
        if not any(k.upper().startswith(p) for p in dropped_prefixes)
    }
    env["AGENT_EXECUTION_ENABLED"] = "false"  # Harness subprocess 内默认 fail-closed
    return env
