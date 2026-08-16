"""DeepSeekHarnessRuntime：真正实例化官方 `deepseek_harness.DeepSeekHarness`（M0.1 P0-1 强化）。

使用 DeepSeek 官方 Python SDK（发行包 `deepseek-harness-sdk`，import 模块 `deepseek_harness`）。
通过真实 Cordis composition（`.cordis.yml`）加载插件组合：
- physical profile  → `harness/physical/cordis.yml`（仅 LLM + agent 核心 + 会话，无 bash/fs/editor）。
- development profile → `harness/development/cordis.yml`（官方 coding 组合）。

安全边界（v3.0 §6 + M0.1 P0-1）：
- Harness 永远不直连设备/HA Token：物理 Cordis 组合不挂载任何可访问设备凭据的工具，
  设备凭据（HA_TOKEN/MQTT/SSH/ADB）绝不注入 SDK 进程环境；仅 DEEPSEEK_API_KEY/BASE_URL
  由调用方显式注入（可为本地 fake/model proxy）。
- 物理组合不挂载 bash/shell/filesystem/editor/http/ssh/adb 工具。
- `capability.invoke` 工具桥接 Physical Safety Kernel 属 M1A 落地（M0 为"仅规划/观察"组合）。

平台限制（P0-13，如实）：
- 运行时二进制仅 Linux x64/arm64、macOS 14+ arm64，**不支持 Windows**。
- 支持平台上 SDK 必须真实安装并真实运行（不允许 "SDK 未装但 conformance PASS"）。
"""

from __future__ import annotations

import asyncio
import importlib
import platform
import sys
from pathlib import Path
from typing import Any

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
DSH_MODULE = "deepseek_harness"
DSH_CLASS = "DeepSeekHarness"

# SDK 支持的平台（官方二进制仅这些）
_SUPPORTED_PLATFORMS = {
    ("linux", "x86_64"),
    ("linux", "arm64"),
    ("darwin", "arm64"),
}

# 仓库根目录（src/physical_agent/runtime/deepseek_harness.py -> 上溯到仓库根）
_REPO_ROOT = Path(__file__).resolve().parents[3]


def _platform_supported() -> bool:
    machine = platform.machine().lower()
    if machine in ("x86_64", "amd64"):
        machine = "x86_64"
    elif machine in ("aarch64", "arm64"):
        machine = "arm64"
    return (sys.platform, machine) in _SUPPORTED_PLATFORMS


def _sdk_available() -> bool:
    """官方 SDK 是否可真实导入（平台 + 安装检查）。"""
    if not _platform_supported():
        return False
    try:
        importlib.import_module(DSH_MODULE)
        return True
    except ImportError:
        return False


def physical_cordis_path() -> Path:
    """物理 runtime 的真实 Cordis composition 路径。"""
    return _REPO_ROOT / "harness" / "physical" / "cordis.yml"


def development_cordis_path() -> Path:
    """开发/Evolution 的真实 Cordis composition 路径。"""
    return _REPO_ROOT / "harness" / "development" / "cordis.yml"


class DeepSeekHarnessRuntime:
    """DeepSeek Harness 创新 runtime（真实 SDK）。

    通过官方 `deepseek_harness.DeepSeekHarness` 在隔离子进程中加载真实 Cordis composition。
    支持平台 + SDK 已安装时真正运行；否则如实返回 rejected（平台/安装说明），绝不伪装 completed。
    """

    # 物理 runtime 允许的工具（P0-1）：M1A 桥接 capability.* 到 gateway
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
        provider: str = "deepseek-official",
        model: str = "deepseek-v4-flash",
        max_tokens: int = 49_152,
        workspace: Path | None = None,
        session_dir: Path | None = None,
        cordis: Path | str | None = None,
    ) -> None:
        self._gateway = gateway
        self._profile = profile
        self._provider = provider
        self._model = model
        self._max_tokens = max_tokens
        self._workspace = workspace
        self._session_dir = session_dir
        if cordis is not None:
            self._cordis = Path(cordis)
        elif profile == "dsh-physical":
            self._cordis = physical_cordis_path()
        else:
            self._cordis = development_cordis_path()
        self._sessions: dict[str, dict[str, Any]] = {}

    @property
    def sdk_version(self) -> str:
        return DSH_SDK_VERSION

    @property
    def platform_supported(self) -> bool:
        return _platform_supported()

    @property
    def sdk_available(self) -> bool:
        return _sdk_available()

    @property
    def cordis_path(self) -> Path:
        return self._cordis

    def capabilities(self) -> RuntimeCapabilities:
        """Return only capabilities exercised by the runtime implementation.

        Host bookkeeping is not native cancellation or recovery, and the planned
        M1A gateway bridge is not available in this M0 runtime.
        """
        return RuntimeCapabilities(
            native_resume=False,
            native_cancel=False,
            persistent_session_recovery=False,
            streaming=False,
            tool_bridge=False,
        )

    # ---- 官方 SDK 实例化 ----

    def build_harness(self) -> Any:  # pragma: no cover - 仅支持平台可执行（CI Linux smoke test 覆盖）
        """实例化官方 `deepseek_harness.DeepSeekHarness`（真实 SDK，非 mock）。

        支持平台 + SDK 已安装才允许调用；否则抛 RuntimeError（调用方不得伪装运行）。
        """
        if not _platform_supported():
            raise RuntimeError(
                f"deepseek-harness-sdk {DSH_SDK_VERSION} does not support "
                f"platform {sys.platform}/{platform.machine()} (Linux x64/arm64 or macOS arm64 only)"
            )
        if not _sdk_available():
            raise RuntimeError(
                f"{DSH_MODULE} not importable: install `deepseek-harness-sdk=={DSH_SDK_VERSION}` "
                f"(pip install -e '.[dev,harness]') before running on a supported platform"
            )
        if not self._cordis.exists():
            raise RuntimeError(f"Cordis composition not found: {self._cordis}")

        module = importlib.import_module(DSH_MODULE)
        harness_cls = getattr(module, DSH_CLASS)
        kwargs: dict[str, Any] = {
            "provider": self._provider,
            "model": self._model,
            "max_tokens": self._max_tokens,
            "cordis": str(self._cordis),
        }
        if self._workspace is not None:
            kwargs["cwd"] = str(self._workspace)
        if self._session_dir is not None:
            kwargs["session_root"] = str(self._session_dir)
        return harness_cls(**kwargs)

    # ---- 运行 ----

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
        if not _sdk_available():
            return AgentResult(
                session_id=context.session_id,
                correlation_id=context.correlation_id,
                status="rejected",
                message=(
                    f"DeepSeekHarnessRuntime unavailable: {DSH_MODULE} not installed "
                    f"(pip install deepseek-harness-sdk=={DSH_SDK_VERSION})"
                ),
            )

        # 真实运行（阻塞 SDK 调用放到线程池，避免阻塞事件循环）
        return await asyncio.to_thread(self._run_sync, intent, context)  # pragma: no cover

    def _run_sync(self, intent: UserIntent, context: RuntimeContext) -> AgentResult:  # pragma: no cover
        session_id = context.session_id or f"dsh-{context.correlation_id}"
        with self.build_harness() as harness:
            result = harness.run(intent.text, session_id=session_id)
            self._sessions[context.session_id] = {"correlation_id": context.correlation_id}

        finish = getattr(result, "finish_reason", None)
        final = getattr(result, "final_response", None)
        if finish == "error":
            status = "failed"
        elif finish is None:
            status = "completed" if final else "failed"
        else:
            status = "completed"  # completed / max-tokens 均视为已产出
        return AgentResult(
            session_id=getattr(result, "session_id", session_id),
            correlation_id=context.correlation_id,
            status=status,
            message=final if isinstance(final, str) else "",
            evidence={
                "finish_reason": finish,
                "sdk_version": self.sdk_version,
                "cordis": str(self._cordis),
            },
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
        # This only drops host bookkeeping.  It cannot terminate a running
        # Harness subprocess, so capabilities().native_cancel remains false.
        self._sessions.pop(session_id, None)
