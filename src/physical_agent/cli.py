"""M1A Simulation MVP 最小 CLI 用户入口。

用法：`python -m physical_agent.cli`

真实调用正式 `LangGraphRuntime`（经 composition root 组装的完整闭环），
**禁止**单独写一条 demo 假链路。

目标体验：:

    You: 把客厅空调调到26度
    Agent: 此动作需要批准。
    Approve? [y/N]: y
    Agent: SIMULATION 执行完成。
    Verification: V2 satisfied
"""

from __future__ import annotations

import asyncio
import sys

from physical_agent.composition import build_simulation_composition
from physical_agent.runtime.base import RuntimeContext, RuntimeEvent, UserIntent
from physical_agent.safety.gateway import CapabilityGateway

_EXIT_WORDS = ("exit", "quit", "q")


def _reconfigure_stdio() -> None:
    """Windows 控制台下把 stdio 切到 UTF-8，保证中文交互稳定。"""
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8")
            except Exception:  # pragma: no cover - 尽力而为
                pass


async def _run_once(runtime, text: str):
    correlation_id = CapabilityGateway.new_correlation_id()
    session_id = f"sess-{correlation_id}"
    intent = UserIntent(text=text, principal="human", session_id=session_id)
    context = RuntimeContext(correlation_id=correlation_id, session_id=session_id)
    return await runtime.run(intent, context)


async def main() -> int:
    _reconfigure_stdio()
    composition = build_simulation_composition()
    runtime = composition.runtime

    print("M1A Simulation MVP — 输入自然语言指令（exit/quit 退出）。")
    while True:
        try:
            text = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not text:
            continue
        if text.lower() in _EXIT_WORDS:
            break

        result = await _run_once(runtime, text)

        if result.status == "needs_approval":
            approval_id = result.evidence.get("approval_id")
            print("Agent: 此动作需要批准。")
            try:
                answer = input("Approve? [y/N]: ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                answer = "n"
            if answer in ("y", "yes"):
                # Owner 授予一次性 ApprovalGrant（M0 ApprovalEngine: request → grant → consume）
                composition.gateway.approve(approval_id)
                decision = "approve"
            else:
                decision = "reject"
            result = await runtime.resume(
                result.session_id,
                RuntimeEvent(event_type="approval", payload={"decision": decision}),
            )

        print(f"Agent: {result.message}")

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
