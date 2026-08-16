# CHANGELOG_FROM_V01 — Architecture Audit v0.1 → v0.2 变更清单

版本：v0.2（2026-08-16）
状态：**Proposed / Pending Owner Approval**

> 本文记录 v0.1（第一次 Architecture Audit）被外部审查驳回（REVISION REQUIRED）后，v0.2 的全部整改。逐项对应审查意见编号（P0-1 ~ P0-11，P1-1 ~ P1-4）。

---

## 1. P0 级整改（必须修正）

### P0-1 Hardware BOM correctness（TSOP38238 pinout 错误）

| 项 | v0.1（错误）| v0.2（修正）|
|---|---|---|
| TSOP38238 pinout | "1=VCC, 2=GND, 3=OUT" | **Pin 1 = OUT, Pin 2 = GND, Pin 3 = VS**（Vishay datasheet 82491）|
| 去耦电路 | "无需外部元件"（绝对结论）| R1(100Ω)+C1(0.1µF) **在供电线有强纹波/尖峰时推荐**（Vishay 应用电路原文）|
| 元件型号 | 未精确到厂商 datasheet | TSAL6200 (Vishay 81010)、TSOP38238 (Vishay 82491)、2N2222A (onsemi)、SHT31-DIS (Sensirion) 均给出 datasheet URL |

### P0-2 ESP32-C3 GPIO safety（generic GPIO 固定）

| 项 | v0.1 | v0.2 |
|---|---|---|
| 开发板 | "generic ESP32-C3" | **锁定 ESP32-C3-DevKitM-1 具体 SKU**（见 hardware/BOARD_SELECTION.md）|
| GPIO | GPIO2/8/9 混用 | 避开全部 3 个 strapping pin；用 GPIO0/1/3/10（自由引脚）|
| 冲突识别 | 未考虑板载 RGB LED / BOOT 按钮 | GPIO8=板载 RGB、GPIO9=BOOT 按钮已识别并避开 |

### P0-3 IR transmitter driver review（hFE≈100 估算）

| 项 | v0.1 | v0.2 |
|---|---|---|
| 基极电流 | 按 hFE≈100 估算 | **forced-β（β_forced=15）饱和设计**，Ib≈7.9mA |
| 电阻瞬时功率 | 未计算 | **P_inst=I²R≈0.34W → R_LIM 选 1/2W** |
| BJT vs MOSFET | 未评估 | 给出完整对比（BJT 主方案 + AO3400A 备选）|
| 双 LED | 未讨论 | 明确 series/parallel 拓扑 + per-LED 独立限流 + 光学摆放 |

### P0-4 Redefine Physical Verification（IR readback 误当状态验证）

| 项 | v0.1 | v0.2 |
|---|---|---|
| 验证模型 | "多信号融合，IR 回读 99%" | **V0-V4 五级证据链**（ADR-0006）|
| IR 回读语义 | 误当"设备状态验证" | 正确定位为 **V2（actuator output verified）** |
| 可靠性数字 | "99% reliability" | **删除**；改为带 sample size/conditions/FPR/FNR/CI 的实验报告 |

### P0-5 Home Assistant authorization model（虚假 entity-level 权限）

| 项 | v0.1 | v0.2 |
|---|---|---|
| 错误声明 | "给 Integration Token 配 entity-level permissions" | **已删除**。HA token 无 entity scope（官方文档核实）|
| 授权设计 | 单一 token 层 | **双层**：Layer A（dedicated non-admin user）+ Layer B（Capability Gateway allowlist）|

### P0-6 Architecture abstraction correction（HA 唯一抽象层）

| 项 | v0.1 | v0.2 |
|---|---|---|
| ADR-0001 | "HA 作为唯一设备抽象层" | **Capability Gateway + Adapter Layer**；HA 降为 primary smart-home/IoT adapter |

### P0-7 Version and compatibility verification（版本自相矛盾）

| 项 | v0.1 | v0.2 |
|---|---|---|
| 版本 | compose 里 Ollama 0.5.7（2024 版），却声称"2026-08 verified" | **修正为 v0.32.13**，新增 COMPATIBILITY_MATRIX.md 明确区分 latest vs baseline |
| "无 CVE 风险" | 绝对表述 | **删除** |

### P0-8 Docker Compose must become executable

| 项 | v0.1 | v0.2 |
|---|---|---|
| 文件位置 | docker/compose.core.yml（路径冲突）| **根目录 compose.yaml + compose.dev.yaml** |
| secrets | `${VAR:-changeme}`（fail-open）| **`${VAR:?VAR is required}`（fail-closed）** |
| healthcheck | 无 | HA/Ollama/Qdrant/Mosquitto 均加 healthcheck |
| 网络 | 未区分 | host-network HA vs bridge-network 服务明确区分；host URL vs container DNS 明确 |
| 校验 | 未执行 | **已执行 `docker compose config` 并保存结果**（docker/COMPOSE_VALIDATION.md）|

### P0-9 Governance correction（虚假审批签名）

| 项 | v0.1 | v0.2 |
|---|---|---|
| ADR 状态 | "Accepted" | **全部改为 "Proposed / Pending Owner Approval"** |
| 签名 | "Principal Architect ✅ / QA ✅" | **改为 "Reviewed-by-simulated-role"**，附"不等同项目批准"声明 |
| Git 措辞 | "已提交 Git" | **改为 "prepared for first commit"**（当前无 commit）|

### P0-10 Audit integrity semantics（"不可篡改"→"tamper-evident"）

| 项 | v0.1 | v0.2 |
|---|---|---|
| 术语 | "不可篡改日志" | **tamper-evident（可检测篡改）** |
| 完整性机制 | 链式哈希（含糊）| canonical serialization → SHA-256 chain → signed/HMAC checkpoint → 签名密钥隔离 → 离机副本 |
| 禁用 | （隐式用 hash()）| **明确禁止 Python built-in hash()**；Acceptance Test 用真实 SHA-256/HMAC |

### P0-11 Correct code/pseudocode defects

| 项 | v0.1 缺陷 | v0.2 修正 |
|---|---|---|
| PolicyGate | `def` 内用 `await` | 改为 `async def`（ADR-0005）|
| Sensor fusion | `zip(signals.values(), weights)` 用 dict keys | 已删除该错误代码，改为 V0-V4 接口（ARCHITECTURE.md）|
| HA REST 返回 | 假设 `{"result":"success"}` | 修正为"返回 200 + 受影响实体列表"（ACCEPTANCE_TESTS）|
| LLM 确定性 | "temperature=0 保证相同输出" | **删除**，改为"低温度降低（非消除）方差"（ADR-0003）|

---

## 2. P1 级整改

### P1-1 Memory architecture（Qdrant 是否 M1 必需）

- **结论**：M1 不启用 Qdrant。MemoryStore 接口 + SqliteMemoryStore 为主，QdrantMemoryStore 为 planned adapter（ADR-0004 重写）。

### P1-2 Model abstraction and benchmark（qwen3:8b 写死）

- **结论**：建立 ModelProvider 接口 + OllamaProvider；qwen3:8b 降为候选；新增 tests/benchmarks/model_tool_calling/（ADR-0003 重写）。

### P1-3 Contextual risk policy（静态 Tier 过粗）

- **结论**：`risk = f(principal, device, capability, action, parameters, context)`（ADR-0005 重写）。

### P1-4 Correct ESPHome protocol mapping（按品牌猜 platform）

- **结论**：先取证（精确型号+遥控器型号+协议证据）→ 再选 platform；区分 midea 与 midea_ir 等不同 transport（HARDWARE_BOM §6）。

---

## 3. 文件级变更清单

### 新增
- `hardware/BOARD_SELECTION.md`
- `hardware/GPIO_MAP.md`
- `hardware/IR_GATEWAY_SCHEMATIC.md`
- `hardware/ELECTRICAL_REVIEW_CHECKLIST.md`
- `docs/COMPATIBILITY_MATRIX.md`
- `docs/EVIDENCE_MATRIX.md`
- `docs/CHANGELOG_FROM_V01.md`（本文件）
- `docs/audits/2026-08-16-architecture-audit-v0.2.md`
- `compose.yaml` + `compose.dev.yaml`（根目录）
- `docker/COMPOSE_VALIDATION.md`
- `tests/benchmarks/model_tool_calling/`（目录占位）

### 修订
- `docs/HARDWARE_BOM.md`（pinout 修正、电路下沉）
- `docs/ARCHITECTURE.md`（Capability Gateway + Adapter、V0-V4、tamper-evident、代码修正）
- `docs/SECURITY_MODEL.md`（HA 双层授权、tamper-evident、fail-closed）
- `docs/THREAT_MODEL.md`（tamper-evident 语义）
- `docs/ACCEPTANCE_TESTS.md`（crypto 校验、数字纪律、HA 契约修正）
- `docs/ROADMAP.md`（标定目标加"待实测"）
- `docs/PRODUCT_SPEC.md`（可靠性/延迟改为待标定）
- `docs/DECISIONS/ADR-0000 ~ 0009`（状态 + 签名 + 内容）
- `README.md`、`AGENTS.md`、`.env.example`、`.gitignore`

### 删除
- `docker/compose.core.yml`（被根目录 compose.yaml 取代）

---

*本文档是 v0.1→v0.2 的权威变更记录。*
