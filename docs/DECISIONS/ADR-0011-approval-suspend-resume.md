# ADR-0011: Approval Suspend / Resume — LangGraph interrupt + 重新校验 + 单次消费

## Status

**Proposed / Pending Owner Approval**

> **治理铁律（对应 P0-9）**：模拟角色审查不等于项目正式批准。本 ADR 只有在 **Owner**
> 通过 Architecture Gate 后方可置为 Accepted。

## Context

M1A-W1/W2 只在 graph 拓扑里留了 `human_review` 边界节点，没有实现审批挂起/恢复。
W3 正式实现 M1A approval suspend/resume lifecycle：

```
policy_gate ─ NEEDS_APPROVAL → human_review ─(interrupt 挂起)→ Owner 审批
      → resume → 重新执行当前 Policy → ApprovalEngine.consume（单次）→ Execute boundary
```

关键安全约束（来自 M0 `CapabilityGateway.execute_approved()` 已确立的语义）：

> approval 是绑定授权，不是绕过当前 Policy 的许可证。

因此 resume 后不能简单 `if approved: execute`，必须先重新校验。

## Decision

**用 LangGraph 真实 `interrupt()` / `Command(resume=...)` + checkpointer 实现审批挂起/恢复；
resume 后对同一 canonical request 重新执行当前 Policy，仅当仍允许且 `ApprovalEngine.consume`
单次消费成功，才授权到达 Execute boundary。**

具体机制：

1. **挂起**：`human_review` 节点首次进入时调用 `interrupt(payload)`（payload 含
   `approval_id` / `canonical_request_hash` / `correlation_id`），graph 挂起并返回给调用方。
   调用方需经 `build_graph(handlers, checkpointer=...)` 传入 checkpointer
   （M1A simulation 用 `InMemorySaver`）。
2. **恢复**：调用方用 `Command(resume={"decision": "approve"|"reject"})` 恢复。
3. **重新校验（re-policy）**：对 `state.current_request`（本轮 canonical request）再次
   `PolicyEngine.evaluate`。当前 Policy 已拒绝（如 grant 后 kill switch 打开、风险条件
   改变）→ REJECTED，不消费、不 execute。
4. **单次消费**：仍允许时 `ApprovalEngine.consume(approval_id, request, tier)`——
   校验 correlation_id / principal / device_id / capability_id / canonical_request_hash /
   risk_tier 全部一致，且单次使用、过期、防重放。任何不匹配/过期/重放 → REJECTED。
5. **授权边界**：消费成功 → `policy_route = APPROVED` → 到达 Execute boundary
   （M1A 只到此处，Execute 为 injected spy/sentinel，无生产执行）。

**State 契约**（`AgentState` 新增/保留）：
- `current_request: CapabilityRequest | None` —— 本轮 canonical request（跨 checkpoint 保留）。
- `policy_decision: PolicyDecision | None` —— 本轮真实 M0 PolicyDecision。
- `policy_route: PolicyRoute` —— 由 PolicyDecision 确定性派生。
- `approval_id` / `canonical_request_hash` / `needs_human_review` —— 审批挂起元数据。

## Consequences

### 正面影响

- 真实 LangGraph interrupt/checkpoint（非自造 checkpoint、非全局 dict 冒充恢复）。
- 批准是绑定授权而非永久通行证：grant 后 kill switch / 风险 / 参数 / device /
  principal / capability 任何变化都导致 resume 拒绝。
- 单次消费 + 防重放由 M0 `ApprovalEngine.consume` 保证（不重造）。

### 负面影响 / 风险

- checkpointer 需要调用方显式传入；无 checkpointer 的图不可 interrupt（无审批路径不受影响）。
- Pydantic/dataclass 对象存入 checkpoint 状态，langgraph 1.2.11 会输出一条
  「unregistered msgpack type」的未来版本弃用提示（当前版本无害；未来升级需
  `allowed_msgpack_modules` 显式登记）。
- M1A 审批后端（ApprovalEngine）为 in-memory；PHYSICAL 持久化审批属后续里程碑。

### 替代方案（未选中的）

- **resume 后直接 `if approved: execute`**：被否决——绕过当前 Policy，违反 M0 已确立的
  「绑定授权，非永久通行证」语义。
- **自造 checkpoint/resume（全局 dict 存挂起状态）**：被否决——不是真实 LangGraph
  恢复，无法保留 session/correlation/canonical request，属伪装持久化。
- **不实现 suspend，仅以 helper 函数模拟**：被否决——测试只调用 helper、不实际恢复 graph，
  不能证明挂起后不执行、恢复后单次执行。

## Related ADRs

- ADR-0003：Agent 运行时 = LangGraph StateGraph（本 ADR 使用其 interrupt/checkpoint 机制）。
- ADR-0005：Policy Gate（本 ADR 实现其 `requires_approval` 分支的挂起/恢复）。
- ADR-0010：Reason → Graph 路由契约（canonical request 的 PLAN/DIRECT 来源）。

## References

- LangGraph interrupt / Command(resume) / checkpointer 官方文档（按 pinned `langgraph==1.2.11`
  实际 API 核对，未凭记忆猜测）：
  https://langchain-ai.github.io/langgraph/

## Date

2026-08-16

## Reviewers

- `Reviewed-by-simulated-role`: Agent Runtime Engineer、QA / Red-Team、Platform / Security
- **Note**: 模拟角色审查不等于项目正式批准。最终由 **Owner** 通过 Architecture Gate。
