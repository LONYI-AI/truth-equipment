# ADR-0000: Architecture Decision Record Template

每个 ADR 必须包含以下字段。

---

## Title（标题）

简短描述决策内容的名词短语。

## Status（状态）

- **Proposed / Pending Owner Approval**（提议中，待 Owner 批准）：**所有 ADR 在 Architecture Gate 通过前的默认状态**
- **Accepted**（已采纳）：**仅由 Owner 通过 Architecture Gate 后**才可置为 Accepted
- **Deprecated**（已废弃）：被新 ADR 替代
- **Superseded**（已取代）：被新 ADR 完全替代

> **治理铁律（对应 P0-9）**：模拟角色的审查（Architect / IoT / QA 等）只可记录为 `Reviewed-by-simulated-role`，**不等同项目正式批准**。只有 **Owner** 能通过 Architecture Gate 将 ADR 置为 Accepted。

## Context（背景）

描述问题、动机、触发本决策的事件或需求。
包含：
- 当前状态/问题是什么？
- 为什么需要做这个决策？
- 有哪些约束条件？

## Decision（决定）

明确说明选择了什么方案。
用一句话概括核心决策，然后展开细节。

## Consequences（后果）

### 正面影响
- 好处 1
- 好处 2

### 负面影响 / 风险
- 代价 1
- 风险 1

### 替代方案（未选中的）
- 方案 A 及其未选中原因
- 方案 B 及其未选中原因

## Related ADRs（关联 ADR）

- ADR-XXXX：相关决策
- ADR-YYYY：依赖此决策的后续决策

## References（参考）

官方文档链接、讨论记录、测试数据等。

## Date（日期）

YYYY-MM-DD

## Reviewers（审查者）

- `Reviewed-by-simulated-role:` 列出参与审查的模拟角色（Architect、IoT Engineer 等）。
- 必须附注：模拟角色审查**不等于**项目正式批准，最终由 **Owner** 通过 Architecture Gate。
