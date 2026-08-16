"""M1A-W2 graph 兼容性与真实运行测试。

W2 REV2 整改：不再只做 build_graph()，而是真实 graph.invoke() / ainvoke() 验收：
- A. actionable planned path：perceive → recall → reason(PLAN) → plan → policy 边界，
     在 policy test handler 内断言真实 Plan / CapabilityRequest / 参数未 clamp。
- B. non-actionable path：perceive → recall → reason(NOOP) → 安全终态，plan/policy/
     execute/verify 等一律不调用（spies/sentinels）。
- C. stale-plan regression：注入旧 current_plan + NOOP，证明旧计划永不越过 Reason 边界。
- D. direct path：reason(DIRECT) → policy_gate，不经 plan（保留 W1 direct path）。
"""

from __future__ import annotations

import ast
import inspect

from tests.mock_llm import MockReasoningModel

from physical_agent.capability.request import CapabilityRequest
from physical_agent.memory.store import SqliteMemoryStore
from physical_agent.runtime.base import UserIntent
from physical_agent.runtime.graph import NODE_NAMES, NodeHandlers, build_graph
from physical_agent.runtime.nodes import (
    make_perceive_handler,
    make_plan_handler,
    make_reason_handler,
    make_recall_handler,
)
from physical_agent.runtime.nodes.perceive import PerceptionSnapshot, WorldStateSource
from physical_agent.runtime.planning import Plan, PolicyRoute, ReasoningDecision, ReasoningRoute


class _InlineSource(WorldStateSource):
    def read_snapshot(self) -> PerceptionSnapshot:
        return PerceptionSnapshot(
            devices={"climate.bedroom_ac": {"state": "off"}},
            environment={"room_temperature": 28},
        )


def _initial_state(**overrides):
    base = {
        "messages": [],
        "session_id": "s1",
        "correlation_id": "req-1",
        "intent": UserIntent(text="cool to 16", principal="human", session_id="s1"),
    }
    base.update(overrides)
    return base


def _sentinel(name: str):
    """后续 slice 的 test-only 边界 sentinel：被意外调用必须 FAIL（不返回 fake success）。"""

    def handler(state):
        raise AssertionError(f"W2 sentinel node '{name}' must not be invoked")

    return handler


def _recorder(name: str, sink: list[str]):
    def handler(state):
        sink.append(name)
        return {}

    return handler


def _base_handlers(store, model, **overrides):
    handlers = {
        "perceive": make_perceive_handler(_InlineSource()),
        "recall": make_recall_handler(store),
        "reason": make_reason_handler(model),
        "plan": make_plan_handler(),
        "policy_gate": _sentinel("policy_gate"),
        "execute": _sentinel("execute"),
        "verify": _sentinel("verify"),
        "compensate": _sentinel("compensate"),
        "memory_update": _sentinel("memory_update"),
        "escalate": _sentinel("escalate"),
        "human_review": _sentinel("human_review"),
    }
    handlers.update(overrides)
    return NodeHandlers(**handlers)


# ---- 基本编译契约（保留原 W2 兼容性检查）----

def test_w2_handlers_compatible_with_w1_graph():
    store = SqliteMemoryStore(":memory:")
    model = MockReasoningModel([ReasoningDecision(route=ReasoningRoute.PLAN, capability_id="home.climate.turn_on")])
    handlers = _base_handlers(store, model)
    graph = build_graph(handlers)
    # 真实 StateGraph 仍可编译，节点名齐全
    assert hasattr(graph, "invoke")
    assert hasattr(graph, "ainvoke")
    assert set(NODE_NAMES) <= set(graph.get_graph().nodes)


def test_w2_handlers_match_nodehandler_contract():
    """W2 四个 handler 工厂返回 sync NodeHandler（callable, state -> dict）。"""
    store = SqliteMemoryStore(":memory:")
    handlers = {
        "perceive": make_perceive_handler(_InlineSource()),
        "recall": make_recall_handler(store),
        "reason": make_reason_handler(MockReasoningModel()),
        "plan": make_plan_handler(),
    }
    for name, handler in handlers.items():
        assert callable(handler), f"{name} handler must be callable"


def test_w2_nodes_have_no_asyncio_run():
    """W2 节点不在 async flow 中使用 asyncio.run()（反模式）。"""
    import physical_agent.runtime.nodes.perceive as p
    import physical_agent.runtime.nodes.plan as pl
    import physical_agent.runtime.nodes.reason as re
    import physical_agent.runtime.nodes.recall as rc

    for mod in (p, rc, re, pl):
        assert "asyncio.run(" not in inspect.getsource(mod)


def test_w2_nodes_have_no_forbidden_imports():
    """AST 级：W2 四个节点不 import execution / safety.gateway / policy.approval。"""
    import physical_agent.runtime.nodes.perceive as p
    import physical_agent.runtime.nodes.plan as pl
    import physical_agent.runtime.nodes.reason as re
    import physical_agent.runtime.nodes.recall as rc

    forbidden = ("physical_agent.execution", "physical_agent.safety.gateway", "physical_agent.policy.approval")
    for mod in (p, rc, re, pl):
        for node in ast.walk(ast.parse(inspect.getsource(mod))):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert node.module not in forbidden, f"{mod.__name__} imports {node.module}"
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name not in forbidden, f"{mod.__name__} imports {alias.name}"


# ---- A. actionable planned path（真实 graph.invoke）----

def test_graph_invoke_actionable_planned_path():
    decision = ReasoningDecision(
        route=ReasoningRoute.PLAN,
        capability_id="home.climate.set_temperature",
        device_id="climate.bedroom_ac",
        parameters={"temperature": 100},  # 越界参数，必须不被 clamp
        rationale="cool down",
    )
    model = MockReasoningModel([decision])
    store = SqliteMemoryStore(":memory:")
    policy_calls: list[dict] = []
    escalated: list[str] = []

    def policy_gate(state):
        policy_calls.append(state)
        plan = state.get("current_plan")
        # 断言收到真实 Plan + M0 CapabilityRequest steps
        assert isinstance(plan, Plan), "policy must receive a real Plan"
        assert len(plan.steps) == 1
        step = plan.steps[0]
        assert isinstance(step, CapabilityRequest)
        assert step.capability_id == "home.climate.set_temperature"
        assert step.device_id == "climate.bedroom_ac"
        assert step.parameters == {"temperature": 100}  # 仍未 clamp
        assert step.principal == "human"
        assert step.correlation_id == "req-1"
        assert plan.session_id == "s1"
        assert plan.correlation_id == "req-1"
        # test-only reject → escalate → END，绝不执行 adapter
        return {"policy_route": PolicyRoute.REJECTED}

    handlers = _base_handlers(
        store,
        model,
        policy_gate=policy_gate,
        escalate=_recorder("escalate", escalated),
    )
    graph = build_graph(handlers)
    result = graph.invoke(_initial_state())

    assert len(policy_calls) == 1  # 计划确实到达 policy 边界
    assert escalated == ["escalate"]  # reject 走 escalate 终态
    assert result["current_plan"] is not None  # 计划在 policy 边界存活
    assert result["policy_route"] is PolicyRoute.REJECTED


# ---- B. non-actionable path（真实 graph.invoke）----

def test_graph_invoke_non_actionable_safe_terminal():
    model = MockReasoningModel([ReasoningDecision(route=ReasoningRoute.NOOP, rationale="nothing to do")])
    store = SqliteMemoryStore(":memory:")
    # 除 perceive/recall/reason 外全部 sentinel：任何越界调用都 FAIL
    handlers = _base_handlers(store, model)
    graph = build_graph(handlers)
    result = graph.invoke(_initial_state())

    # NOOP 安全终态：plan/policy_gate/execute/verify 等一律未调用（sentinel 未触发）
    assert result["route"] is ReasoningRoute.NOOP
    assert result["reasoning"].route is ReasoningRoute.NOOP
    assert result["current_plan"] is None


# ---- C. stale-plan regression（真实 graph.invoke）----

def test_graph_invoke_stale_plan_never_crosses_reason_boundary():
    # 人为注入一个「旧计划」，随后 Reason 返回 non-actionable（NOOP）
    old_plan = Plan(
        session_id="s-old",
        correlation_id="req-old",
        steps=[CapabilityRequest(capability_id="home.climate.turn_on", correlation_id="req-old")],
    )
    model = MockReasoningModel([ReasoningDecision(route=ReasoningRoute.NOOP)])
    store = SqliteMemoryStore(":memory:")
    handlers = _base_handlers(store, model)  # 全 sentinel（plan/policy/execute/verify...）
    graph = build_graph(handlers)
    result = graph.invoke(_initial_state(current_plan=old_plan))

    # 旧计划被显式清除，且未越过 Reason 边界（plan/policy/execute/verify 均未调用）
    assert result["current_plan"] is None
    assert result["route"] is ReasoningRoute.NOOP
    assert result["reasoning"].route is ReasoningRoute.NOOP


def test_graph_invoke_stale_plan_direct_path_cleared():
    """stale Plan + DIRECT：旧 plan 必须失效；policy 收到的 current_plan 为 None，
    reasoning 是本轮 DIRECT decision；plan 不调用、execute 不调用。"""
    old_plan = Plan(
        session_id="s-old",
        correlation_id="req-old",
        steps=[CapabilityRequest(capability_id="home.climate.turn_on", correlation_id="req-old")],
    )
    model = MockReasoningModel(
        [ReasoningDecision(route=ReasoningRoute.DIRECT, capability_id="home.climate.set_temperature")]
    )
    store = SqliteMemoryStore(":memory:")
    policy_calls: list[dict] = []
    escalated: list[str] = []

    def policy_gate(state):
        policy_calls.append(state)
        # 旧 plan 必须已被 Reason 无条件失效
        assert state.get("current_plan") is None
        # reasoning 是本轮 DIRECT decision（canonical current-action 来源）
        assert state["reasoning"].route is ReasoningRoute.DIRECT
        assert state["reasoning"].capability_id == "home.climate.set_temperature"
        return {"policy_route": PolicyRoute.REJECTED}

    handlers = _base_handlers(
        store,
        model,
        plan=_sentinel("plan"),  # DIRECT 不经过 plan
        policy_gate=policy_gate,
        escalate=_recorder("escalate", escalated),
    )
    graph = build_graph(handlers)
    result = graph.invoke(_initial_state(current_plan=old_plan))

    assert len(policy_calls) == 1  # policy_gate 被调用
    assert escalated == ["escalate"]
    assert result["current_plan"] is None  # 旧 plan 未残留（execute 未调用，sentinel 未触发）


def test_graph_invoke_stale_plan_replaced_by_new_plan():
    """stale Plan + PLAN：旧 plan 被失效；plan 节点生成本轮新 Plan；
    policy 只看到本轮 correlation/capability/parameters，不复用旧 step。"""
    old_plan = Plan(
        session_id="s-old",
        correlation_id="req-old",
        steps=[CapabilityRequest(capability_id="home.climate.turn_on", correlation_id="req-old")],
    )
    model = MockReasoningModel(
        [
            ReasoningDecision(
                route=ReasoningRoute.PLAN,
                capability_id="home.climate.set_temperature",
                device_id="climate.bedroom_ac",
                parameters={"temperature": 24},
                rationale="cool down this round",
            )
        ]
    )
    store = SqliteMemoryStore(":memory:")
    policy_calls: list[dict] = []
    escalated: list[str] = []

    def policy_gate(state):
        policy_calls.append(state)
        plan = state.get("current_plan")
        assert isinstance(plan, Plan)
        # 只能看到本轮 session / correlation
        assert plan.session_id == "s1"
        assert plan.correlation_id == "req-1"
        assert len(plan.steps) == 1
        step = plan.steps[0]
        assert step.correlation_id == "req-1"
        assert step.capability_id == "home.climate.set_temperature"
        assert step.parameters == {"temperature": 24}
        # 不得复用旧 step（旧 capability 必须消失）
        assert step.capability_id != "home.climate.turn_on"
        return {"policy_route": PolicyRoute.REJECTED}

    handlers = _base_handlers(
        store,
        model,
        policy_gate=policy_gate,
        escalate=_recorder("escalate", escalated),
    )
    graph = build_graph(handlers)
    result = graph.invoke(_initial_state(current_plan=old_plan))

    assert len(policy_calls) == 1
    assert escalated == ["escalate"]
    # 终态 current_plan 是本轮新 Plan，非旧 plan
    assert result["current_plan"].correlation_id == "req-1"
    assert result["current_plan"].steps[0].capability_id == "home.climate.set_temperature"


# ---- D. direct path（保留 W1 direct path，真实 graph.invoke）----

def test_graph_invoke_direct_path_preserved():
    model = MockReasoningModel(
        [ReasoningDecision(route=ReasoningRoute.DIRECT, capability_id="home.climate.turn_on")]
    )
    store = SqliteMemoryStore(":memory:")
    policy_calls: list[dict] = []
    escalated: list[str] = []

    def policy_gate(state):
        policy_calls.append(state)
        # DIRECT 不经过 plan：policy 收到的 current_plan 应为 None
        assert state.get("current_plan") is None
        return {"policy_route": PolicyRoute.REJECTED}

    handlers = _base_handlers(
        store,
        model,
        plan=_sentinel("plan"),  # DIRECT 绝不经过 plan
        policy_gate=policy_gate,
        escalate=_recorder("escalate", escalated),
    )
    graph = build_graph(handlers)
    result = graph.invoke(_initial_state())

    assert len(policy_calls) == 1  # DIRECT → policy_gate
    assert escalated == ["escalate"]
    assert result["policy_route"] is PolicyRoute.REJECTED


# ---- async（真实 graph.ainvoke）----

async def test_graph_ainvoke_non_actionable_safe_terminal():
    model = MockReasoningModel([ReasoningDecision(route=ReasoningRoute.NOOP)])
    store = SqliteMemoryStore(":memory:")
    handlers = _base_handlers(store, model)  # 全 sentinel
    graph = build_graph(handlers)
    result = await graph.ainvoke(_initial_state())

    assert result["route"] is ReasoningRoute.NOOP
    assert result["current_plan"] is None


async def test_graph_ainvoke_actionable_planned_path():
    model = MockReasoningModel(
        [
            ReasoningDecision(
                route=ReasoningRoute.PLAN,
                capability_id="home.climate.set_temperature",
                device_id="climate.bedroom_ac",
                parameters={"temperature": 100},
            )
        ]
    )
    store = SqliteMemoryStore(":memory:")
    policy_calls: list[dict] = []
    escalated: list[str] = []

    def policy_gate(state):
        policy_calls.append(state)
        assert isinstance(state.get("current_plan"), Plan)
        assert state["current_plan"].steps[0].parameters == {"temperature": 100}
        return {"policy_route": PolicyRoute.REJECTED}

    handlers = _base_handlers(
        store,
        model,
        policy_gate=policy_gate,
        escalate=_recorder("escalate", escalated),
    )
    graph = build_graph(handlers)
    result = await graph.ainvoke(_initial_state())

    assert len(policy_calls) == 1
    assert escalated == ["escalate"]
    assert result["current_plan"] is not None
