# ADR-0001: Capability Gateway + Adapter Layer 架构抽象

## Status
**Proposed / Pending Owner Approval**（原 v0.1 为 Accepted，已撤回，见 P0-6 / P0-9）

## Context

Agent 需要控制多种物理设备（空调、传感器、未来可能的电脑、手机、摄像头等）。原 ADR-0001 将 Home Assistant 定位为"唯一设备抽象层"，即所有物理能力都强制经 HA 传输。

外部审查指出该定位的错误：
1. 电脑（MeshCentral）、手机（scrcpy/ADB）、摄像头（RTSP/Frigate）等能力**本质上不属于智能家居域**，硬塞进 HA 是架构强耦合。
2. HA 的权限模型（长期令牌=用户全权限，无 entity scope）不足以承载"跨域统一能力网关"的安全要求。
3. "唯一抽象层"会造成单点故障与能力域错配。

## Decision

**采用三层抽象：Capability Gateway + Adapter Layer。Home Assistant 降级为 "primary smart-home and IoT state/control adapter"，而非 "mandatory transport for every physical capability"。**

```
Agent Runtime
     │
     ▼
Capability Gateway（统一能力网关：统一 Capability Schema + Policy + Audit）
     │
     ▼
Adapter Layer（每类设备一个 adapter）
  ├── HomeAssistantAdapter   → home.*   （智能家居/空调/灯光）
  ├── ComputerAdapter        → computer.*（Phase 3，MeshCentral/RustDesk）
  ├── MobileAdapter          → mobile.*  （Phase 3，scrcpy/ADB）
  ├── CameraAdapter          → camera.*  （Phase 2，Frigate/RTSP）
  └── (future adapters)
```

### Capability Schema 命名空间（示例）

```
home.climate.*      → HomeAssistantAdapter
home.light.*        → HomeAssistantAdapter
computer.*          → ComputerAdapter
mobile.*            → MobileAdapter
camera.*            → CameraAdapter
```

### 关键规则

1. **Agent 只面对统一 Capability Schema**（`<domain>.<entity_type>.<action>`），永远不直连任何设备协议。
2. **每个 adapter 可使用其最合适的底层系统**：HA adapter 用 HA API/WebSocket；Camera adapter 用 Frigate；Computer adapter 用 MeshCentral。
3. **Policy / Audit 在 Capability Gateway 统一执行**，与具体 adapter 解耦（对应 ADR-0005）。
4. HA 是**智能家居与 IoT 状态/控制的首选 adapter**（M1 全部走 HA），但不是唯一传输通道。

### 架构边界（修订）

```
Agent Runtime
     │  Capability Schema（domain.xxx.action）
     ▼
Capability Gateway（schema 校验 + 风险分级 + 速率限制 + 审计）
     │
     ├─→ HomeAssistantAdapter → HA API/WebSocket → ESPHome → IR → AC（M1）
     ├─→ (M2) CameraAdapter → Frigate → RTSP → IP Camera
     ├─→ (M3) ComputerAdapter → MeshCentral
     └─→ (M3) MobileAdapter → scrcpy/ADB
```

## Consequences

### 正面影响
- 能力域正确分离：智能家居走 HA，电脑/手机/摄像头走各自最优系统
- Agent 解耦于具体协议，新增设备=新增 adapter，不改 Agent 核心
- 安全策略在 Gateway 统一执行，不依赖 HA 的权限模型
- 消除 HA 单点故障对非家居域能力的影响

### 负面影响 / 风险
- ⚠️ 比"单一 HA"多一层 Gateway + 多 adapter 接口，实现复杂度上升
  - 缓解：M1 只实现 HomeAssistantAdapter，其余 adapter 为 planned 占位
- ⚠️ 需维护跨 adapter 的统一 Capability Schema 规范
  - 缓解：先定义 Schema 约定文档，M1 只落地 home.* 子集

### 替代方案（未选中）
- **HA 作为唯一抽象层（原 v0.1）**：能力域错配 + HA 权限模型不足 + 单点故障 ❌
- **完全不用 HA，每设备直连**：安全模型爆炸，违反非侵入原则 ❌

## Related ADRs
- ADR-0005: Policy Gate（在 Capability Gateway 层执行）
- ADR-0002: IR 网关硬件（经 HomeAssistantAdapter 接入）

## References
- Home Assistant API: https://developers.home-assistant.io/docs/api/rest/
- HA 权限模型（无 entity scope）: 见 Evidence Matrix

## Date
2026-08-16（v0.2 修订）

## Reviewers
- Reviewed-by-simulated-role: Principal Architect、Agent Runtime Engineer、IoT Engineer
- **Note**: 模拟角色审查不等于项目正式批准。最终由 **Owner** 通过 Architecture Gate。
