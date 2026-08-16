# ADR-0005: Policy Gate — 上下文风险分级与参数校验

## Status
**Proposed / Pending Owner Approval**（原 v0.1 为 Accepted，已撤回，见 P0-9）

## Context

任务书原方案：LLM 输出的 tool call 直通 HA，无任何策略闸门。这是致命缺陷（LLM 幻觉可转化为物理动作）。

原 v0.1 ADR-0005 引入了 Policy Gate，但风险分级过于粗糙（"开空调 = Tier 2 每次人工批准"），导致既不够安全又不够自动化。

外部审查指出：
1. 风险应是**多维函数**，而非单一静态 Tier。
2. 需要同时做到安全 + 真正自动化。
3. 原伪代码在 `def` 中使用 `await`，为语法错误。

## Decision

**在 Agent Runtime 与 Adapter 之间插入 Policy Gate，风险分级采用上下文感知的多维模型。**

### 风险模型（修订，对应 P1-3）

```
risk = f(
    principal,      # 触发者身份（唯一人类 admin / automation / agent）
    device,         # 目标设备（已知/未知）
    capability,     # 能力类型（只读/写/配置）
    action,         # 具体动作
    parameters,     # 参数（温度、模式等）
    environment     # 环境上下文（时间、房间、是否有人、安全规则）
)
```

### 分级策略（示例，非穷举）

| 场景 | 分级 | 说明 |
|---|---|---|
| 正常家庭：AC on, cool, 24-28℃, 已批准房间, 正常时段 | **Tier 1（有界自动）** | 参数在安全边界内 + 正常上下文 |
| 异常温度（如 16℃ 或 32℃）| **Tier 2（确认）** | 参数超出舒适区间 |
| 连续快速启停（防压缩机损坏）| **Tier 2（确认）** | 违反设备保护规则 |
| 无人长时间运行 / 深夜 | **Tier 2（确认）** | 环境上下文异常 |
| override 安全规则 | **Tier 2（确认）** | 显式越权 |
| 未知设备 / 未映射 capability | **Tier 2（拒绝→确认）** | 白名单外 |
| 删除设备 / 修改安全配置 | **Tier 3（仅手动）** | 禁止自动 |

### 核心不变式

> **LLM 的输出永远不可信。所有物理写动作必须经过确定性（非 LLM）的 Policy Gate 校验。**

Policy Gate 是**确定性代码**，不依赖任何 LLM 判断。

### 校验顺序

```
1. schema 校验（类型/必填）
2. capability 白名单（该 principal 是否有权调用该 device.action）
3. 参数边界（temperature ∈ [16,30] 等）
4. 速率限制（滑动窗口）
5. 上下文风险分级（决定自动/确认/拒绝）
6. Kill switch 检查
7. 审计埋点
```

## 伪代码（语法修正，对应 P0-11）

```python
# services/policy_gate/gate.py（接口，M1A 实现）
from dataclasses import dataclass
from typing import Literal

Tier = Literal[0, 1, 2, 3]

@dataclass
class Decision:
    allowed: bool
    tier: Tier
    reason: str
    requires_approval: bool = False

class PolicyGate:
    def __init__(self, *, kill_switch: "KillSwitch", audit: "AuditSink") -> None:
        self.kill_switch = kill_switch
        self.audit = audit

    # 注意：async def，await 合法
    async def evaluate(self, *, principal: str, device: str,
                       capability: str, action: str,
                       parameters: dict, context: dict) -> Decision:
        if self.kill_switch.is_active and capability != "read":
            return Decision(allowed=False, tier=3, reason="kill switch active")

        if not self._schema_valid(capability, parameters):
            return Decision(allowed=False, tier=3, reason="schema violation")

        if not self._in_allowlist(principal, device, action):
            return Decision(allowed=False, tier=3, reason="not in allowlist")

        if not self._params_in_bounds(capability, parameters):
            return Decision(allowed=False, tier=3, reason="parameter out of bounds")

        if await self._rate_limited(device, action):
            return Decision(allowed=False, tier=3, reason="rate limited")

        tier = self._classify(device, capability, action, parameters, context)
        self.audit.record("policy_evaluated", {...})
        return Decision(allowed=True, tier=tier,
                        requires_approval=(tier >= 2))
```

## Consequences

### 正面影响
- 安全与自动化平衡：正常操作自动放行，异常上下文升级确认
- 多维风险模型比静态 Tier 更贴近真实使用
- 确定性 gate 与 LLM 决策完全分离

### 负面影响 / 风险
- ⚠️ 上下文规则需维护（规则集随设备/场景增长）
  - 缓解：规则表数据驱动，M1 只实现 AC 域的最小规则集

## M1A-W3 实现（Policy Gate 集成）

W3 将本 ADR 的 Policy Gate 落为真实 graph 节点，明确以下契约：

1. **typed contract**：graph 路由信号用 `PolicyRoute`（`APPROVED` / `REJECTED` /
   `NEEDS_APPROVAL`），**由本轮真实 M0 `PolicyDecision` 确定性派生**
   （`derive_policy_route`），不再使用字符串 `policy_verdict`、不依赖 LLM。
2. **canonical request**：Policy Gate 只处理**一个明确的本轮 `CapabilityRequest`**。
   - PLAN 路径：`current_plan.steps` 必须恰有 1 个 step，correlation_id 与本轮一致。
   - DIRECT 路径：由本轮 `ReasoningDecision` 确定性转换为 M0 `CapabilityRequest`，
     参数**原样透传**（例如 `temperature=100` 以 `100` 到达 PolicyEngine 再被拒绝，
     禁止 Policy 前 clamp）。
   - 任何缺失 / 矛盾 / 未知 capability / 异常 → fail-closed（REJECTED），绝不 execute。
3. **stale-policy invariant（REV2）**：每次 policy_gate 调用**无条件 invalidate** 上一轮
   policy/approval 授权状态的**全部五个字段**：`policy_decision`、`current_request`、
   `approval_id`、`canonical_request_hash`、`needs_human_review`，再由本轮结果重新建立。
   旧 `approved` 不得被本轮复用。**canonical extraction failure 与 `PolicyEngine.evaluate`
   exception 均必须 fail-closed 且显式清空上述五字段**——否则上一轮 approved decision /
   旧 canonical request 会经 partial state merge 残留，被误当成本轮授权（REV2 修复点）。
4. **复用 M0**：直接复用 `PolicyEngine`（kill switch / registry allowlist / schema /
   rate limit / risk classify）、`KillSwitch`、`RateLimiter`，不重建第二套。

## Related ADRs
- ADR-0001: Capability Gateway（Policy 在此层执行）
- ADR-0006: 物理验证（验证结果反馈给 Policy 决定重试/升级）

## References
- 无外部依赖，纯设计决策。

## Date
2026-08-16（v0.2 修订）

## Reviewers
- Reviewed-by-simulated-role: Agent Runtime Engineer、QA/Red-Team Engineer
- **Note**: 模拟角色审查不等于项目正式批准。最终由 **Owner** 通过 Architecture Gate。
