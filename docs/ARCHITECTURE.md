# ARCHITECTURE — Physical AI Agent Platform

版本：v0.1（2026-08-16，Architecture Audit 后初版）
状态：**待批准** —— 与 Architecture Audit 联合审批

---

## 1. 架构总览

### 1.1 设计目标

构建 production-grade、self-hosted、non-invasive 的物理世界感知与操控 Agent 平台。形成完整闭环：

```
Perception → State → Reasoning → Planning → Tool Execution
    ▲                                     │
    │                                     ▼
   Audit ←── Memory ←── Verification ←───┘
   （全链路）            （物理证据）
```

### 1.2 核心设计原则

| 原则 | 说明 | 优先级 |
|---|---|---|
| **Non-invasive** | 不拆机、不改线、不刷目标设备原厂固件，控制端可随时物理移除 | P0 |
| **Self-hosted** | 全部基础设施本地部署，零厂商云锁定 | P0 |
| **Verified actuation** | IR 等单向控制必须配独立物理验证通道（传感器/功率/接收回读） | P0 |
| **Policy-gated** | 所有物理动作按风险分级（Tier 0-3），高风险需人工确认 + 审计 + 可回滚 | P0 |
| **Auditable** | 每次推理、工具调用、物理验证结果都落 append-only 审计日志 | P0 |
| **Docs-as-code** | 架构决策必须落 ADR，不允许关键知识只存在于对话中 | P0 |
| **Defense in depth** | 多层安全防护，不依赖单一安全机制 | P1 |

### 1.3 架构分层

```
┌──────────────────────────────────────────────────────────────┐
│ Layer 0: Interface（接口层）                                   │
│ CLI / Chat / (Phase 2+ Voice / API)                           │
└──────────────────────────┬───────────────────────────────────┘
                           ▼
┌──────────────────────────────────────────────────────────────┐
│ Layer 1: Agent Runtime（智能体运行时）                          │
│ ┌─────────────────────────────────────────────────────────┐  │
│ │ LangGraph State Machine:                                 │  │
│ │ Perceive → Recall(Memory) → Plan → [Policy Gate]         │  │
│ │       ↑                                  │              │  │
│ │       └──────── Verify(物理验证 V0-V4) ←──┘              │  │
│ │                 ↓ 失败: retry(≤2) → compensate → escalate│  │
│ └─────────────────────────────────────────────────────────┘  │
│ LLM: ModelProvider 抽象（Ollama + 候选 qwen3:8b）             │
└───────┬──────────────────────┬───────────────────┬───────────┘
        │ capability calls     │ memory            │ every step
        ▼                      ▼                   ▼
┌────────────────┐   ┌─────────────────┐   ┌──────────────────┐
│ Capability     │   │ Memory          │   │ Audit            │
│ Gateway        │   │ SQLite (M1)     │   │ append-only JSONL│
│ - schema 校验  │   │ (Qdrant planned)│   │ SHA-256 chain    │
│ - 上下文风险   │   │                 │   │ signed checkpoint│
│ - 速率限制     │   │                 │   │ tamper-evident   │
│ - kill switch  │   │                 │   │                  │
└───────┬────────┘   └─────────────────┘   └──────────────────┘
        ▼
┌──────────────────────────────────────────────────────────────┐
│ Adapter Layer（设备适配层，每类设备一个 adapter）              │
│  ├── HomeAssistantAdapter  → home.*（M1：空调/灯光）          │
│  ├── CameraAdapter         → camera.*（Phase 2）             │
│  ├── ComputerAdapter       → computer.*（Phase 3）           │
│  └── MobileAdapter         → mobile.*（Phase 3）             │
│  Home Assistant = primary smart-home/IoT adapter（非唯一通道）│
└───────┬──────────────────────────────────────────────────────┘
        ▼
┌──────────────────────────────────────────────────────────────┐
│ Physical Layer（物理设备）                                     │
│ ESPHome IR Gateway (ESP32-C3-DevKitM-1):                     │
│   - remote_transmitter (IR 发射)                              │
│   - remote_receiver  (IR 回读 → V2 验证)                      │
│   - SHT31 温湿度 (I2C → V4 验证)                              │
└──────────────────────────────────────────────────────────────┘
```

---

## 2. 核心组件详解

### 2.1 Agent Runtime（`agent/`）

**职责**：推理、规划、工具调用协调、验证决策、记忆管理

**技术栈**：
- LangGraph StateGraph（显式状态机）
- ModelProvider 抽象（Ollama 实现，候选模型 qwen3:8b）
- 低温度 ≤ 0.2（**降低**输出方差，而非"保证确定性"）

**状态定义**：

```python
class AgentState(TypedDict):
    # 对话消息
    messages: Annotated[list[BaseMessage], add_messages]

    # 当前感知的世界状态
    world_state: WorldState  # 设备状态 + 置信度 + 时间戳

    # 当前计划
    current_plan: Plan | None  # 步骤列表 + 预期验证条件

    # 执行历史
    execution_history: list[ExecutionRecord]

    # 验证结果
    verification_result: VerificationResult | None

    # 元数据
    session_id: str
    correlation_id: str  # 全链路追踪 ID
    retry_count: int
    needs_human_review: bool
```

**节点定义**：

| 节点 | 功能 | 输入 | 输出 |
|---|---|---|---|
| `perceive` | 从 HA/Memory 获取当前环境状态 | 用户指令 | 更新后的 world_state |
| `recall` | 从 Memory 检索相关历史和偏好 | world_state + intent | 上下文增强的 messages |
| `reason` | LLM 推理：理解意图、生成计划 | messages | `ReasoningRoute`：`plan` / `direct` / `noop` |
| `plan` | 将 LLM 输出结构化为可执行计划 | reason 输出 | 结构化 Plan |
| `policy_gate` | 风险分级、参数校验、权限检查（复用 M0 PolicyEngine）| canonical CapabilityRequest | `PolicyRoute`：APPROVED / REJECTED / NEEDS_APPROVAL |
| `human_review` | 审批挂起（interrupt）/ 恢复（resume）+ 重新校验 + 单次消费 | policy_decision + canonical request | `PolicyRoute`：APPROVED / REJECTED |
| `execute` | 经 `CapabilityGateway.execute_authorized_simulation`（SIMULATION-only）派发到 MockAdapter | current_request + policy_decision | execution_outcome |
| `verify` | 把 execution_outcome 转 `VerificationEvidence`（provenance=simulated）；`verification_satisfied` = 达到 required_level | execution_outcome | verification + verification_satisfied |
| `compensate` | 失败处理：重试/回滚/升级 | failed verification | recovery_action |
| `memory_update` | 更新 episodic + semantic 记忆 | full cycle result | memory_ids |

**边（控制流）**：

```
START → perceive → recall → reason → {route: ReasoningRoute}
                                  ├─ PLAN   → plan → policy_gate
                                  ├─ DIRECT → policy_gate (direct，保留 W1 direct path)
                                  └─ NOOP   → END（non-actionable 安全终态）
                                        │
                          policy_gate → {policy_route: PolicyRoute}
                                  ├─ APPROVED       → execute → verify
                                  ├─ REJECTED       → escalate → END
                                  └─ NEEDS_APPROVAL → human_review（interrupt 挂起）
                                                        │  resume → re-policy + consume once
                                                        ├─ APPROVED  → execute → verify
                                                        └─ REJECTED  → escalate → END
                                        │
                                        │   verify → {verification_satisfied?}
                                        │              ├─ yes → memory_update → END
                                        │              └─ no  → compensate → END（fail-closed，不 retry）
```

> **Reason → Graph 边界契约（M1A-W2 REV3）**：路由用 typed contract
> `ReasoningRoute`（`PLAN` / `DIRECT` / `NOOP`）三态，不再用单一 `bool` 混同
> 「是否 actionable」与「是否需要 plan」。`NOOP`（non-actionable / no-op）在
> Reason 边界即安全终态（END），绝不进入 policy_gate / execute / verify。
> **stale-plan lifecycle invariant**：Reason 每轮无条件 invalidate 任何 prior
> `current_plan`（`PLAN`/`DIRECT`/`NOOP` 均输出 `current_plan=None`）；只有 `plan`
> 节点是 `current-plan` 的唯一生产者。DIRECT 到 policy boundary 的 canonical
> current-action 来源是 `reasoning`（本轮 `ReasoningDecision`），policy 不得把遗留
> `current_plan` 当成 DIRECT 本轮请求。详见 ADR-0010。
>
> **Policy → Graph 边界契约（M1A-W3）**：路由用 typed contract `PolicyRoute`
> （`APPROVED` / `REJECTED` / `NEEDS_APPROVAL`），由本轮真实 M0 `PolicyDecision`
> 确定性派生（非字符串 `policy_verdict`、非 LLM）。Policy Gate 只处理**一个明确的本轮
> canonical CapabilityRequest**：PLAN 路径 = `current_plan.steps[0]`；DIRECT 路径 =
> 本轮 `ReasoningDecision` 转 M0 `CapabilityRequest`（参数原样透传，不 clamp）。
> **stale-policy invariant（REV2）**：每次 policy_gate 无条件 invalidate 上一轮 policy/approval
> 授权状态的**全部五个字段**（`policy_decision` / `current_request` / `approval_id` /
> `canonical_request_hash` / `needs_human_review`）；canonical extraction failure 与
> `PolicyEngine.evaluate` exception 均 fail-closed 并显式清空这五字段，旧 approved 不残留。
> 审批经 LangGraph `interrupt`/`Command(resume)` + checkpointer 挂起/恢复；
> resume 后对同一 canonical request 重新执行当前 Policy，仅当仍允许 + `ApprovalEngine.consume`
> 单次消费成功才授权到达 Execute boundary。
> 详见 ADR-0005、ADR-0011。
>
> **Execute / Verify 边界契约（M1A-W4）**：Execute 节点经 M0
> `CapabilityGateway.execute_authorized_simulation` 派发到 MockAdapter——该入口**硬性
> SIMULATION-only**（`mode != SIMULATION` → fail-closed REJECT，adapter.execute 绝不调用），
> 不重新 `PolicyEngine.evaluate`（避免 RateLimiter 双计）；PolicyDecision 不是未来 PHYSICAL
> 的可信 authorization token（待完整 MVP 后统一 hardening）。Verify 节点复用 M0
> `VerificationEngine` 语义，**成功 = 达到 `capability.required_verification_level`**（`status
> == "completed"`），路由用独立 typed 信号 `verification_satisfied`，**不伪造
> `physical_effect == "confirmed"`**（V2 达 required 即 satisfied，但 physical_effect 仍为
> "pending"，V2 不冒充 V4）。所有模拟 `VerificationEvidence` 带 `evidence["provenance"] =
> "simulated"`。**失败路由（REV2）**：M1A-W4 MVP 暂不实现自动 retry——`verification_satisfied`
> False / 缺失一律 fail-closed 到 `compensate` boundary → END（不回路 execute，避免「execute
> → verify failed → execute duplicate rejected → …」的 recursion loop 直至 LangGraph recursion
> limit）。`compensate` 为 injected boundary（不实现真实补偿动作）。正式 retry lifecycle 留待
> MVP 整体 hardening。

### 2.2 Capability Gateway（`src/physical_agent/policy/`）

**职责**：所有 capability 调用的统一入口，实现确定性策略执行（对应 ADR-0001 / ADR-0005）

**功能**：
1. **Schema 校验**：参数类型、范围、必填项
2. **上下文风险分级**：`risk = f(principal, device, capability, action, parameters, context)`（非静态 Tier）
3. **速率限制**：滑动窗口（同设备同操作 ≤ 3次/分钟）
4. **人工确认**：上下文分级为 Tier 2 的动作阻塞等待审批
5. **审计埋点**：每次调用写入 audit log

**风险分级（上下文感知，示例非穷举）**：

| 分级 | 触发（示例） | 机制 |
|---|---|---|
| **Tier 0** | 只读操作 | 自动执行 |
| **Tier 1** | 正常上下文的有界写（AC on, cool, 24-28℃, 已批准房间, 正常时段）| 自动执行（带审计）|
| **Tier 2** | 异常温度 / 连续快速启停 / 无人长时间 / override / 未知设备 | 需人工确认 |
| **Tier 3** | 删除设备、修改安全配置 | 仅手动 |

> 分级是**动态上下文函数**，不是设备/动作的静态标签（见 ADR-0005）。

### 2.3 Physical Verification（`src/physical_agent/verification/`）

**职责**：独立验证物理动作是否真正生效。采用 **V0–V4 五级证据链模型**（见 ADR-0006）。

| 层级 | 定义 | 证据手段 | 硬件 |
|---|---|---|---|
| V0 | request accepted | Policy Gate 通过 | 软件层 |
| V1 | command dispatched | 命令已发往 HA/ESPHome | 软件层 |
| V2 | actuator output verified | TSOP38238 捕获本机 IR 发射码比对 | TSOP38238（M1C）|
| V3 | device acknowledged | 声学蜂鸣 / 视觉面板（Phase 2）| MAX9814（可选）|
| V4 | physical effect verified | SHT31 温度趋势 / 智能插座功率突变 | SHT31 / 智能插座（可选）|

> **关键**：TSOP38238 回读只能证明 V2（执行器输出了信号），**不能单独证明空调收到/执行了命令（V3/V4）**。

**验证结论状态机**：

```
command_sent → actuation_verified → device_acknowledged → physical_effect_verified
（任一层断裂 → inconclusive / failed）
```

**可靠性数字纪律**：任何可靠性/准确率数字在实测前不得写成事实；实验必须带 sample size、conditions、FPR、FNR、confidence interval（详见 ACCEPTANCE_TESTS.md §M1D）。

**融合算法**：融合权重与阈值**待 M1D 实测标定**，不预设具体数值。接口参考（M1D 实现，非最终实现）：

```python
# src/physical_agent/verification/result.py（接口示意）
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

Verdict = Literal["command_sent", "actuation_verified",
                  "device_acknowledged", "physical_effect_verified",
                  "inconclusive", "failed"]

@dataclass
class VerificationResult:
    level: Verdict
    evidence: dict  # 各层级证据，含 sample_size/conditions/FPR/FNR/CI
    timestamp: datetime
    # 注：confidence 的计算方法待 M1D 标定后定义，不预设数值
```

### 2.4 Memory Subsystem（`src/physical_agent/memory/`）

**职责**：持久化记忆，支持跨会话学习

**存储架构**：

| 类型 | 内容 | 存储 | 检索方式 | 保留策略 |
|---|---|---|---|---|
| **Episodic** | 事件流水（每次交互完整记录） | **SQLite** | 时间范围查询 | 90 天滚动 |
| **Semantic** | 用户偏好、设备习惯 | **SQLite（结构化，M1）** | key 查询 | 永久 |
| **Working** | 当前会话上下文 | In-memory (State) | 会话内 | 会话结束清空 |

> Qdrant 为 **planned adapter**，仅在出现明确 semantic retrieval 需求时启用（见 ADR-0004）。M1 不部署向量数据库。

**Memory 更新时机**：
- 每次闭环完成后异步更新
- 用户显式反馈（"记住我喜欢 26 度"）
- 异常事件（连续失败、异常状态）

### 2.5 Audit Subsystem（`src/physical_agent/audit/`）

**职责**：全链路审计日志，**tamper-evident（可检测篡改）**——注意：不是"不可篡改（tamper-proof）"（见 ADR 备注 P0-10）。

**日志格式**（JSONL append-only）：

```json
{
  "timestamp": "2026-08-16T01:30:00Z",
  "correlation_id": "req_abc123",
  "session_id": "sess_xyz789",
  "phase": "policy_gate",
  "event_type": "tool_call_approved",
  "data": {
    "tool": "turn_on_ac",
    "params": {"temperature": 26, "mode": "cool"},
    "tier": 2,
    "approved_by": "human_admin",
    "latency_ms": 45
  },
  "hash": "sha256:abcd1234..."  // 链式哈希防篡改
}
```

**特性**（tamper-evident 完整性机制）：
- Append-only（仅追加）
- Correlation ID 贯穿全链路
- SHA-256 链式哈希（`hash_i = SHA256(hash_{i-1} ‖ canonical(event_i))`）
- 定期 HMAC/Ed25519 signed checkpoint，签名密钥与 Agent Runtime 隔离
- 周期性离机副本（每小时）

> **禁止** Python built-in `hash()`（非密码学、跨进程不稳定）。Acceptance Test 必须用真实 SHA-256/HMAC 校验（见 ACCEPTANCE_TESTS.md）。

---

## 3. 数据流

### 3.1 典型请求流程（以"打开空调到 26 度"为例）

```
用户输入
  ↓
[Interface] 接收自然语言指令
  ↓
[Agent Runtime]
  ├── [perceive] 查询 HA：当前空调状态 = off，室温 = 28℃
  ├── [recall] 查 SQLite：用户偏好 = 通常 26℃，上次使用 = 昨晚
  ├── [reason] LLM 推断意图：开启空调制冷 26℃
  ├── [plan] 生成步骤：
  │     Step 1: turn_on_ac(temp=26, mode=cool)
  │     Step 2: verify_ac_response(expected_state=on, temp_trend=down)
  │     Step 3: report_to_user
  ├── [policy_gate]
  │     ├── 工具 = turn_on_ac；上下文 = 正常房间/正常时段/26℃ ∈ 舒适区间
  │     ├── 参数校验：26 ∈ [16,30] ✓，mode=cool ✓
  │     ├── 速率检查：近 1 分钟无同类操作 ✓
  │     └── → 上下文风险分级 = Tier 1（有界自动放行，不阻塞）
  ├── [execute] 调用 HA climate.turn_on → 返回 success（含 correlation_id）
  ├── [verify]
  │     ├── V2 IR 回读：捕获到匹配的 IR 码 ✓
  │     ├── V4 温度趋势：启动监控（30s 后首次采样）
  │     └── → level = "actuation_verified"（V2 确认；V3/V4 依硬件到位情况）
  ├── [memory_update]
  │     ├── Episodic：记录本次操作完整流水
  │     └── Preferences：更新用户偏好（SQLite）
  └── [返回用户] "已为您开启空调制冷 26℃，已确认发射信号。"
  ↓
[Audit] 全程事件已落盘（correlation_id 贯穿）
```

### 3.2 失败处理流程

```
[verify] verdict = "failed" 或 "inconclusive"
  ↓
{retry_count < 2?
  ├─ 是 → retry_count += 1 → [execute] 重试
  │         ↓
  │      [verify] 再次验证
  │         ↓
  │      {still failed?}
  │         ├─ 是 → [compensate]
  │         │      ├── 尝试回滚到安全态（如关闭空调）
  │         │      ├── 记录失败详情
  │         │      └── 升级通知管理员
  │         └─ 否 → 继续
  └─ 否 → 直接 [compensate]
```

---

## 4. 技术选型与版本锁定

| 组件 | 版本（pin） | 选择理由 | ADR |
|---|---|---|---|
| Python | 3.12+（推荐 3.13） | async native、type hint 成熟 | - |
| Home Assistant | 2026.8.2（见 compose） | primary smart-home/IoT adapter | ADR-0001 |
| ESPHome | ≥2026.4.0（patch 待定） | IoT 固件框架，ESP-IDF 默认 | ADR-0002 |
| Ollama | v0.32.x（patch 待定） | 本地 LLM 推理 | ADR-0003 |
| Qwen（候选） | qwen3:8b（非不变量，benchmark 决定） | 中文优化、原生 tool calling | ADR-0003 |
| LangGraph | 1.x（LTS） | 生产级 Agent 状态机 | ADR-0003 |
| Qdrant | v1.18.1（**M1 不启用**） | planned adapter，语义检索需求出现时才用 | ADR-0004 |
| Docker Engine | 25+ / Compose v2 | 容器编排 | - |
| WireGuard | Linux 内核模块 | VPN 远程访问 | ADR-0008 |
| Caddy | 2.x | 反向代理 + auto TLS | - |

> 完整版本矩阵、验证日期、升级策略见 [COMPATIBILITY_MATRIX.md](COMPATIBILITY_MATRIX.md)。

---

## 5. 部署拓扑

### 5.1 开发环境（M0-M1A）

```
开发者机器 (Windows/Linux/macOS)
├── Docker Desktop / Docker Engine
│   ├── homeassistant (container)
│   ├── ollama (container)
│   ├── qdrant (container)
│   └── mosquitto (container, M1B+ 启用)
├── Agent Runtime (本地 Python venv)
│   ├── Fake HA (recorded fixtures)
│   ├── Mock LLM (可重复测试)
│   └── 模拟验证器
└── Git + CI (GitHub Actions / local)
```

### 5.2 生产环境（M1B+）

```
常开 Linux 服务器 (Ubuntu 24.04+)
├── Docker Compose Stack
│   ├── homeassistant (host network)
│   ├── ollama (GPU passthrough)
│   ├── qdrant (127.0.0.1 bind)
│   ├── mosquitto (内部网络)
│   ├── prometheus
│   ├── grafana
│   └── loki (M1E+)
├── WireGuard (VPN 入口)
├── Caddy (反向代理 + TLS)
└── Agent Runtime (systemd service or container)
        │
        ├── WiFi Network
        │   └── ESP32-C3 IR Gateway
        │       ├── IR Transmitter → 空调
        │       ├── IR Receiver ← 遥控器/空调应答
        │       └── SHT31 Sensor
        └── (M2+) IP Cameras → Frigate
```

---

## 6. 安全边界

详见 SECURITY_MODEL.md 和 THREAT_MODEL.md。

核心原则：
- 所有外部暴露服务必须经 Caddy + TLS
- 内部服务绑定 127.0.0.1 或 Docker internal network
- MQTT 默认禁用，启用即鉴权 + ACL
- HA Token 最小权限（专用 token，非管理员）
- Agent 不直连设备协议，全部经 HA 抽象

---

## 7. 可扩展性设计

### 7.1 新增设备类型

1. 在 `src/physical_agent/adapters/` 新增适配器
2. 在 HA 配置集成或 ESPHome 固件
3. 在 `src/physical_agent/capability/` 注册新工具（含 risk tier 元数据）
4. 更新 verification 策略（如需要）

### 7.2 新增感知通道（如视觉）

1. 部署 Frigate（NVR + 检测）
2. 接入 VLM（qwen3-vl 或专用模型）
3. 在 `agent/perception/` 新增视觉处理节点
4. 更新 State schema 加入视觉字段
5. **必须在 M1E 全部通过后才允许启动**

### 7.3 多 Agent 协作（M4+）

- 使用 LangGraph 的 multi-agent 模式
- 共享 Memory + Audit 层
- 每个 Agent 有独立 Policy Gate

---

## 8. 监控与可观测性

详见 observability/ 目录（M1E 实现）。

核心指标：
- 端到端延迟（分阶段统计：LLM、HA、验证）
- 工具调用成功率
- 验证准确率（真阳性/假阳性）
- 审计日志完整性
- 系统资源使用率

---

## 9. 文档索引

| 文档 | 内容 |
|---|---|
| PRODUCT_SPEC.md | 产品规格与需求 |
| SECURITY_MODEL.md | 安全模型与权限设计 |
| THREAT_MODEL.md | 威胁建模与缓解措施 |
| hardware/BOM.md | 硬件清单与采购指南 |
| ROADMAP.md | 里程碑路线图 |
| ACCEPTANCE_TESTS.md | 验收标准与测试用例 |
| RUNBOOK.md | 运维手册与故障排查 |
| DECISIONS/ | ADR 架构决策记录 |
| audits/ | 阶段性审计报告 |

---

*本文档随项目演进持续更新。重大变更须经 Architect + 实现负责人 + QA/Security 三方审查并更新对应 ADR。*
