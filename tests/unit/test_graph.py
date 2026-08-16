"""M1A-W1 REV2 graph 骨架测试：真实 LangGraph 拓扑 + 条件路由 + async 节点。

不 mock StateGraph；注入 deterministic handler 验证真实编译与路由。
零物理执行：graph 骨架模块不引用 adapter / safety / execution。

M1A-W2 REV2 整改：Reason → Graph 边界改用 typed contract `ReasoningRoute`
（PLAN / DIRECT / NOOP），本文件中的 direct-path 测试改用 `route=DIRECT` 表达，
NOOP 为安全终态（新增断言）。
"""

from __future__ import annotations

import inspect
import tomllib
from importlib.metadata import version
from pathlib import Path

from langgraph.graph import END, START, StateGraph

from physical_agent.capability.schema import VerificationLevel
from physical_agent.runtime.graph import (
    NODE_NAMES,
    NodeHandlers,
    build_graph,
    route_after_policy,
    route_after_reason,
    route_after_verify,
)
from physical_agent.runtime.planning import ReasoningRoute
from physical_agent.runtime.state import WorldState
from physical_agent.verification.evidence import VerificationEvidence


def _make_handlers(visited: list[str], **overrides) -> NodeHandlers:
    """构造 NodeHandlers：默认 handler 记录节点名并返回空更新；overrides 覆盖特定节点。"""

    def make(name):
        def handler(state):
            visited.append(name)
            return {}
        return handler

    handlers = {name: make(name) for name in NODE_NAMES}
    handlers.update(overrides)
    return NodeHandlers(**handlers)


def _sim_verification(physical_effect: str = "confirmed") -> VerificationEvidence:
    """模拟验证证据：真实 VerificationEvidence + simulated provenance，不声称真实 V2/V3/V4。"""
    return VerificationEvidence(
        correlation_id="c1",
        capability_id="home.climate.turn_on",
        level=VerificationLevel.V2,
        evidence={"provenance": "simulated"},
        physical_effect=physical_effect,
    )


# ---- 真实 langgraph 导入 + 精确版本 ----

def test_real_langgraph_import():
    import langgraph.graph as lg

    assert lg.StateGraph is StateGraph
    assert lg.START is START
    assert lg.END is END


def test_exact_langgraph_version():
    # 依赖声明精确 pin
    data = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    deps = data["project"]["dependencies"]
    assert "langgraph==1.2.11" in deps
    # 实际安装版本一致
    assert version("langgraph") == "1.2.11"


# ---- 编译 + 节点名 ----

def test_graph_compiles_with_real_stategraph():
    graph = build_graph(_make_handlers([]))
    assert hasattr(graph, "invoke")
    assert hasattr(graph, "ainvoke")
    assert hasattr(graph, "get_graph")


def test_expected_node_names_present():
    graph = build_graph(_make_handlers([]))
    nodes = set(graph.get_graph().nodes)
    assert set(NODE_NAMES) <= nodes


# ---- 路由函数（unit，派生自真实 VerificationEvidence）----

def test_route_after_policy():
    assert route_after_policy({"policy_verdict": "approved"}) == "execute"
    assert route_after_policy({"policy_verdict": "rejected"}) == "escalate"
    assert route_after_policy({"policy_verdict": "needs_approval"}) == "human_review"
    assert route_after_policy({}) == "escalate"  # fail-closed default


def test_route_after_verify():
    confirmed = _sim_verification("confirmed")
    failed = _sim_verification("failed")
    assert route_after_verify({"verification": confirmed}) == "memory_update"
    assert route_after_verify({"verification": failed, "retry_count": 0}) == "execute"
    assert route_after_verify({"verification": failed, "retry_count": 1}) == "execute"
    assert route_after_verify({"verification": failed, "retry_count": 2}) == "compensate"
    # 无 verification 视为失败 → 重试
    assert route_after_verify({"retry_count": 0}) == "execute"


def test_route_after_reason():
    # typed contract：PLAN / DIRECT / NOOP 三态无歧义
    assert route_after_reason({"route": ReasoningRoute.PLAN}) == "plan"
    assert route_after_reason({"route": ReasoningRoute.DIRECT}) == "policy_gate"
    assert route_after_reason({"route": ReasoningRoute.NOOP}) == "noop"
    # 缺失/未知 → noop（fail-closed 安全终态）
    assert route_after_reason({}) == "noop"


# ---- 状态传播（成功路径，sync）----

def test_state_propagates_through_real_graph():
    visited: list[str] = []

    def perceive(state):
        visited.append("perceive")
        return {
            "session_id": "s1",
            "correlation_id": "c1",
            "world_state": WorldState(provenance="simulated"),
        }

    def reason(state):
        visited.append("reason")
        return {"route": ReasoningRoute.PLAN}

    def plan(state):
        visited.append("plan")
        return {"current_plan": {"steps": ["home.climate.turn_on"]}}

    def policy_gate(state):
        visited.append("policy_gate")
        return {"policy_verdict": "approved", "needs_human_review": False}

    def execute(state):
        visited.append("execute")
        return {"execution_history": [{"capability_id": "home.climate.turn_on"}]}

    def verify(state):
        visited.append("verify")
        return {"verification": _sim_verification("confirmed")}

    def memory_update(state):
        visited.append("memory_update")
        return {}

    handlers = _make_handlers(
        visited,
        perceive=perceive,
        reason=reason,
        plan=plan,
        policy_gate=policy_gate,
        execute=execute,
        verify=verify,
        memory_update=memory_update,
    )
    graph = build_graph(handlers)
    result = graph.invoke({"messages": []})

    assert result["session_id"] == "s1"
    assert result["correlation_id"] == "c1"
    assert result["verification"].physical_effect == "confirmed"
    assert result["world_state"].provenance == "simulated"
    assert visited == [
        "perceive", "recall", "reason", "plan", "policy_gate",
        "execute", "verify", "memory_update",
    ]


def test_real_verification_evidence_used():
    """graph 状态中的 verification 是真实 M0 VerificationEvidence（非 ad-hoc dict）。"""
    handlers = _make_handlers(
        [],
        reason=lambda s: {"route": ReasoningRoute.DIRECT},
        policy_gate=lambda s: {"policy_verdict": "approved"},
        verify=lambda s: {"verification": _sim_verification("confirmed")},
    )
    graph = build_graph(handlers)
    result = graph.invoke({"messages": []})
    assert isinstance(result["verification"], VerificationEvidence)
    # simulated provenance
    assert result["verification"].evidence["provenance"] == "simulated"


# ---- 条件路由（真实 graph 运行）----

def test_conditional_success_route():
    visited: list[str] = []
    handlers = _make_handlers(
        visited,
        reason=lambda s: {"route": ReasoningRoute.DIRECT},
        policy_gate=lambda s: {"policy_verdict": "approved"},
        verify=lambda s: {"verification": _sim_verification("confirmed")},
    )
    graph = build_graph(handlers)
    graph.invoke({"messages": []})
    assert "memory_update" in visited
    assert "compensate" not in visited


def test_conditional_retry_route():
    visited: list[str] = []
    verify_calls: list[int] = []

    def verify(state):
        verify_calls.append(1)
        if len(verify_calls) == 1:
            return {"verification": _sim_verification("failed"), "retry_count": 1}
        return {"verification": _sim_verification("confirmed")}

    handlers = _make_handlers(
        visited,
        reason=lambda s: {"route": ReasoningRoute.DIRECT},
        policy_gate=lambda s: {"policy_verdict": "approved"},
        verify=verify,
    )
    graph = build_graph(handlers)
    graph.invoke({"messages": []})
    assert visited.count("execute") == 2  # 失败 → retry → 成功
    assert "memory_update" in visited


def test_conditional_compensate_route():
    visited: list[str] = []
    handlers = _make_handlers(
        visited,
        reason=lambda s: {"route": ReasoningRoute.DIRECT},
        policy_gate=lambda s: {"policy_verdict": "approved"},
        verify=lambda s: {"verification": _sim_verification("failed"), "retry_count": 2},
    )
    graph = build_graph(handlers)
    graph.invoke({"messages": []})
    assert "compensate" in visited
    assert "memory_update" not in visited


def test_policy_reject_route():
    visited: list[str] = []
    handlers = _make_handlers(
        visited,
        reason=lambda s: {"route": ReasoningRoute.DIRECT},
        policy_gate=lambda s: {"policy_verdict": "rejected"},
    )
    graph = build_graph(handlers)
    graph.invoke({"messages": []})
    assert "escalate" in visited
    assert "execute" not in visited


def test_noop_safe_terminal_route():
    """NOOP 路由：真实 graph 运行中 non-actionable 直达 END，不触达任何下游节点。"""

    def reason(state):
        visited.append("reason")
        return {"route": ReasoningRoute.NOOP}

    visited: list[str] = []
    handlers = _make_handlers(
        visited,
        reason=reason,
    )
    graph = build_graph(handlers)
    result = graph.invoke({"messages": []})
    # 只有 perceive/recall/reason 被访问；plan/policy/execute/verify 等均未访问
    assert visited == ["perceive", "recall", "reason"]
    assert result["route"] is ReasoningRoute.NOOP


def test_approval_boundary_route():
    """审批挂起边界：needs_approval → human_review，且 approval 绑定元数据在边界存活。"""
    visited: list[str] = []
    handlers = _make_handlers(
        visited,
        reason=lambda s: {"route": ReasoningRoute.DIRECT},
        policy_gate=lambda s: {
            "policy_verdict": "needs_approval",
            "needs_human_review": True,
            "approval_id": "apv_1234567890ab",
            "canonical_request_hash": "sha256:deadbeef",
        },
    )
    graph = build_graph(handlers)
    result = graph.invoke({"messages": [], "session_id": "s1", "correlation_id": "c1"})

    assert "human_review" in visited
    assert "execute" not in visited
    # APPROVAL_ID_PRESERVED / CANONICAL_REQUEST_HASH_PRESERVED
    assert result["session_id"] == "s1"
    assert result["correlation_id"] == "c1"
    assert result["approval_id"] == "apv_1234567890ab"
    assert result["canonical_request_hash"] == "sha256:deadbeef"
    assert result["needs_human_review"] is True


# ---- 消息 reducer：官方 add_messages ----

def test_real_message_reducer():
    """messages 用官方 add_messages：按 ID 去重/更新，而非 list 拼接。"""
    from langchain_core.messages import AIMessage, HumanMessage
    from langgraph.graph.message import add_messages

    h1 = HumanMessage(content="hi", id="1")
    h2 = HumanMessage(content="hi updated", id="1")  # 同 ID，更新
    a1 = AIMessage(content="hello", id="2")
    merged = add_messages([h1], [h2, a1])
    assert len(merged) == 2  # 同 ID 去重，不是 3
    assert merged[0].content == "hi updated"
    assert merged[1].content == "hello"


def test_messages_accumulate_via_add_messages_in_graph():
    """graph 的 messages 字段跨节点累积（add_messages reducer，非覆盖）。"""
    from langchain_core.messages import HumanMessage

    handlers = _make_handlers(
        [],
        perceive=lambda s: {"messages": [HumanMessage(content="p", id="m1")], "route": ReasoningRoute.DIRECT},
        recall=lambda s: {"messages": [HumanMessage(content="r", id="m2")]},
        policy_gate=lambda s: {"policy_verdict": "approved"},
        verify=lambda s: {"verification": _sim_verification("confirmed")},
    )
    graph = build_graph(handlers)
    result = graph.invoke({"messages": []})
    assert len(result["messages"]) == 2  # 两条累积


# ---- async 节点 ----

async def test_real_async_node():
    """真实 LangGraph graph 支持 async 节点，经 ainvoke 执行。"""
    visited: list[str] = []

    async def perceive(state):
        visited.append("perceive")
        return {"session_id": "s1", "route": ReasoningRoute.DIRECT}

    async def policy_gate(state):
        visited.append("policy_gate")
        return {"policy_verdict": "approved"}

    async def verify(state):
        visited.append("verify")
        return {"verification": _sim_verification("confirmed")}

    handlers = _make_handlers(visited, perceive=perceive, policy_gate=policy_gate, verify=verify)
    graph = build_graph(handlers)
    result = await graph.ainvoke({"messages": []})

    assert "perceive" in visited
    assert "verify" in visited
    assert result["session_id"] == "s1"
    assert result["verification"].physical_effect == "confirmed"


# ---- 零物理执行 ----

def test_graph_skeleton_has_no_physical_execution_dependency():
    """graph 骨架模块不 import 任何物理执行路径（adapter/safety/execution）。"""
    import ast

    import physical_agent.runtime.graph as gm

    source = inspect.getsource(gm)
    tree = ast.parse(source)
    forbidden = ("physical_agent.adapters", "physical_agent.safety", "physical_agent.execution")
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            assert node.module not in forbidden, f"graph skeleton imports {node.module}"
        elif isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name not in forbidden, f"graph skeleton imports {alias.name}"


# ---- M0 运行时协议不破坏 ----

def test_m0_runtime_protocol_unbroken():
    from physical_agent.runtime.base import AgentResult, AgentRuntime
    from physical_agent.runtime.langgraph import LangGraphRuntime

    assert AgentRuntime is not None
    result = AgentResult(session_id="s", correlation_id="c", status="completed")
    assert result.status == "completed"
    assert result.correlation_id == "c"

    assert hasattr(LangGraphRuntime, "run")
    assert hasattr(LangGraphRuntime, "resume")
    assert hasattr(LangGraphRuntime, "cancel")
