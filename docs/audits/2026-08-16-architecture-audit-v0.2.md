# Architecture Audit v0.2 — 二次审计报告

版本：v0.2（2026-08-16）
审计人：Principal Engineer / TPM（模拟角色）
状态：**Pending Owner Approval**（REVISION REQUIRED 后重新提交）
上游：v0.1 审计报告（已被外部独立审查驳回）

---

## 0. 结论摘要

v0.1 的总体架构方向获认可，但外部审查发现 11 项 P0 + 4 项 P1 问题。本 v0.2 已**逐项整改**，全部以 manufacturer primary datasheet / 官方 release 页为准重新核实，并撤回所有未经实测的可靠性/延迟数字与未经官方渠道验证的 CVE 声明。

**v0.2 的核心改进：**
1. 硬件事实全部绑定官方 datasheet（Vishay / Espressif / Sensirion），TSOP38238 pinout 已纠正。
2. GPIO 分配绑定到 ESP32-C3-DevKitM-1 具体 SKU，避开全部 strapping pin。
3. 验证模型重构为 V0–V4 证据链，纠正"IR 回读=状态验证"的错误。
4. HA 授权改为双层（dedicated non-admin user + Capability Gateway），删除虚假 entity-level 权限描述。
5. 架构抽象改为 Capability Gateway + Adapter Layer（HA 降为 primary smart-home adapter）。
6. 版本全部重新核实（Ollama 0.5.7→0.32.13），新增 COMPATIBILITY_MATRIX 与 EVIDENCE_MATRIX。
7. Compose 重构为根目录可执行模型，fail-closed secrets，已通过 `docker compose config` 校验。
8. 治理修正：所有 ADR = Proposed / Pending Owner Approval，删除虚假审批签名，Git 措辞改为 "prepared for first commit"。
9. 审计完整性语义改为 tamper-evident，禁用 hash()，使用 SHA-256/HMAC。
10. 修复全部可执行伪代码缺陷（await 在 def、zip dict、HA 返回契约、temperature=0）。

---

## 1. 逐项整改状态

| 编号 | 项 | v0.1 问题 | v0.2 整改 | 状态 |
|---|---|---|---|---|
| P0-1 | 硬件 BOM 正确性 | TSOP38238 pinout 写错、"无需外部元件"绝对化 | 纠正 pinout，按 datasheet 表述去耦条件 | ✅ 已整改 |
| P0-2 | GPIO 安全 | generic GPIO 固定 | 锁定 DevKitM-1 SKU，避开 strapping | ✅ 已整改 |
| P0-3 | IR 驱动 | hFE≈100 估算 | forced-β 饱和设计 + 电阻瞬时功率 + MOSFET 对比 | ✅ 已整改 |
| P0-4 | 物理验证 | IR readback 误当状态验证 | V0-V4 证据链，删除未实测数字 | ✅ 已整改 |
| P0-5 | HA 授权 | 虚假 entity-level 权限 | 双层授权，删除错误 UI 描述 | ✅ 已整改 |
| P0-6 | 架构抽象 | HA 唯一抽象层 | Capability Gateway + Adapter Layer | ✅ 已整改 |
| P0-7 | 版本验证 | 版本自相矛盾、无 CVE 绝对化 | COMPATIBILITY_MATRIX + 撤回 CVE 声明 | ✅ 已整改 |
| P0-8 | Compose 可执行 | 路径冲突、fail-open secrets | 根目录 compose + fail-closed + healthcheck + 校验 | ✅ 已整改 |
| P0-9 | 治理 | 虚假 Accepted + 签名 | 全改 Proposed + Reviewed-by-simulated-role | ✅ 已整改 |
| P0-10 | 审计完整性 | "不可篡改" | tamper-evident + SHA-256/HMAC + 密钥隔离 | ✅ 已整改 |
| P0-11 | 代码缺陷 | await 在 def、zip dict、HA 契约、temp=0 | 全部修正 | ✅ 已整改 |
| P1-1 | 记忆架构 | Qdrant 过早启用 | SQLite 为主，Qdrant planned | ✅ 已整改 |
| P1-2 | 模型抽象 | qwen3:8b 写死 | ModelProvider + benchmark | ✅ 已整改 |
| P1-3 | 上下文风险 | 静态 Tier 过粗 | risk=f(principal,device,...context) | ✅ 已整改 |
| P1-4 | ESPHome 协议 | 按品牌猜 platform | 先取证再选 platform，区分 transport | ✅ 已整改 |

---

## 2. 撤回的 v0.1 不当声明

| 声明 | 撤回原因 |
|---|---|
| "Chroma CVE-2026-45829 未修复" | CVE 编号未经官方渠道核实 |
| "IR 回读可靠性 99%" | 未经实测 |
| "端到端 <3s / <5s" | 未经实测硬件标定 |
| "Qwen3 tool calling 错误率 <1%" | 未经实测 |
| "temperature=0 保证相同输出" | 技术错误 |
| "审计日志不可篡改" | 只能 tamper-evident |
| "HA token 可配 entity-level 权限" | HA 官方文档证伪 |

---

## 3. Repository Consistency Audit（最终一致性校验）

### 3.1 文件存在性

运行结果见下方"一致性校验执行记录"。所有引用文件均已创建。

### 3.2 关键一致性断言

- [x] 所有 ADR 状态 = Proposed / Pending Owner Approval（无 Accepted）
- [x] 无 "Principal Architect ✅" 虚假签名（已改 Reviewed-by-simulated-role）
- [x] 无 "已提交 Git" 措辞（已改 prepared for first commit；git log 为空）
- [x] 无 `${SECRET:-changeme}`（已改 `${SECRET:?}`）
- [x] 无 Python `hash()` 用于完整性（已改 SHA-256）
- [x] 无 "不可篡改"（已改 tamper-evident）
- [x] 无 "99% / 95% / <3s" 未经实测的事实性宣称（改为"待实测目标"）
- [x] 无 "无 CVE 风险" 绝对化表述
- [x] compose.yaml / compose.dev.yaml 通过 `docker compose config` 校验

---

## 4. 阻塞项（不变）

| # | 阻塞项 | 状态 |
|---|---|---|
| B4 | **本 Architecture Audit v0.2 待 Owner 批准** | ⏳ 等 Owner |
| B1 | LLM 推理主机（GPU）未确认 | ⏳ 等 Owner |
| B2 | 常开 Linux 服务器未确认 | ⏳ 等 Owner |
| B3 | 空调精确品牌/型号未知 | ⏳ 等 Owner |

---

## 5. 提交给 Owner 的决策请求

1. 是否批准 Architecture Audit v0.2？
2. 若有残余问题，具体编号与意见。
3. 确认 B1/B2/B3 阻塞项。

**批准前：不进行真实设备控制、不采购硬件、不进入 M0 implementation、不把任何 ADR 标为 Accepted。**

---

*本报告由模拟角色（Principal Engineer / TPM）撰写。最终架构批准权在 Owner。*
