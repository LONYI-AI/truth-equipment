# HARDWARE_BOM — Physical AI Agent Platform 硬件清单

版本：v0.2（2026-08-16，Architecture Audit v0.2）
状态：**Proposed / Pending Owner Approval**
货币：CNY（人民币）

> **本文件已从 v0.1 全面修订**（对应 Architecture Audit P0-1/P0-2/P0-3）。
> 电气细节已下沉到 `docs/hardware/` 子目录，本文件只保留采购清单与成本。
> 所有电气参数以 manufacturer primary datasheet 为准，详见 Evidence Matrix。

---

## 1. 采购清单（M1C 空调红外闭环）

### 1.1 核心必购项

| # | 物品 | 精确型号 | 数量 | 参考价 | 用途 |
|---|---|---|---|---|---|
| H1 | **开发板** | **Espressif ESP32-C3-DevKitM-1**（官方 SKU）| 1 | ¥20-30 | 主控（见 BOARD_SELECTION.md）|
| H2 | IR 发射管 | **Vishay TSAL6200**（940nm, 5mm）| 2 | ¥2/个 | IR 发射（1 用 1 备）|
| H3 | IR 接收管 | **Vishay TSOP38238**（38kHz）| 1 | ¥2 | IR 回读验证（见 §2 pinout 修正）|
| H4 | NPN 三极管 | **2N2222A**（TO-92, onsemi/ST）| 2 | ¥0.5/个 | IR 驱动（1 用 1 备）|
| H5 | 电阻 | 33Ω **1/2W** ×2、330Ω ×2、100Ω ×2、4.7kΩ ×4 | 1套 | ¥3 | 限流/基极/去耦/I2C上拉 |
| H6 | 电容 | 0.1µF ×2、4.7–10µF ×1 | 1套 | ¥2 | TSOP38238 去耦 + 电源轨去耦 |
| H7 | 温湿度传感器 | **Sensirion SHT31-DIS**（I2C）| 1 | ¥10-15 | 温度趋势验证 |
| H8 | 面包板 + 杜邦线 | 830 孔面包板 + 公对公/母对母 | 1套 | ¥10 | 原型插接 |
| H9 | USB 电源 | Micro-USB 线 + 5V/1A 充电头 | 1 | 已有 | 供电 |

**小计：约 ¥50-70**

### 1.2 可选增强项

| # | 物品 | 型号 | 价格 | 用途 |
|---|---|---|---|---|
| O1 | 计量智能插座 | WiFi/Zigbee 功率计量 | ¥40-120 | 功率验证通道（M1D 可选）|
| O2 | 麦克风模块 | MAX9814 | ¥15-50 | 声学验证（M1D 可选）|
| O3 | 逻辑电平 N-MOSFET | AO3400A（SOT-23）| ¥1 | 最终固定化替代 BJT（见 IR_GATEWAY_SCHEMATIC §5.1）|

---

## 2. TSOP38238 引脚定义（关键修正，对应 P0-1）

> **v0.1 错误**：把 TSOP38238 写成 "1=VCC, 2=GND, 3=OUT"。
> **正确（Vishay datasheet 82491）**：

| Pin | 功能 |
|---|---|
| **Pin 1 = OUT** | 解调输出（开漏、低有效）|
| **Pin 2 = GND** | 地 |
| **Pin 3 = VS** | 电源（2.5–5.5 V）|

识别方向：从球面透镜一侧朝自己看，引脚朝下，从左到右为 **1(OUT)、2(GND)、3(VS)**。

**去耦/滤波**：Vishay 应用电路建议在供电线有强纹波/尖峰时加 **R1(100Ω) + C1(0.1µF)**。本项目 ESP32-C3 的 Wi-Fi 突发电流会产生纹波，故采纳此建议（非"无需外部元件"）。详见 [IR_GATEWAY_SCHEMATIC.md](hardware/IR_GATEWAY_SCHEMATIC.md) §4。

---

## 3. 接线说明（指向详细文档）

| 内容 | 文档 |
|---|---|
| 精确开发板选型与引脚约束 | [hardware/BOARD_SELECTION.md](hardware/BOARD_SELECTION.md) |
| GPIO 分配表（GPIO0/3/1/10）| [hardware/GPIO_MAP.md](hardware/GPIO_MAP.md) |
| 完整原理图 + 电气计算（含 BJT/MOSFET 对比、电阻瞬时功率）| [hardware/IR_GATEWAY_SCHEMATIC.md](hardware/IR_GATEWAY_SCHEMATIC.md) |
| 上电前后检查清单 | [hardware/ELECTRICAL_REVIEW_CHECKLIST.md](hardware/ELECTRICAL_REVIEW_CHECKLIST.md) |

> **不再在本文件重复电路图**（v0.1 的电路图有错误，已废弃）。单一事实来源 = IR_GATEWAY_SCHEMATIC.md。

---

## 4. LLM 推理主机（阻塞项 B1，未确认）

### 4.1 需求（依据模型，非臆测）

| 组件 | qwen3:8b（Q4 量化，~5GB）| 说明 |
|---|---|---|
| GPU VRAM | ≥ 8 GB（推荐）| 留余量给系统与 KV cache |
| 系统内存 | ≥ 16 GB | CPU 降级时需更多 RAM |
| 存储 | SSD ≥ 50 GB | 模型 + 向量数据 + 日志 |

> **延迟承诺（v0.1 修正）**：v0.1 曾写"端到端 <3s / <5s"。**这些数字在无实测硬件前不作承诺**。最终延迟以 M1E 实测基线为准（见 COMPATIBILITY_MATRIX.md 与 ACCEPTANCE_TESTS.md 的"性能标定"章节）。

### 4.2 方案（由 Owner 决策）

| 方案 | 配置 | 成本 |
|---|---|---|
| A. 现有带独显台式机/笔记本 | GTX 1660S / RTX 3060 以上 | 已有则零成本 |
| B. 二手显卡升级 | GTX 1660 Super（¥600 左右二手）| ¥500-1000 |
| C. Mac 统一内存 | M1/M2/M3 16GB+（用 MLX，非 Ollama CUDA）| 已有则零成本 |
| D. 纯 CPU 降级 | 仅开发调试用，延迟高 | 零成本 |

---

## 5. 常开服务器（阻塞项 B2，未确认）

| 要求 | 规格 |
|---|---|
| CPU / 内存 | 2 core+ / 4GB+（推荐 8GB）|
| 存储 | 64GB+ SSD |
| OS | Linux（Ubuntu 24.04 / Debian 13）——HA host network 需要 Linux |
| 网络 | 以太网，与 IoT 设备同子网 |

> **明确**：Windows 仅作开发环境，**不能作为生产 HA 服务器**（host networking + mDNS 依赖 Linux）。

---

## 6. 空调品牌协议识别（对应 P1-4）

> **v0.1 错误**：直接按品牌猜 ESPHome climate platform。
> **正确流程**：先取证（精确型号 + 遥控器型号 + 协议证据），再选 platform。

| 步骤 | 内容 |
|---|---|
| 1 | 记录空调铭牌上的**精确型号**（如 TCL KFRd-35GW/...）|
| 2 | 记录遥控器**型号/编号**（通常印在遥控器背面或电池仓）|
| 3 | 用 ESPHome `remote_receiver` 抓取遥控器原始码，识别协议（NEC/DAIKIN/Gree 等）|
| 4 | 依据协议证据选 platform（native `climate_ir` 平台 vs HeatpumpIR fallback）|
| 5 | 区分 `midea`（UART/直连）与 `midea_ir`（红外）等**完全不同的 transport** |

详细流程见 [COMPATIBILITY_MATRIX.md](../COMPATIBILITY_MATRIX.md) 的 ESPHome 条目与 M1C 任务。

---

## 7. 成本汇总

| 类别 | 金额 |
|---|---|
| IoT 硬件（H1-H9）| ¥50-70 |
| LLM 主机（可选新购显卡）| ¥0-1000 |
| 服务器（利旧或新购）| ¥0-2000 |
| **最低（仅 IoT 硬件）** | **¥50-70** |

---

## 8. 供应商参考（非广告）

| 物品 | 渠道 | 备注 |
|---|---|---|
| ESP32-C3-DevKitM-1 | 淘宝/立创搜"ESP32-C3-DevKitM-1" | 认准 Espressif 官方板，勿买山寨 |
| TSAL6200 / TSOP38238 | 淘宝搜"TSAL6200"、"TSOP38238" | 认准 Vishay 原厂，注意 TSOP38238 pinout |
| 2N2222A | 淘宝搜"2N2222A TO-92" | onsemi/ST 原厂 |
| SHT31-DIS | 淘宝搜"SHT31 温湿度传感器" | 认准 Sensirion SHT31-DIS |
| 电阻电容包 | 淘宝搜"电阻包 1/2W"、"电容包" | 注意 1/2W 电阻 |

---

*本文件随采购进展更新。所有电气事实以 docs/hardware/ 与 Evidence Matrix 为准。*
