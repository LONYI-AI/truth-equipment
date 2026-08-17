"""M1A Integration Hardening end-to-end acceptance。

从自然语言用户输入开始，实际经过**正式 LangGraphRuntime** + ReasoningModel +
StateGraph（Perceive → Recall → Reason → Plan → Policy → Approval → Execute →
Verify → Memory → Audit），最终返回 AgentResult。

全程经 composition root（`build_simulation_composition`），**不另拼一套 demo 假链路**。
覆盖：正常成功 / 用户拒绝审批 / policy 拒绝 / 验证失败 / 审批 resume / stale-replay 审批 /
malformed model output fail-closed / 审批 resume 不双计 rate-limit。
"""

from __future__ import annotations

from physical_agent.adapters.mock import MockDevice
from physical_agent.capability.registry import CapabilityRegistry
from physical_agent.capability.schema import (
    CapabilityDefinition,
    Operation,
    ParameterSpec,
    SideEffect,
)
from physical_agent.composition import build_simulation_composition
from physical_agent.policy.engine import RateLimiter
from physical_agent.runtime.base import RuntimeContext, RuntimeEvent, UserIntent
from physical_agent.safety.gateway import CapabilityGateway


def _session() -> tuple[str, str]:
    correlation_id = CapabilityGateway.new_correlation_id()
    return f"sess-{correlation_id}", correlation_id


async def _run(runtime, text: str):
    session_id, correlation_id = _session()
    intent = UserIntent(text=text, principal="human", session_id=session_id)
    context = RuntimeContext(correlation_id=correlation_id, session_id=session_id)
    result = await runtime.run(intent, context)
    return session_id, result


def _risk1_turn_on_registry() -> CapabilityRegistry:
    """turn_on 设为 risk=1（无需审批），便于聚焦测试 execute/verify 失败路径。"""
    reg = CapabilityRegistry()
    reg.register(CapabilityDefinition(
        id="home.climate.turn_on",
        device_type="climate",
        parameters={
            "temperature": ParameterSpec(type="integer", minimum=16, maximum=30),
            "mode": ParameterSpec(type="string", enum=["cool", "heat", "dry", "fan_only"], required=False),
        },
        risk={"default": 1},
        side_effect=SideEffect.REVERSIBLE_WRITE,
        operation=Operation.EXECUTE,
    ))
    return reg


# ---- 正常成功：审批闭环（自然语言 → 完整 StateGraph → AgentResult）----

async def test_e2e_success_approval_loop():
    comp = build_simulation_composition()
    rt = comp.runtime

    session_id, r1 = await _run(rt, "把客厅空调调到26度")
    assert r1.status == "needs_approval"
    approval_id = r1.evidence["approval_id"]
    assert approval_id
    assert comp.device.power == "off"  # 挂起未执行

    comp.gateway.approve(approval_id)
    r2 = await rt.resume(session_id, RuntimeEvent(event_type="approval", payload={"decision": "approve"}))

    assert r2.status == "completed"
    assert "SIMULATION 执行完成" in r2.message
    assert "V2 satisfied" in r2.message
    assert r2.evidence["verification_level"] == "V2"
    assert r2.evidence["verification_satisfied"] is True
    # 真实执行到模拟设备
    assert comp.device.power == "on"
    assert comp.device.temperature == 26

    # 完整 audit lifecycle（最少要求的事件类型）
    types = {e.event_type for e in comp.audit.events()}
    for required in (
        "user_input_received", "perceive_complete", "recall_complete", "reason_complete",
        "plan_created", "policy_evaluated", "needs_approval", "approval_granted",
        "approval_consumed", "execution_result", "verification_result", "memory_updated",
        "session_complete",
    ):
        assert required in types, f"missing audit event {required}"

    # memory 写入（session/correlation scoped）
    events = comp.memory.query_events(session_id=session_id)
    assert events
    assert events[0]["event_type"] == "action_completed"
    assert events[0]["correlation_id"] == r2.correlation_id


# ---- 用户拒绝审批 ----

async def test_e2e_user_rejects_approval():
    comp = build_simulation_composition()
    rt = comp.runtime

    session_id, r1 = await _run(rt, "开空调")
    assert r1.status == "needs_approval"

    r2 = await rt.resume(session_id, RuntimeEvent(event_type="approval", payload={"decision": "reject"}))
    assert r2.status == "rejected"
    assert comp.device.power == "off"  # 未执行
    # 不写成功记忆
    assert comp.memory.query_events(session_id=session_id) == []


# ---- policy 拒绝（参数越界）----

async def test_e2e_policy_reject_out_of_bounds():
    comp = build_simulation_composition()
    rt = comp.runtime

    _session_id, result = await _run(rt, "把空调调到100度")
    assert result.status == "rejected"
    assert "policy rejected" in result.message
    assert comp.device.power == "off"
    assert comp.mock_adapter.execute_calls == 0  # 绝不 execute


# ---- 验证失败 fail-closed 到安全终态 ----

async def test_e2e_verification_failure_fail_closed():
    device = MockDevice()
    device.set_fault(fail_actuation=True)  # 注入 actuation 失败
    comp = build_simulation_composition(registry=_risk1_turn_on_registry(), device=device)
    rt = comp.runtime

    _session_id, result = await _run(rt, "开空调")
    assert result.status == "failed"
    assert "verification failed" in result.message
    assert comp.device.power == "off"  # 未成功执行
    # 失败不写成功记忆
    assert comp.memory.query_events() == []
    # fail-closed 审计
    types = {e.event_type for e in comp.audit.events()}
    assert "compensated" in types
    assert "memory_updated" not in types


# ---- 审批 resume 不双计 rate-limit（一次真实动作只消耗一个名额）----

async def test_e2e_approval_resume_no_rate_limit_double_count():
    comp = build_simulation_composition(rate_limiter=RateLimiter(max_calls=1))
    rt = comp.runtime

    session_id, r1 = await _run(rt, "开空调")
    assert r1.status == "needs_approval"
    approval_id = r1.evidence["approval_id"]

    comp.gateway.approve(approval_id)
    # resume 的 re-policy 走 RateLimiter 幂等准入：同一 (capability, correlation_id)
    # 幂等放行且不重复计数（无任何 boolean bypass）。若仍双计，max_calls=1 会令 resume
    # 复审命中 rate limit → rejected。
    r2 = await rt.resume(session_id, RuntimeEvent(event_type="approval", payload={"decision": "approve"}))
    assert r2.status == "completed"
    assert comp.device.power == "on"


# ---- P0-2：audit correlation + chain integrity + 不伪造 policy_evaluated ----

async def test_e2e_audit_correlation_and_chain_integrity():
    comp = build_simulation_composition()
    rt = comp.runtime

    session_id, r1 = await _run(rt, "把客厅空调调到26度")
    assert r1.status == "needs_approval"
    approval_id = r1.evidence["approval_id"]
    comp.gateway.approve(approval_id)
    r2 = await rt.resume(session_id, RuntimeEvent(event_type="approval", payload={"decision": "approve"}))
    assert r2.status == "completed"

    events = comp.audit.events()
    assert events

    # 所有本轮 lifecycle audit record 的 correlation_id 都等于 result.correlation_id
    assert all(e.correlation_id == r2.correlation_id for e in events)

    # audit chain verify PASS（链式哈希完整，无断链）
    comp.audit.verify_chain()

    # policy_evaluated 不得因 execute_authorized_simulation 伪造重复（恰好 1 次真实 evaluate）
    policy_evaluated = [e for e in events if e.event_type == "policy_evaluated"]
    assert len(policy_evaluated) == 1

    # approval_granted 的 correlation_id 是原始 request correlation_id（非 approval_id）
    approval_granted = [e for e in events if e.event_type == "approval_granted"]
    assert approval_granted and approval_granted[0].correlation_id == r2.correlation_id
    assert approval_granted[0].correlation_id != approval_granted[0].data.get("approval_id")


# ---- stale / replay approval：会话终结后禁止再次 resume ----

async def test_e2e_approval_replay_rejected():
    comp = build_simulation_composition()
    rt = comp.runtime

    session_id, r1 = await _run(rt, "开空调")
    assert r1.status == "needs_approval"
    comp.gateway.approve(r1.evidence["approval_id"])

    r2 = await rt.resume(session_id, RuntimeEvent(event_type="approval", payload={"decision": "approve"}))
    assert r2.status == "completed"
    assert comp.mock_adapter.execute_calls == 1

    # 重放：同一会话再次 resume → 拒绝，绝不二次 execute
    r3 = await rt.resume(session_id, RuntimeEvent(event_type="approval", payload={"decision": "approve"}))
    assert r3.status == "rejected"
    assert comp.mock_adapter.execute_calls == 1


# ---- malformed model output → failed（不得伪装 completed）----

async def test_e2e_malformed_model_fail_closed():
    class _BoomModel:
        def reason(self, *, messages, intent, world_state, memory_context):
            raise ValueError("malformed model output")

    comp = build_simulation_composition(reasoning_model=_BoomModel())
    rt = comp.runtime

    _session_id, result = await _run(rt, "开空调")
    assert result.status == "failed"
    assert "reasoning failed" in result.message
    assert comp.device.power == "off"  # 未执行
    assert comp.mock_adapter.execute_calls == 0
    # 不写成功记忆
    assert comp.memory.query_events() == []
    # audit：reason_failed + session_complete(status=failed)
    events = comp.audit.events()
    types = {e.event_type for e in events}
    assert "reason_failed" in types
    session_complete = [e for e in events if e.event_type == "session_complete"]
    assert session_complete and session_complete[-1].data["status"] == "failed"


# ---- 正常 non-actionable NOOP → completed（与 malformed 可区分）----

async def test_e2e_noop_completed_distinct_from_failure():
    class _NoopModel:
        def reason(self, *, messages, intent, world_state, memory_context):
            from physical_agent.runtime.planning import ReasoningDecision, ReasoningRoute
            return ReasoningDecision(route=ReasoningRoute.NOOP, rationale="nothing to do")

    comp = build_simulation_composition(reasoning_model=_NoopModel())
    rt = comp.runtime

    _session_id, result = await _run(rt, "随便聊聊")
    assert result.status == "completed"
    assert "no actionable capability" in result.message
    assert comp.mock_adapter.execute_calls == 0
    # 正常 NOOP 不写 reason_failed
    types = {e.event_type for e in comp.audit.events()}
    assert "reason_failed" not in types


# ---- 无需审批路径：turn_off ----

async def test_e2e_turn_off_no_approval():
    comp = build_simulation_composition()
    comp.device.power = "on"  # 前置：已开启才能关
    rt = comp.runtime

    _session_id, result = await _run(rt, "关空调")
    assert result.status == "completed"
    assert comp.device.power == "off"
    types = {e.event_type for e in comp.audit.events()}
    assert "needs_approval" not in types
