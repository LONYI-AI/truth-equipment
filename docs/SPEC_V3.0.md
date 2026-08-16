# Agent 物理世界感知与操控系统 — 项目开发规格书 v3.0（Physical Agent OS）

> **本文件是 Owner 于 2026-08-16 发布的权威基线（原文保留），取代此前《项目任务书》PDF 及 Architecture Audit v0.1/v0.2 的实施细节。**
> 状态：Architecture Baseline / 待 Owner Gate Approval。
> 阶段：Pre-M0。

---

## 0. Executive Summary

最终产品是一套 **Personal Physical Agent Operating System**：持续感知真实环境、理解人的目标、自主规划、通过受控能力影响真实设备、验证物理结果、积累经验、并安全扩展新设备能力。

完整闭环：

```
Intent → Perception → State → Reasoning → Planning → Policy
→ Execution → Physical Verification → Memory → Audit / Learning
```

五个相互隔离的逻辑平面：

```
① Interaction Plane
② Agent / Reasoning Plane
③ Physical Safety & Capability Plane
④ Device / Physical Plane
⑤ Evolution / Build Plane
```

核心原则：**LLM 可以提出动作，但永远不直接拥有物理设备权限。**

---

## 1. 核心产品目标

统一管理：智能家居、空调、摄像头、相机、Windows/Linux/macOS 电脑、Android 手机、网络设备、传感器、自动化场景、后续机器人或其他物理执行器。

Agent 不接触协议细节，只调用统一 Capability（如 `home.climate.set_temperature`、`camera.get_home_state`），而非 `POST /api/services/climate/...`、`adb shell`、`mqtt publish`。

---

## 2. 不变的最高设计原则

**2.1 非侵入式**：禁止拆改控制板/改高压线/刷原厂固件/破坏原遥控能力。Agent 控制器移除后，原始设备必须仍正常工作。

**2.2 Local-first / Self-hosted**：核心状态/控制/策略/日志 100% 本地运行。云模型是 Optional Intelligence Provider，不是物理控制的必需依赖。断网时基本控制/安全策略/自动化仍工作。

**2.3 LLM 不是安全边界**：`LLM → Plan → Deterministic Policy Engine → Capability Gateway → Physical Device`，永远不能 `LLM → Device`。

---

## 3. v3.0 总体架构

关键变化：**Home Assistant 不再是所有设备的唯一总线**，定位为 **Primary Smart-Home / IoT Adapter**。

```
USER/AUTOMATION (Chat·CLI·Voice·Mobile·Scheduler·Events)
  → AGENT RUNTIME LAYER
      Runtime Interface
      ├─ DeepSeekHarnessRuntime  [Experimental/Primary]
      ├─ LangGraphRuntime        [Stable/Fallback]
      └─ MockRuntime             [CI/Test]
      Planner·Session·Context·Model·Memory
  → PHYSICAL SAFETY KERNEL
      Capability Gateway → Schema Validator → Policy Engine
      → Approval/Risk Gate → Execution Coordinator
      → Verification Engine → Audit/Event Store
  → ADAPTER LAYER
      HomeAssistantAdapter / ComputerAdapter / MobileAdapter
      / CameraAdapter / NetworkAdapter / FutureAdapter
  → HA / Mesh·SSH / ADB / RTSP → ESPHome·Zigbee·Matter → PHYSICAL WORLD
```

---

## 4. DeepSeek Harness 的正式定位

指 DeepSeek 官方 `deepseek-ai/deepseek-harness`（非第三方同名项目）。Cordis 架构，核心理念 "Everything is a Plugin"。官方标记为 Developer Preview（仍有 breaking changes）。

定位：**Agent Runtime / Evolution Runtime**，而非 Physical Security Boundary。

---

## 5. 为什么 DeepSeek Harness 适合

项目的长期目标（发现能力→组合→生成→测试→加载→失败回滚）与 Harness 的 Cordis 插件组合/替换能力契合。适合 agent runtime composition、model provider、development agent、tool presentation、session、coding agent、adapter development、自进化 Build Plane。但**不能成为设备安全层**。

---

## 6. DeepSeek Harness 的安全边界

Harness 官方工程记录明确：动态挂载 Cordis 插件/执行代码的开发工具具有接近 Bash 权限，不能当 security boundary。

因此：`DeepSeek Harness → only typed capability request → Physical Safety Kernel → Devices`；禁止 `Harness plugin → HA Token → Device`。

---

## 7. DeepSeek Harness 双 Profile

**7.1 Development Profile（dsh-development）**：可拥有 Git/filesystem/compiler/tests/isolated shell/package manager/docs/code gen；**永远不拥有生产设备凭据**。用于写 Adapter、测试、修 Bug、Device Driver、Architecture/Code Review、文档、Benchmark。

**7.2 Physical Runtime Profile（dsh-physical）**：只暴露 `capability.list/describe/observe/invoke`、`task.status`、`verification.status`、`memory.query`。禁止 `bash/shell/raw filesystem/direct HTTP/raw MQTT/direct HA REST/ADB shell/SSH/plugin install/arbitrary code`。**Physical Runtime 是 Agent，不是 Root Shell。**

---

## 8. DeepSeek Harness + Python 集成

官方提供 `deepseek-harness-sdk` Python SDK，可运行 Harness、要求 isolated workspace、保留 JSONL 日志。采用 `physical-agent Python Core → DeepSeekHarnessRuntime Adapter → DeepSeek Harness SDK`，不把整个项目改写成 TypeScript。

---

## 9. Runtime 抽象

```python
class AgentRuntime(Protocol):
    async def run(self, intent: UserIntent, context: RuntimeContext) -> AgentResult: ...
    async def resume(self, session_id: str, event: RuntimeEvent) -> AgentResult: ...
    async def cancel(self, session_id: str) -> None: ...
```

实现：DeepSeekHarnessRuntime / LangGraphRuntime / MockRuntime。所有 Runtime 必须通过 **Runtime Conformance Suite**。

---

## 10. 为什么仍保留 LangGraph

Harness 处 Developer Preview，作为 innovation runtime；LangGraph 是 stable reference runtime（截至本规格 1.2.11）。项目不允许业务逻辑绑定某个 Agent framework。

---

## 11. Model Plane

`ModelProvider → LocalOllamaProvider / DeepSeekProvider / FutureProvider`。

---

## 12. Local Model

生产默认 Local-first，用 Ollama（当前 0.32.13；0.32.11 已加 `ollama launch dsh`）。不在 Architecture 层写死具体模型，由 benchmark 决定。指标：Tool selection accuracy / Schema adherence / Unsafe action rate / Hallucinated tool rate / Chinese understanding / Latency / Tokens/sec / VRAM/RAM / Recovery after tool failure / Long context stability。

---

## 13. DeepSeek V4 Model Provider

可选 High-Intelligence Provider：`deepseek-v4-pro`（V4-Pro-0813）、`deepseek-v4-flash`（V4-Flash-0731）。用于 Architecture、复杂规划、Adapter 生成、Code review、难调试、高层推理。**DeepSeek API 不得成为基本物理控制可用性的必需依赖。**

---

## 14. DeepSeek Thinking / Tool Calling

V4 支持 Thinking Mode 与 Tool Calls。含工具调用的多轮上下文中 `reasoning_content` 需按 contract 保留回传。这类协议兼容问题由 Model Provider / Harness 解决，不能渗透到 Capability Gateway / Device Adapter / Policy Engine。

---

## 15. Physical Safety Kernel

最重要组件，目录 `services/safety-kernel/`（v3.0 实施映射到 src/）。包含：CapabilityRegistry、SchemaValidator、PolicyEngine、ApprovalEngine、ExecutionCoordinator、VerificationEngine、AuditStore、KillSwitch。**Safety Kernel 不依赖 LLM。**

---

## 16. Capability Model

所有动作定义为 Capability，例：

```yaml
id: home.climate.set_temperature
device_type: climate
parameters:
  temperature: {type: number, minimum: 16, maximum: 30}
risk: {default: 1}
verification: {required_level: V2}
```

---

## 17. 禁止把 HA Entity 自动全部暴露给 LLM

正确路径：`HA Entity → Adapter discovery → Capability Candidate → Policy classification → Allowlist → Capability Registry → Agent`（门锁/车库/报警/加热器/开关/admin service/automation trigger 等不得自动暴露）。

---

## 18. Contextual Policy Engine

`Risk = f(principal, device, capability, parameters, location, time, occupancy, historical_state, environment)`。例：回家途中开卧室空调 26℃ → Risk 1 自动；一分钟开关 20 次 → Risk 2/3 Deny；陌生 Agent 控门锁 → Risk 3 人工确认。

---

## 19. 风险等级

- **Tier 0** 只读（get temperature、camera metadata）
- **Tier 1** 低风险可逆（开灯、24-28℃ 空调）
- **Tier 2** 重要设备状态变化（电脑执行命令、外出运行设备）
- **Tier 3** 安全敏感（门锁、报警器、危险执行器、权限修改）→ 默认 Human Approval

---

## 20. Kill Switch

独立 Kill Switch：`AGENT_EXECUTION_ENABLED=false`。触发后 LLM 可聊天、可观察，不可执行任何 physical action。支持 kill device / kill adapter / kill capability / kill runtime。

---

## 21. Execution State Model

禁止用 `success = API returned 200` 作为执行成功。生命周期：

```
REQUESTED → AUTHORIZED → DISPATCHED → ACTUATION_OBSERVED
→ DEVICE_EVIDENCE → PHYSICAL_EFFECT
```

---

## 22. Verification Level

- **V0** Request Accepted
- **V1** Command Dispatched（Adapter 接受并发出）
- **V2** Actuation Observed（执行器产生输出，如 IR waveform 被检测）
- **V3** Device Evidence（目标设备产生确认证据，如空调蜂鸣）
- **V4** Physical Effect Verified（环境发生预期改变，如出风温度下降）

---

## 23. Phase 1 空调验证

IR Receiver 只能证明 V2，不能证明空调实际执行。推荐证据：V2=IR waveform、V3=AC beep/可见响应、V4=vent/room 温度趋势。结果示例 `{"command":"home.climate.turn_on","dispatch":"success","verification_level":"V3","physical_effect":"pending"}`。

---

## 24. Adapter Architecture

```python
class DeviceAdapter(Protocol):
    async def discover(self) -> list[Device]: ...
    async def observe(self, device_id: str) -> DeviceState: ...
    async def execute(self, request: AuthorizedCapabilityRequest) -> ExecutionEvidence: ...
    async def verify(self, execution: ExecutionEvidence) -> VerificationEvidence: ...
```

---

## 25. Adapter 类型

第一阶段 HomeAssistantAdapter；后续 ComputerAdapter / MobileAdapter / CameraAdapter；未来 RobotAdapter / VehicleAdapter / NetworkAdapter。

---

## 26. Home Assistant 定位

HA 负责 Smart Home / ESPHome / Zigbee / Matter / Sensors / Climate / Lights / Switches。当前 2026.8 release family，M0 必须 pin 精确 patch，禁止 `:stable`。

---

## 27. ESPHome

继续作为 IoT Gateway 首选固件（当前 2026.8.0 generation）。禁止 generic ESP32 + 随便选 GPIO；必须 exact board SKU → manufacturer schematic → datasheet → GPIO Map → Electrical Review 后才采购。

---

## 28. Memory Architecture

M1 不部署 Vector DB。先实现 Working Memory→Agent State、Event Memory→SQLite、User Preferences→structured SQLite、Device History→SQLite。例：`preferred_bedroom_temp=25`、`arrival_pre_cool_minutes=15`。

---

## 29. Semantic Memory

只有明确需求（"找到和当前异常最相似的历史故障"）才加 SemanticMemoryAdapter（可选 Qdrant）。Vector DB 不是 M1 强制依赖。

---

## 30. Audit Architecture

每条 physical action 记录 correlation_id/principal/intent/plan/capability/policy_decision/parameters/adapter/dispatch_result/verification/timestamp/runtime/model。append-only + tamper-evident，不能称"不可篡改"。

---

## 31. Tamper-evident Audit

Canonical JSON → SHA-256 hash chain → periodic signed checkpoint → off-host copy。Signing Key 不允许由 Agent Runtime 读取。

---

## 32. 自进化架构 v3

禁止 v2 的"LLM 写 Python → import → 真实设备"。v3：Discovery → Capability Analysis → Adapter Specification → LLM candidate → Static Analysis → Dependency Review → Hermetic Sandbox → Contract Tests → Device Simulator → Security Tests → Human/Policy Approval → Signed Artifact → Adapter Registry → Canary → Production。

---

## 33. Build Plane 与 Runtime Plane 分离

Evolution Plane 可写代码/编译/测试/联网/生成 Adapter，但不能有生产 Device Token。Production Plane 只运行已批准 Signed Adapter，不能自动生成代码/安装依赖/修改自身。

---

## 34. DeepSeek Harness 在自进化中的角色

放 Evolution Plane：Research/Architecture/Adapter generation/Testing/Code review/Repair/Regression。但 DSH Plugin ≠ Physical Device Driver。

---

## 35. Production Adapter Registry

Adapter artifact 含 manifest/source hash/version/dependencies/SBOM/tests/supported devices/capabilities/required permissions/signature。

---

## 36. DeepSeek Harness Promotion Gate

从 Experimental 升 Production Default 需满足 H1 Pinned commit、H2 Conformance PASS、H3 无设备凭据、H4 全经 Safety Kernel、H5 Tool bypass PASS、H6 Session replay PASS、H7 Cancellation PASS、H8 Failure recovery PASS、H9 Upgrade rollback PASS。

---

## 37. Deployment Topology

Linux Host + Docker Compose：safety-kernel / agent-api / langgraph-runtime / deepseek-harness-runtime / homeassistant / audit-service / ollama。Harness isolated container，Safety Kernel separate container。

---

## 38. 网络隔离

frontend_net / agent_net / device_net / management_net。Agent Runtime 不能直连 IoT LAN，只能 Agent → Safety Kernel → Adapter → IoT。

---

## 39. MQTT

Phase 1 默认不启用。ESPHome 优先 Native API → HA。需 MQTT 时：listener + authentication + ACL + TLS/VPN。禁止 `allow_anonymous true`。

---

## 40. Docker 原则

禁止 latest/stable/main/changeme/default password。必须 exact version/healthcheck/restart policy/resource limit/read-only fs/cap_drop/no-new-privileges。可用 healthchecks 和 depends_on readiness 控制依赖启动。

---

## 41. Repository Structure

见下方 §41 目录树（实施时映射到本项目）。

---

## 42. Compatibility Matrix

M0 生成 docs/COMPATIBILITY_MATRIX.md，记录 Component/Current upstream/Selected baseline/Exact version/Known risks/Compatibility/Test evidence/Upgrade policy/Rollback version/Verification date。Harness 必须 pin commit SHA 或 exact package version，禁止 master/latest。

---

## 43. 2026-08-16 技术基线

DeepSeek Harness=Official Developer Preview；DeepSeek=V4-Pro GA/V4-Flash；LangGraph=1.2.11；HA=2026.8 family；ESPHome=2026.8 generation；Ollama=0.32.13。"Current upstream" 不代表最终 selected baseline，须经测试后 pin。

---

## 44. Phase 0 — Engineering Foundation

M0-A：repo/pyproject/lint/typecheck/pytest/CI/pre-commit/secret scanning。
M0-B：Capability Schema/Policy Engine/Audit/Execution State Machine/Verification Interface。
M0-C：Mock Adapter/Mock Device/Mock Runtime。
M0-D：DeepSeek Harness integration/LangGraph integration/Runtime Conformance Tests。
M0-E：Docker Compose/healthchecks/network segmentation/secrets/backup。

---

## 45. M0 Definition of Done

必须存在实际 Evidence：pytest.txt、typecheck.txt、lint.txt、compose-config.txt、security-scan.txt、runtime-conformance.txt，且 Tests PASS（而非"Agent 认为完成"）。

---

## 46. Phase 1A — Simulated Physical Loop

不连真实设备，模拟 Simulated AC，完整链 User→Runtime→Capability Request→Policy→Execution→Fake Adapter→Fake Physical Device→Verification→Audit。100+ scenario tests（正常/错误参数/重复/timeout/adapter crash/policy deny/verification fail/LLM wrong tool/cancellation/retry）。

---

## 47. Phase 1B — Home Assistant

先只读（state/temperature/entity metadata），通过后才 controlled write。HA Token 用 Dedicated non-admin identity + Safety Kernel 的 entity/service allowlist + parameter constraints。

---

## 48. Phase 1C — IR Gateway

确认 AC exact model/remote exact model/ESP exact board/IR protocol 后再设计。硬件依据 Manufacturer Datasheet，不依据博客接线图/AI 推测。

---

## 49. Phase 1D — Physical Verification

建立 V2/V3/V4 真实证据。验收不能写"99% reliable"，除非有 sample size/false positive/false negative/conditions/confidence interval。

---

## 50. Phase 1E — Reliability & Security

测试 network outage/HA restart/Agent restart/ESP reboot/power outage/duplicate command/invalid token/malicious prompt/prompt injection/adapter failure/verification disagreement。

---

## 51. Phase 2 — Vision

接入 Frigate/RTSP/Snapshots/Event detection/Vision Model。CameraAdapter 暴露 camera.snapshot/objects/event.latest/record，不把 RTSP URL 暴露给 LLM。

---

## 52. Phase 3 — Computers & Mobile

ComputerAdapter（computer.status/app.launch/file.open/command.execute_bounded，底层 MeshCentral/SSH/platform agent）。MobileAdapter（mobile.status/app.open/notification/ui_action，底层 ADB/scrcpy/platform API）。ADB 不允许 LLM 直调。

---

## 53. Phase 4 — Multi-device Orchestration

Planner 生成 Scene Plan，执行协调器处理 dependency/parallelization/rollback/verification，不让 LLM 随意顺序调 Tool。

---

## 54. Scene Transaction

多设备动作用 SceneExecution：prepare/execute/verify/compensate/finish。部分失败 → scene result=partial，必须明确报告。

---

## 55. Phase 5 — Controlled Self Evolution

M0-M4 稳定后开放。Evolution Engine 可发现未知设备/生成 Adapter candidate/生成测试/运行 simulator/提交 PR；默认不能自动部署到 Production。

---

## 56. Auto Promotion

成熟后可低风险 Adapter auto-promote，需 signed artifact/zero critical findings/contract tests/security tests/simulation pass/canary pass/low-risk capability only。

---

## 57. WorkBuddy 的定位

WorkBuddy 是 Principal Engineer/TPM/Implementation Agent/QA Coordinator。可用 DeepSeek V4 作开发模型之一。**WorkBuddy 不是 Owner。**

---

## 58. Governance

状态只能 Draft/Proposed/Approved/Deprecated/Rejected/Superseded。WorkBuddy 可写 "Reviewed-by: Architect/Security/QA Agent"，不能自己写 "Owner Approved"。

---

## 59. Gate Authority

只有 Owner 能宣布 Architecture Gate PASS / Hardware Gate PASS / M0 PASS / M1 PASS / Production Approved。Agent 不得自我批准。

---

## 60. WorkBuddy 每轮输出格式

每个 Milestone 报告 STATUS / IMPLEMENTED / TESTED / FAILED / BLOCKERS / RISKS / EVIDENCE / GIT COMMIT / NEXT GATE。没有 Evidence = 没有完成。

---

## 61. Source Verification Policy

电气/安全/API/版本/硬件 pin/协议只接受：Manufacturer datasheet → Official documentation → Official repository → Maintainer issue → Community。AI 生成的事实默认不可信直到有 source evidence。

---

## 62. Hardware Procurement Gate

禁止提前购买整套 M1 硬件。先确认空调品牌/型号/遥控器型号/服务器/电脑/GPU/网络拓扑，再完成 BOARD_SELECTION/GPIO_MAP/SCHEMATIC/BOM/ELECTRICAL_REVIEW，才 Hardware Gate → Purchase。

---

## 63. 顶级成品的最终 Definition of Done

Functionality（自然语言→物理设备）；Security（LLM 不能绕过 Policy）；Verification（区分"发出命令"vs"物理世界改变"）；Reliability（restart/network-failure/retry safe）；Observability（每次动作可追踪）；Reproducibility（git clone→bootstrap→validated deployment）；Extensibility（新增设备=新增 Adapter）；Evolvability（自动 research/generate/test/review/propose 新能力，但不能绕过 Security Gate）。

---

## 64. 最终技术战略

DeepSeek Harness + LangGraph fallback + Physical Safety Kernel + Capability Gateway + Adapter Architecture + Evidence-based Verification + Controlled Evolution Plane。

---

## 65. 当前项目状态（截至 v3.0）

Product Vision=APPROVED DIRECTION；Architecture=PROPOSED；DeepSeek Harness=INCLUDED/EXPERIMENTAL；Physical Safety Kernel=REQUIRED；M0=NOT STARTED；M1 Hardware=NOT APPROVED FOR PURCHASE；Physical Control=DISABLED；Production=NOT READY。

---

## 66. WorkBuddy 下一步唯一任务

现在不做 Phase 1、不买硬件、不重写几十页 PDF。**START M0-FOUNDATION**，第一轮只建立：repo skeleton、pyproject、CI、Capability Schema、Policy Engine、Execution State Machine、Verification Model、Mock Adapter、Mock Device、Audit Store、Runtime Interface、DeepSeek Harness Runtime prototype、LangGraph Runtime prototype、Runtime Conformance Suite、Docker Compose development environment。不得：连接真实空调、加载真实 HA write token、运行 ADB、运行 MeshCentral command、部署 LLM-generated physical plugin。

---

## 67. M0 First Gate

第一批交付 repo.zip + git log + evidence/（pytest PASS、lint PASS、typecheck PASS、compose config PASS、secret scan PASS、runtime conformance PASS、policy bypass tests PASS）。然后 M0 Gate Review，通过后进入 M1A Simulated AC Closed Loop。

---

## 68. 最终一句定义

> 这是一个可以逐渐学习如何影响真实世界，但永远不能绕过确定性安全边界的自进化 AI 操作系统。
