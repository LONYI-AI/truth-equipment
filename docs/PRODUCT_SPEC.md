# PRODUCT_SPEC — Physical AI Agent Platform

版本：v0.1（2026-08-16，Architecture Audit 后重写）
上游输入：《Agent 物理世界感知与操控系统 – 项目任务书》（本文件取代其实施细节，保留其产品意图）

## 1. 产品目标

构建一个能实时感知环境、经显式推理与规划、操控物理设备、并**以物理证据验证执行结果**的自托管 AI Agent 平台。Agent 是"能动手的数字资产"，不是聊天工具，也不是"LLM + HA API 胶水"。

## 2. 核心闭环（产品级定义）

```
Perception ──→ State ──→ Reasoning ──→ Planning
    ▲                                     │
    │                                     ▼
   Audit ←── Memory ←── Verification ←── Tool Execution
   （全链路）            （物理证据）
```

每一环的产品含义：

| 环节 | 定义 | 不存在时的失败模式 |
|---|---|---|
| Perception | 从 HA 状态流、传感器、（M2 起）视觉获取环境事实 | Agent 活在想象里 |
| State | 显式世界状态模型（设备状态 + 置信度 + 时间戳） | 用过期/臆测状态决策 |
| Reasoning | LLM 推理（Qwen3 本地），可解释（think 模式落审计） | 黑盒决策 |
| Planning | LangGraph 状态机生成可审计的计划（步骤 + 预期验证） | 一步到位玄学调用 |
| Tool Execution | 经 Policy Gate 的分级执行 | 幻觉直接变成物理动作 |
| Verification | 独立物理证据确认结果（多信号） | "我以为我开了空调" |
| Memory | episodic（事件）+ semantic（偏好/知识）+ 设备历史 | 每次从零开始 |
| Audit | append-only 全链路日志，correlation ID 贯穿 | 出事无法复盘 |

## 3. 需求

### 3.1 功能需求（Must / Should / Could）

**Must（M1 范围）**
- F1 自然语言控制空调（开关/模式/温度/风速），端到端闭环
- F2 所有写动作过 Policy Gate（风险分级 + 参数边界 + 速率限制）
- F3 物理验证：V0–V4 证据链（IR 回读=V2、声学=V3、温度趋势=V4），结论按证据层级记录
- F4 失败处理：重试 ≤2 → 补偿（回滚到安全态）→ 升级人工
- F5 全链路审计日志（JSONL append-only）
- F6 记忆：设备历史 + 用户偏好（M1 用 SQLite；Qdrant 为 planned adapter）
- F7 一键 kill switch：禁用所有写动作，Agent 降级为只读

**Should（M2-M3）**
- F8 视觉感知（Frigate + VLM）
- F9 电脑/手机操控（MeshCentral / scrcpy，需独立安全评审）
- F10 多设备场景编排（"回家模式"）

**Could（M4+）**
- F11 语音接口；F12 多 Agent 协作；F13 自动化学习（从审计日志提炼习惯）

### 3.2 非功能需求

- **可靠性**：单设备写动作物理成功率、验证器假阳性率——**均待实测标定**（目标：成功率 ≥95%、假阳性 ≤5%，附样本量 + 置信区间，实测前不作事实承诺）
- **延迟**：动作派发（LLM 输出 tool call → HA 收到）与端到端延迟——**均待实测标定**，不预设 <3s 硬承诺（GPU/CPU 分别标定）
- **安全**：见 SECURITY_MODEL.md / THREAT_MODEL.md
- **可维护**：全仓 docs-as-code；版本 pin；CI 强制
- **非侵入**：控制链路任一环节拔除后，家电保持原生可用

## 4. 范围边界

- 不做：拆机接线、刷目标家电固件、依赖任何厂商云 API
- Insta360 相机 WiFi 协议为 P2 探索项，不进关键路径
- 视觉系统（Frigate/VLM）在 M1E 验收通过前**冻结**

## 5. 用户与风险分级（产品视角）

- 唯一人类管理员 = 项目所有者。Tier 2 动作需其显式确认（M1 通过 CLI 确认，后续可接推送审批）。
- 动作风险分级定义见 SECURITY_MODEL.md §3。
