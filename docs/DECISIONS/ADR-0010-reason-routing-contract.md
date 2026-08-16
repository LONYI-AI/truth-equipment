# ADR-0010: Reason → Graph 路由契约（ReasoningRoute typed contract）

## Status

**Proposed / Pending Owner Approval**

> **治理铁律（对应 P0-9）**：模拟角色审查不等于项目正式批准。本 ADR 只有在 **Owner**
> 通过 Architecture Gate 后方可置为 Accepted。

## Context

M1A-W2 首次实现（patch `m1a-w2.patch`，SHA256 `531269c3...`）存在一个路由语义错误，
被判定 **SUPERSEDED / REVISION REQUIRED**：

- W1（baseline `3b23105`）的 `route_after_reason` 语义：`has_plan=True → plan`，
  `has_plan=False → policy_gate`。这里的 `has_plan=False` 实际含义是 **direct path**
  （actionable 但无需结构化计划，直接进 policy）。
- W2 首次实现把 `has_plan` 赋值为 `ReasoningDecision.actionable`。于是
  `actionable=False`（non-actionable / no-op）被错误路由到 `policy_gate`。

问题本质：**用单一 `bool` 同时表示「是否 actionable」与「是否需要 plan」**，导致
non-actionable 请求可能进入 policy / execute / verify 路径，破坏安全边界。

整改要求（P0）：不得在 policy_gate 内以 `current_plan is None` 来掩盖此错误；
Reason → Graph 边界自身必须语义正确。

## Decision

**采用 typed contract `ReasoningRoute`（`StrEnum`）作为 Reason → Graph 的唯一路由信号，
替代 `has_plan: bool`。**

`ReasoningRoute` 三态，语义无歧义：

| 枚举 | 语义 | 路由目标 |
|---|---|---|
| `PLAN` | planned actionable request：需要先结构化为 `Plan` | `plan` → `policy_gate` |
| `DIRECT` | direct actionable request：显式保留 W1 direct path | `policy_gate` |
| `NOOP` | non-actionable / no-op | `END`（安全终态） |

具体落实：

1. `ReasoningDecision.route: ReasoningRoute`（默认 `NOOP`）；一致性校验：
   `PLAN`/`DIRECT` 必须携带 `capability_id`，`NOOP` 不得携带 `capability_id`。
   保留派生只读属性 `is_actionable`（`route != NOOP`），仅用于可读性与校验，
   **不参与路由**。
2. `AgentState.route: ReasoningRoute` 替换 `has_plan: bool`。
3. `route_after_reason` 依据 `route` 返回 `"plan"` / `"policy_gate"` / `"noop"`；
   `"noop"` 经 `add_conditional_edges` 映射到 `END`。缺失/未知一律 `"noop"`（fail-closed）。
4. **Reason 每轮无条件 invalidate 任何 prior `current_plan`**：Reason handler 对
   `PLAN` / `DIRECT` / `NOOP` 一律输出 `current_plan=None`。**只有 `plan` 节点是
   `current-plan` 的唯一生产者**（为本轮生成新 Plan）。DIRECT / NOOP 均不得携带
   旧 Plan 越过 Reason 边界。
5. **DIRECT 到 policy boundary 的 canonical current-action 来源是 `reasoning`**（本轮
   的 `ReasoningDecision`），**不是 `current_plan`**。policy 不得把遗留 `current_plan`
   当成 DIRECT 本轮请求——由于 Reason 已无条件清空 `current_plan`，policy 内
   `current_plan` 恒为 `None`（或仅当本轮经 `plan` 节点后才非空）。

保留 W1 direct path（`DIRECT → policy_gate`），不改动 W1 的 `route_after_policy` /
`route_after_verify` 语义。

## Consequences

### 正面影响

- non-actionable / no-op 请求在 Reason 边界安全终止，绝无进入 policy/execute/verify 的可能。
- 三态路由语义明确，消除 bool 混用的歧义与后续误用风险。
- **stale-plan lifecycle invariant**：Reason 每轮无条件 invalidate 旧计划；`plan` 节点
  是 `current-plan` 的唯一生产者，旧 plan 在任何路由（含 DIRECT）下都不会越过 Reason 边界。
- 真实 `graph.invoke()/ainvoke()` 回归测试覆盖 A（planned）/ B（non-actionable）/
  C（stale-plan NOOP）/ D（direct）四条路径，另含 stale Plan + DIRECT、stale Plan + PLAN
  的 lifecycle regression。

### 负面影响 / 风险

- W1 的 `has_plan` 字段被移除，`test_graph.py` / `test_state.py` 相应断言需同步更新
  （已在 W2 REV2 patch 内完成，非静默变更）。
- `ReasoningDecision` 的公开字段由 `actionable` 改为 `route`，为破坏性变更；W2 尚未
  有下游消费者（W3 未开始），影响面可控。

### 替代方案（未选中的）

- **在 policy_gate 内判断 `current_plan is None` 来兜底**：被否决——把语义错误推迟到
  下游掩盖，Reason/Graph 边界本身仍错误，且无法防止 stale plan 复用。
- **取消 direct path，只保留 plan/noop 两态**：被否决——W1 架构明确支持
  `direct_tool_call`（ARCHITECTURE.md §2.1），取消需额外改动 W1 契约，收益不明确。
- **保留 `actionable` bool + 新增 `needs_plan` bool**：被否决——两个 bool 的组合仍易
  出现非法态（如 `actionable=False, needs_plan=True`），不如单枚举强约束。

## Related ADRs

- ADR-0003：Agent 运行时 = LangGraph StateGraph + ModelProvider 抽象（本 ADR 细化其
  Reason 节点的输出契约）。
- ADR-0005：Policy Gate（在 Reason/Plan 与 Execute 之间；本 ADR 明确其上游边界）。

## References

- LangGraph `add_conditional_edges` / `END` 语义：
  https://langchain-ai.github.io/langgraph/
- `docs/ARCHITECTURE.md` §2.1 控制流图（已同步更新为三态路由）。

## Date

2026-08-16

## Revision

- **REV3**（2026-08-16）：将 stale-plan 规则从「NOOP 时清除」升级为「Reason 每轮
  无条件 invalidate prior `current_plan`；`plan` 节点是 `current-plan` 的唯一生产者」，
  修复「stale Plan + DIRECT 越过 Reason 边界到达 Policy」的残留 lifecycle defect。
  新增 DIRECT→policy boundary 的 canonical current-action 声明（`reasoning` 而非
  `current_plan`）。

## Reviewers

- `Reviewed-by-simulated-role`: Principal Architect、Agent Runtime Engineer、QA / Red-Team
- **Note**: 模拟角色审查不等于项目正式批准。最终由 **Owner** 通过 Architecture Gate。
