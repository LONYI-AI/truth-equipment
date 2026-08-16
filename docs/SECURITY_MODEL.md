# SECURITY_MODEL — Physical AI Agent Platform 安全模型

版本：v0.2（2026-08-16，Architecture Audit v0.2）
状态：**Proposed / Pending Owner Approval**

> 当前安全模型以本文件为唯一事实来源；历史修订记录仅保留在 Git history。

---

## 1. 安全目标与原则

### 1.1 核心安全目标

| 目标 | 说明 | 优先级 |
|---|---|---|
| **机密性** | 密钥、令牌、用户数据不被未授权访问 | P0 |
| **完整性** | 审计日志 **tamper-evident**（可检测篡改，非"不可篡改"）；代码/配置可验证 | P0 |
| **可用性** | Kill switch 可立即禁用所有写动作 | P0 |
| **可追溯性** | 每次物理动作可追溯到触发者与推理链 | P0 |
| **非否认性** | 审计证据足以证明"谁在何时做了什么" | P1 |

### 1.2 安全原则

1. **最小权限**：每个组件仅持有所需最小权限
2. **纵深防御**：不依赖单一安全机制
3. **默认拒绝 + fail closed**：未显式允许即禁止；密钥缺失即拒绝启动（`${VAR:?}` 而非 `${VAR:-default}`）
4. **零信任**：内部组件间通信也需鉴权
5. **分离关注**：决策（LLM）≠ 执行（Gateway）≠ 验证（Verification）≠ 审计签名
6. **人工兜底**：高风险动作需人工确认

---

## 2. 身份与访问控制

### 2.1 角色定义

| 角色 | 权限范围 | 认证方式 |
|---|---|---|
| **Owner / Administrator**（唯一人类）| 全部权限：配置、密钥轮换、Tier 2+ 审批、备份恢复 | 密码 + 2FA（M1E+）|
| **Agent Runtime** | 经 Policy Gate 后的受限工具调用 | 内部 service token |
| **Read-Only Monitor** | 只读：状态、审计日志、监控面板 | Read-only token |
| **HA Integration** | 白名单设备读写 | HA 长期令牌（专用受限用户，见 §2.2）|

### 2.2 Home Assistant 授权模型（双层，对应 P0-5）

> **v0.1 错误已删除**：v0.1 曾声称"给 Integration Token 配置 entity-level permissions"。**HA 官方文档证实：long-lived token 无法在 UI 中做 entity-level scope 或 read-only scope，token 继承创建它的用户的全部权限。**（见 Evidence Matrix）

**正确设计：两层安全控制，明确区分"HA 凭据权限"与"Agent 授权策略"。**

#### Layer A — Dedicated non-admin HA user/credential（最小可用权限）

- 创建一个 **非管理员 HA 用户**（如 `agent_service`），通过 HA 用户角色体系限制其可访问范围。
- 用该受限用户生成 long-lived token。
- 该 token 的权限 = 该受限用户的权限，**是 HA 侧能做到的最细粒度**。
- 明确：**HA credential permission ≠ Agent authorization policy**（HA 只是"凭证能访问什么"，Agent 授权是"策略允许做什么"）。

#### Layer B — Deterministic Capability/Tool Gateway（确定性策略层）

| 控制 | 说明 |
|---|---|
| entity allowlist | 仅允许白名单实体（如 `climate.bedroom_ac`）|
| action allowlist | 仅允许白名单动作（如 `climate.set_temperature`）|
| schema validation | 参数类型/必填校验 |
| parameter bounds | 温度 16-30℃ 等边界 |
| context-aware policy | 上下文风险分级（见 ADR-0005）|
| rate limit | 滑动窗口限速 |
| kill switch | 一键禁用全部写动作 |
| audit | 每次调用落审计 |

#### 关键声明（对应 P0-5）

> **不得宣称 HA long-lived token 本身具有尚未验证的 per-token entity scopes。** HA token 是无 entity scope 的。真正的授权边界是 Layer B（Capability Gateway）提供的。

---

## 3. 动作风险分级与策略

（与 ADR-0005 保持一致，采用上下文感知多维模型）

```
risk = f(principal, device, capability, action, parameters, environment/context)
```

| 场景（示例）| 分级 |
|---|---|
| 正常：AC on, cool, 24-28℃, 已批准房间, 正常时段 | Tier 1（有界自动）|
| 异常温度 / 连续快速启停 / 无人长时间 / override / 未知设备 | Tier 2（确认）|
| 删除设备 / 修改安全配置 | Tier 3（仅手动）|

**校验顺序**：schema → capability 白名单 → 参数边界 → 速率限制 → 上下文分级 → kill switch → 审计。

---

## 4. Secrets 管理

### 4.1 分层存储

| 环境 | 存储 | 访问控制 | 轮换 |
|---|---|---|---|
| dev | `.env`（gitignored）| 文件权限 600 | 手动 |
| prod（M2+ 候选）| SOPS / Docker Secrets | 加密 | 90 天 |

### 4.2 密钥清单

| 密钥 | 用途 | 存储 |
|---|---|---|
| `HA_TOKEN` | HA API 认证（受限用户）| .env |
| `QDRANT_API_KEY` | 向量库（仅启用 Qdrant 时才需要）| .env |
| `MQTT_USERNAME/PASSWORD` | MQTT（M1 禁用）| .env |
| `ESPHOME_WIFI_*` | ESPHome 固件编译 | .env（仅本机）|
| `AGENT_SESSION_SECRET` | 会话签名 | .env |
| `AUDIT_SIGNING_KEY` | 审计 checkpoint 签名（**与 Agent Runtime 隔离**）| secrets/（不进 Git）|

### 4.3 Fail-Closed（对应 P0-8）

**禁止** `${SECRET:-changeme}`（缺失时静默用默认值，fail-open）。
**必须** `${SECRET:?SECRET is required}`（缺失时拒绝启动，fail-closed）。

```yaml
# ✅ 正确
environment:
  - QDRANT__SERVICE__API_KEY=${QDRANT_API_KEY:?QDRANT_API_KEY is required}

# ❌ 禁止
# environment:
#   - QDRANT__SERVICE__API_KEY=${QDRANT_API_KEY:-changeme-in-env}
```

---

## 5. 审计日志完整性（对应 P0-10）

### 5.1 术语修正

> **v0.1 错误**：称审计日志"不可篡改（tamper-proof）"。
> **正确**：本地 hash-chain + append-only 只能提供 **tamper-evident（可检测篡改）**，不是 tamper-proof。

### 5.2 完整性机制设计

```
canonical event serialization（规范化 JSON）
        ↓
SHA-256 chain（每条含前一条哈希）
        ↓
signed/HMAC checkpoints（定期 checkpoint 签名）
        ↓
signing key isolated from Agent Runtime（签名密钥与运行时隔离）
        ↓
periodic off-host checkpoint/copy（周期性离机副本/快照）
```

| 组件 | 说明 |
|---|---|
| 事件规范化 | 字段顺序固定、UTF-8、无时间戳精度抖动（否则哈希链断裂）|
| SHA-256 链 | `hash_i = SHA256(hash_{i-1} ‖ canonical(event_i))` |
| Checkpoint 签名 | 每 N 条或每 T 秒生成 checkpoint，用 HMAC/Ed25519 签名 |
| 签名密钥隔离 | `AUDIT_SIGNING_KEY` 由独立进程持有，**Agent Runtime 只有追加权限，无签名密钥** |
| 离机副本 | 定期（如每小时）将 checkpoint 复制到第二存储位置 |

### 5.3 禁用项

> **禁止使用 Python built-in `hash()` 作为持久完整性机制**（进程内随机盐，跨进程不稳定，且非密码学哈希）。

**Acceptance Test 必须使用真实 cryptographic validation**（SHA-256 / HMAC，见 ACCEPTANCE_TESTS.md）。

---

## 6. 网络安全

（保留 v0.1 的端口暴露表与 WireGuard 设计，此处不再重复，详见 THREAT_MODEL.md §5）

关键：内部服务绑定 127.0.0.1；对外仅 Caddy + TLS；IoT 设备建议独立 VLAN。

---

## 7. Kill Switch 与应急响应

（保留 v0.1 设计；补充：kill switch 激活事件本身写入审计）

---

## 8. 合规与最佳实践

（保留；补充：安全事件案例库从审计日志提炼）

---

*本文档随威胁演进持续更新。重大变更需 Architect + Security + QA/Red-Team 评审，最终由 Owner 批准。*
