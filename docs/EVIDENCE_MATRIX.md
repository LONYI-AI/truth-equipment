# EVIDENCE_MATRIX — 官方一手资料证据矩阵

版本：v0.2（2026-08-16）
状态：**Proposed / Pending Owner Approval**

> **目的**：每个关键事实必须标注 Claim、Primary Source、Exact evidence、Date verified、Confidence、Impact if wrong。**未经此矩阵支撑的事实不得写入设计文档。**

---

## 1. 硬件元件（Vishay / Espressif / Sensirion）

| # | Claim | Primary Source | Exact evidence | Date verified | Confidence | Impact if wrong |
|---|---|---|---|---|---|---|
| H-01 | TSOP38238 pinout = Pin1 OUT / Pin2 GND / Pin3 VS | Vishay datasheet 82491 | "Pinning: 1 = OUT, 2 = GND, 3 = VS" | 2026-08-15 | **高** | 接反→接收器不工作或损坏 |
| H-02 | TSOP38238 供电 2.5–5.5V，供电电流 typ 0.27/max 0.45mA | Vishay 82491 | "Supply voltage VS 2.5–5.5 V；ISD typ 0.27 max 0.45 mA" | 2026-08-15 | **高** | 供电超压→损坏；欠压→不工作 |
| H-03 | TSOP38238 去耦 R1+C1 是"供电有强纹波时推荐"，非"无需外部元件" | Vishay 82491 应用电路 | "R1 and C1 recommended in case there are strong ripple or spikes on the supply line" | 2026-08-15 | **高** | 误省去耦→噪声误码 |
| H-04 | TSAL6200 VF=1.35V typ/1.6V max @100mA；IF(DC)=100mA；IFM=200mA；PV=210mW；940nm | Vishay 81010 | "VF 1.35/1.6 V @ IF=100mA；IFM 200 mA (tp/T=0.5)；PV 210 mW；λp 940nm" | 2026-08-15 | **高** | 过流→LED 烧毁；限流电阻算错→寿命短 |
| H-05 | TSAL6200 tr/tf 存在版本差异（15ns vs 800ns） | Vishay 81010 多版本 | 两版 datasheet 数值不一致 | 2026-08-15 | **中**（版本差异已知，对 38kHz 无影响）| 若当真值设计高频→误判 |
| H-06 | ESP32-C3 strapping pins = GPIO2/GPIO8/GPIO9 | ESP32-C3 Datasheet v2.4 | "3 个 strapping 管脚：GPIO2/GPIO8/GPIO9" | 2026-08-15 | **高** | 占用 strapping→启动异常 |
| H-07 | GPIO9 默认弱上拉；GPIO2/GPIO8 浮空 | ESP32-C3 Datasheet v2.4 | "GPIO2 浮空、GPIO8 浮空、GPIO9 上拉" | 2026-08-15 | **高** | 误判默认电平 |
| H-08 | ESP32-C3 GPIO 最大源电流 40mA/灌 28mA（PAD_DRIVER=3）；默认驱动 10/20mA | ESP32-C3 Datasheet v2.4 | "IOH 40mA, IOL 28mA；GPIO2/3/MTMS/MTDI 默认 10mA，其余 20mA" | 2026-08-15 | **高** | 超驱动→GPIO 损坏 |
| H-09 | ESP32-C3-DevKitM-1 板载 WS2812 RGB LED 由 GPIO8 驱动；USB-UART 占 GPIO20/21 | Espressif DevKitM-1 用户指南 | Header Block 表 + 组件描述 | 2026-08-15 | **高** | GPIO8 被 LED 争用 |
| H-10 | SHT31-DIS 为 I2C 温湿度传感器 | Sensirion SHT3x-DIS datasheet | Datasheet 标题与接口 | 2026-08-15 | **高** | 选错型号→接口不匹配 |

---

## 2. 软件栈版本（2026-08 核实）

| # | Claim | Primary Source | Exact evidence | Date verified | Confidence | Impact if wrong |
|---|---|---|---|---|---|---|
| S-01 | Home Assistant 当前 stable = 2026.8.2 | HA 官方博客 + GitHub releases | "2026.8.2 — 34 bug fixes"（08-14）| 2026-08-15 | **高** | pin 错版本→已知 bug 或不可复现 |
| S-02 | Ollama 当前 = v0.32.13（v0.1 的 0.5.7 已过时） | GitHub ollama/ollama releases | "v0.32.13"（08-14）| 2026-08-15 | **高** | 用 0.5.7→缺 Qwen3 tool calling 支持 |
| S-03 | Qdrant 当前 stable = v1.18.1 | qdrant.tech blog + GitHub releases | "v1.18.0 TurboQuant (05-11)；v1.18.1 (05-22)" | 2026-08-15 | **高** | pin 错版本 |
| S-04 | LangGraph 当前 = 1.2.5；1.0 为 LTS | PyPI + 社区 release 追踪 | "langgraph==1.2.5 (06-12)；1.0 LTS" | 2026-08-15 | **中高** | pin 错版本线 |
| S-05 | ESPHome 版本线 ≥2026.4.0（精确 patch 待定） | esphome.io changelog | "2026.1.0 / 2026.4.0" 存在；最新 patch 未拉取确认 | 2026-08-15 | **中** | patch 未定→M0 落地时补齐 |
| S-06 | Docker Compose CLI = v5.1.1（本机实测） | 本机 `docker compose version` | 实测输出 | 2026-08-16 | **高** | 本地校验环境不一致 |

---

## 3. Home Assistant 鉴权（P0-5 关键证据）

| # | Claim | Primary Source | Exact evidence | Date verified | Confidence | Impact if wrong |
|---|---|---|---|---|---|---|
| A-01 | HA long-lived token 继承创建用户的**全部权限**，无 entity-level scope | HA 官方 auth 文档 + 多方独立确认 | "tokens inherit the full permissions of the user account"; "You can't scope them to specific entities or read-only access" | 2026-08-15 | **高** | 误以为 token 可细粒度授权→越权风险 |
| A-02 | 限制权限的唯一方式是 dedicated non-admin user | HA 文档 | "Create a dedicated non-admin user to limit scope" | 2026-08-15 | **高** | 授权模型设计错误 |

---

## 4. 撤回的 v0.1 声明（不再作为事实）

| # | v0.1 声明 | 处置 | 原因 |
|---|---|---|---|
| R-01 | "Chroma CVE-2026-45829 未修复" | **撤回** | 该 CVE 编号未经官方渠道核实，属未经验证声明 |
| R-02 | "IR 回读可靠性 99%" | **撤回** | 未经本项目实测 |
| R-03 | "端到端延迟 <3s / <5s" | **撤回** | 未经实测硬件标定 |
| R-04 | "Qwen3 tool calling 错误率 <1%" | **撤回** | 未经本项目实测 |
| R-05 | "temperature=0 保证相同输出" | **撤回** | 技术错误（浮点/调度非确定性）|
| R-06 | "审计日志不可篡改" | **撤回** | 本地 hash-chain 只能 tamper-evident |

---

## 5. 置信度说明

| 置信度 | 含义 |
|---|---|
| **高** | 官方 datasheet/release 页直接核实，可复现 |
| **中高** | 官方渠道核实，但版本线可能有后续 patch |
| **中** | 官方渠道确认存在，但精确值待 M0 落地补齐 |
| **低** | 二手来源，禁止写入设计文档 |

---

*本矩阵是设计文档事实的权威来源。任何新增关键事实必须先登记本表。*
