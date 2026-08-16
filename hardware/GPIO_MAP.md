# GPIO_MAP — ESP32-C3-DevKitM-1 引脚分配

版本：v0.2（2026-08-16，Architecture Audit v0.2）
状态：**Proposed / Pending Owner Approval**
前置文档：[BOARD_SELECTION.md](BOARD_SELECTION.md)

---

## 1. 引脚分配总表

| 功能 | GPIO | 方向 | 电气要求 | 负载 | 依据 |
|---|---|---|---|---|---|
| **IR 发射使能**（remote_transmitter RMT）| **GPIO0** | 输出 | 3.3V 逻辑 → 1kΩ 基极限流 → 2N2222A 基极 | 源电流 ≈ 2.6 mA | 自由 GPIO，无 strapping/flash/USB 职责 |
| **IR 接收**（remote_receiver）| **GPIO3** | 输入 | TSOP38238 OUT（开漏低有效，内部 30kΩ 上拉）| 灌电流 ≈ 0 | 自由 GPIO；输入模式默认 10mA 驱动上限无影响 |
| **SHT31 SDA**（I2C）| **GPIO1** | 双向开漏 | 软件 I2C，需 4.7kΩ 上拉至 3.3V | 开漏灌电流 < 3 mA | 自由 GPIO |
| **SHT31 SCL**（I2C）| **GPIO10** | 输出开漏 | 软件 I2C，需 4.7kΩ 上拉至 3.3V | 开漏灌电流 < 3 mA | 自由 GPIO |

**供电分配：**

| 电源轨 | 来源 | 用途 |
|---|---|---|
| 5V | 开发板 5V 排针（来自 USB）| IR LED 阳极供电（经限流电阻）|
| 3V3 | 开发板 3V3 排针 | TSOP38238 VS、SHT31 VCC、I2C 上拉 |
| GND | 开发板 GND 排针 | 所有元件共地 |

---

## 2. 为什么避开这些引脚

| GPIO | 冲突来源 | 后果 |
|---|---|---|
| **GPIO2** | Strapping pin（浮空默认，建议上拉）| 上电时被采样决定启动模式；若被 IR 发射电路拉低 → 启动异常 |
| **GPIO8** | Strapping pin + 板载 WS2812 RGB LED | 启动时必须为高；LED 会在启动/复位时闪烁干扰 IR 接收 |
| **GPIO9** | Strapping pin + 板载 BOOT 按钮（外部下拉）| HIGH 才正常启动；BOOT 按钮按下会拉低 → 误进下载模式 |
| **GPIO18/19** | 原生 USB Serial/JTAG（USB_D-/D+）| 占用会破坏 USB 调试/烧录 |
| **GPIO20/21** | UART0 console（U0RXD/U0TXD）| 占用会丢失串口日志/烧录通道 |
| **GPIO4/5/6/7** | 启动时 ROM 用于 flash SPI / JTAG（MTMS/MTDI/MTCK/MTDO）| 输出引脚在启动瞬间可能产生毛刺，误触发外设 |

---

## 3. GPIO0 细节（IR 发射）

- **启动状态**：GPIO0 非 strapping pin，启动时无特殊功能，可安全用作输出
- **注意**：GPIO0 同时是 ADC1_CH0 和 XTAL_32K_P 复用功能——本项目未用 32k 晶振，无冲突
- **驱动能力**：默认 20 mA 驱动，基极电流仅 ~2.6 mA，余量充足
- **ESPHome 映射**：`remote_transmitter: pin: GPIO0`（使用 RMT 硬件通道，非软件 bit-bang）

## 4. GPIO3 细节（IR 接收）

- **启动状态**：GPIO3 非 strapping pin
- **注意**：GPIO3 同时是 ADC1_CH3；ESPHome 默认该引脚驱动电流为 10 mA，但作为输入无影响
- **TSOP38238 输出接口**：开漏、低有效、内部 30kΩ 上拉（见 IR_GATEWAY_SCHEMATIC.md）；GPIO3 配置为输入（可开启内部上拉做冗余，但非必需）
- **ESPHome 映射**：`remote_receiver: pin: GPIO3`，`dump: all`（用于学习/验证）

## 5. I2C 细节（GPIO1 + GPIO10，软件 I2C）

- **为何不用默认 I2C 引脚**：ESP32-C3 的"默认 I2C SDA=GPIO8 / SCL=GPIO9"恰好是两个被禁止的 strapping pin（GPIO8 还有板载 LED）。**必须改用软件 I2C 到自由引脚**。
- **上拉电阻**：SHT31 模块通常自带 4.7kΩ 上拉；若模块未带，需外接 4.7kΩ 上拉至 3.3V（详见 ELECTRICAL_REVIEW_CHECKLIST.md）
- **ESPHome 映射**：
  ```yaml
  i2c:
    sda: GPIO1
    scl: GPIO10
    frequency: 100kHz
  ```

---

## 6. 变更控制

| 规则 | 说明 |
|---|---|
| 换板即复审 | 更换开发板 SKU → 必须重走本文件 + BOARD_SELECTION.md 审计 |
| 换引脚即复审 | 任何引脚变更 → 检查 strapping / flash / USB / JTAG / 板载外设冲突 |
| 上电验证 | 新接线必须做"上电 10 次复位测试"确认稳定进入 SPI Boot（见 ELECTRICAL_REVIEW_CHECKLIST.md）|

---

*本文档的 GPIO 分配绑定到 ESP32-C3-DevKitM-1 具体 SKU，并依据 ESP32-C3 Datasheet v2.4 与 DevKitM-1 用户指南。*
