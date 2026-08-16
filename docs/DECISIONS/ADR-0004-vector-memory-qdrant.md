# ADR-0004: 记忆存储分层 — SQLite 为主，Qdrant 为 planned adapter

## Status
**Proposed / Pending Owner Approval**（原 v0.1 为 Accepted，已撤回，见 P0-9）

## Context

任务书原定用 Chroma 作为向量数据库。原 v0.1 决策弃用 Chroma、强制启用 Qdrant。

外部审查（P1-1）指出：**M1 并不需要向量数据库。** 为"有向量数据库"而启用 Qdrant，只会无谓增加 M1 的攻击面与运维复杂度。

### 关于 Chroma 的说明（v0.1 声明修正）

> v0.1 曾引用一个 Chroma 的 CVE 编号并称"截至 2026-08 未修复"。**该 CVE 编号在本轮未经官方渠道核实，属于未经验证的声明，已撤回。** 对 Chroma 的正式安全评估留待「只有出现明确 semantic retrieval 需求」时再做，并以官方 advisory 为准。当前结论仅是：**M1 不需要向量数据库，故既不选 Chroma 也不选 Qdrant。**

## Decision

**M1 记忆存储采用 SQLite（结构化）；Qdrant 保留为 planned adapter，仅当出现明确的 semantic retrieval acceptance case 时才启用。**

### MemoryStore 抽象

```python
# agent/memory/store.py（接口，M1A 实现）
from typing import Protocol

class MemoryStore(Protocol):
    async def append_event(self, event: dict) -> str: ...
    async def query_events(self, *, session_id: str | None = None,
                           limit: int = 100) -> list[dict]: ...
    async def get_preference(self, key: str) -> object | None: ...
    async def set_preference(self, key: str, value: object) -> None: ...

class SqliteMemoryStore:
    """M1 默认实现：episodic + preferences 全部落 SQLite。"""

class QdrantMemoryStore:
    """planned adapter：语义检索需求出现后再实现。"""
```

### M1 记忆分层（修订）

| 记忆类型 | M1 实现 | 说明 |
|---|---|---|
| Working memory | Agent State（LangGraph 内存）| 会话内 |
| Episodic / action history | **SQLite** | 时间序列/结构化查询足够 |
| Preferences | **SQLite（结构化）** | key-value/表 |

### 启用 Qdrant 的触发条件（acceptance case，非"以后再说"）

当以下任一明确需求出现时，才评估启用 Qdrant：
1. 需要按**语义相似度**检索历史自然语言事件（如"找出类似上次那种'回家很热'的场景"）
2. 偏好数据大到结构化查询无法高效处理（个人场景预计远达不到）
3. 多模态向量（视觉特征检索，Phase 2+ 可能触发）

## Consequences

### 正面影响
- ✅ M1 攻击面最小化（少一个对外服务、少一个密钥）
- ✅ 运维复杂度降低（少一个容器、少一次备份）
- ✅ SQLite 单文件、零配置、够用

### 负面影响 / 风险
- ⚠️ 未来若需要语义检索，需补 Qdrant 集成
  - 缓解：MemoryStore 接口已预留；QdrantMemoryStore 作为 planned adapter 接口已定义
- ⚠️ SQLite 并发写限制（单写者）
  - 缓解：个人场景单 Agent 单写者，无冲突

### 替代方案（未选中）
- **M1 即启用 Qdrant（原 v0.1）**：无谓增加攻击面与运维复杂度 ❌
- **M1 用 Chroma**：同样不需要；且 Chroma 安全评估未完成 ❌

## Related ADRs
- ADR-0003: Agent Runtime（Memory 是 Agent 子系统）
- ADR-0007: Secrets Management（Qdrant API Key 仅启用时才需要）

## References
- Qdrant Official Docs: https://qdrant.tech/documentation/
- SQLite: https://sqlite.org/

## Date
2026-08-16（v0.2 修订）

## Reviewers
- Reviewed-by-simulated-role: Principal Architect、Platform/Security Engineer
- **Note**: 模拟角色审查不等于项目正式批准。最终由 **Owner** 通过 Architecture Gate。
