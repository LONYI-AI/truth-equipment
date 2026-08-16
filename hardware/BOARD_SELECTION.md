# BOARD_SELECTION — ESP32-C3 开发板选型

版本：v0.2（2026-08-16，Architecture Audit v0.2）
状态：**Proposed / Pending Owner Approval**

---

## 1. 结论

**选定开发板：Espressif ESP32-C3-DevKitM-1**（官方 SKU）

| 属性 | 值 |
|---|---|
| 官方型号 | ESP32-C3-DevKitM-1 |
| 核心模组 | ESP32-C3-MINI-1（PCB 天线） |
| 芯片 | ESP32-C3FN4（封装内 4 MB flash） |
| 处理器 | RISC-V 32 位单核，最高 160 MHz |
| SRAM | 400 KB（16 KB cache） |
| 无线 | Wi-Fi 802.11 b/g/n + Bluetooth 5 (LE) |
| USB | Micro-USB（板载 USB-UART 桥，最高 3 Mbps） |
| 板载 LED | 可寻址 RGB LED（WS2812），**由 GPIO8 驱动** |
| 供电 | Micro-USB（默认）/ 5V+GND 排针 / 3V3+GND 排针 |
| 电源转换 | 板载 5V→3.3V 稳压器 |
| 尺寸 | 排针间距 2.54 mm，可直接插面包板 |
| 价格参考 | ¥20-30 |

**官方一手资料：**
- 用户指南（含 Header Block / Pin Layout）：https://docs.espressif.com/projects/esp-idf/en/stable/esp32c3/hw-reference/esp32c3/user-guide-devkitm-1.html
- 原理图（Schematic PDF）：https://docs.espressif.com/projects/esp-idf/en/stable/esp32c3/hw-reference/esp32c3/user-guide-devkitm-1.html#related-documents
- 芯片数据表（ESP32-C3 Datasheet）：https://www.espressif.com/documentation/esp32-c3_datasheet_en.pdf

---

## 2. 选型理由

| 考量 | DevKitM-1 的表现 |
|---|---|
| **官方保证** | Espressif 官方板，schematic/pinout/datasheet 全部公开，可直接审计 |
| **面包板友好** | 2.54 mm 排针，两侧引脚全部引出，可直接插接 |
| **供电简单** | Micro-USB 5V + 板载稳压器，无需外接 3.3V |
| **闪存内置** | 4 MB flash 封装在芯片内，SPI flash 引脚（IO4-IO7）解放为普通 GPIO |
| **风险可控** | 无第三方山寨板的引脚差异/稳压器虚标问题 |

**未选的备选板（记录备查）：**

| 备选 | 未选原因 |
|---|---|
| Seeed Studio XIAO ESP32-C3 | 引脚少（11 个 GPIO）、引脚定义需另查 Seeed 资料；排针非标准面包板布局 |
| ESP32-C3-DevKitC-02 | 同样官方，但板载 RGB LED 同样占 GPIO8，且部分批次 USB-C 有识别问题；与 M-1 差异不大 |
| 合宙/通用 ESP32-C3 板 | 第三方，无统一 schematic，引脚可能与官板不一致（正是 P0-2 要避免的"generic ESP32-C3 层面固定 GPIO"问题）|
| ESP32-C3-DevKit-RUST-1 | 尺寸大、价格高，功能超出本项目需要 |

> **关键约束（对应 P0-2）**：本项目的 GPIO 分配必须绑定到 **ESP32-C3-DevKitM-1 这一具体 SKU**，而非"generic ESP32-C3"。不同板子的 RGB LED、BOOT 按钮、USB-UART 桥、稳压器可能占用不同引脚。更换板子时必须重新走 GPIO_MAP.md 审计。

---

## 3. 板载资源占用清单（影响 GPIO 分配）

| 板载功能 | 占用引脚 | 对 GPIO 分配的影响 |
|---|---|---|
| RGB LED（WS2812）| **GPIO8** | GPIO8 不可用作 IR/Sensor（否则与 LED 争用 + 启动时 LED 闪烁干扰）|
| USB-UART 桥（CP2102 等）| **GPIO20 (RX) / GPIO21 (TX)** | 保留为串口 console，勿占用 |
| 原生 USB Serial/JTAG | **GPIO18 (USB_D-) / GPIO19 (USB_D+)** | 勿占用 |
| BOOT 按钮 | **GPIO9**（外部下拉）| GPIO9 是 strapping pin，勿占用 |
| RST 按钮 | EN (CHIP_PU) | 复位专用 |

---

## 4. Boot Strapping 约束（来自 ESP32-C3 Datasheet）

ESP32-C3 有 3 个 strapping pin，在上电/复位时采样电平决定启动模式：

| Strapping Pin | 默认配置 | 启动作用 | 结论 |
|---|---|---|---|
| **GPIO2** | 浮空（Floating）| 建议上拉（抗毛刺）；实际不决定 SPI/下载模式 | 避免用作输出 |
| **GPIO8** | 浮空（Floating）| 必须保持高电平才能正常 SPI Boot；同时控制 ROM 日志打印 | 避免（且板载 RGB LED）|
| **GPIO9** | 内部弱上拉 | HIGH=正常 SPI Boot；LOW=进入下载模式 | 避免（且板载 BOOT 按钮）|

**SPI Boot 模式要求：** GPIO2=1、GPIO8=1、GPIO9=1（默认值即 SPI Boot）。

**结论：GPIO2 / GPIO8 / GPIO9 三个 strapping pin 一律不用于本项目外设。**

---

## 5. 可用 GPIO 候选

基于 ESP32-C3-DevKitM-1 Header Block，可用 GPIO 分类：

| 类别 | GPIO | 说明 |
|---|---|---|
| **自由可分配**（首选）| GPIO0, GPIO1, GPIO3, GPIO10 | 无 strapping / flash / USB / JTAG 职责 |
| **需谨慎**（JTAG/flash 复用）| GPIO4, GPIO5, GPIO6, GPIO7 | 启动时被 ROM 用于 flash/JTAG，启动后释放；用于输出有启动毛刺风险 |
| **禁止** | GPIO2, GPIO8, GPIO9 | strapping |
| **禁止** | GPIO18, GPIO19, GPIO20, GPIO21 | USB / UART console |

本项目需要 4 个 GPIO（IR 发射、IR 接收、I2C SDA、I2C SCL），恰好由 GPIO0/1/3/10 覆盖。详见 [GPIO_MAP.md](GPIO_MAP.md)。

---

## 6. GPIO 驱动电流约束（来自 ESP32-C3 Datasheet v2.4）

| 参数 | 值 |
|---|---|
| 默认驱动电流（GPIO2/GPIO3/MTMS/MTDI）| **10 mA** |
| 默认驱动电流（其余引脚）| **20 mA** |
| 最大拉电流 IOH（PAD_DRIVER=3，VOH≥2.64V）| **40 mA** |
| 最大灌电流 IOL（PAD_DRIVER=3，VOL=0.495V）| **28 mA** |
| 内部上/下拉电阻 | 45 kΩ（典型）|

**含义：**
- 本项目所有 GPIO 负载（BJT 基极 ~7 mA、IR 接收输入、I2C 开漏）均远低于默认 20 mA 驱动能力
- 若选 GPIO3 做 IR 发射（默认 10 mA 驱动），BJT 基极 7 mA 仍在范围内，但建议避免，改用 GPIO0 或 GPIO10
- **绝不直接用 GPIO 驱动 IR LED**（需要 100 mA，远超 40 mA 上限）——必须经 BJT/MOSFET

---

*本文档随硬件选型演进。更换开发板 SKU 必须重走 GPIO_MAP.md 审计并经 Architect + IoT Engineer 评审。*
