# ADR-0002: ESP32-C3 替代 ESP8266 作为 IR 网关

## Status
Proposed / Pending Owner Approval（原 v0.1 为 Accepted，已撤回，见 P0-9）

## Context
任务书原定使用 ESP8266 D1 Mini 作为红外网关主控。审计发现：
1. ESP8266 已进入维护期（Espressif 官方声明），不再获得新功能
2. ESP8266 不支持 ESP-IDF 框架（ESPHome 2026.1+ 默认框架），部分新组件不可用
3. ESP32-C3 同价位（¥20-30）但性能、安全性、功能全面领先
4. 社区反馈 ESP8266 上 IR 发射时序不稳定（WiFi 中断干扰）

## Decision
**使用 ESP32-C3 作为红外网关主控芯片，ESP8266 仅作为备用/学习用途。**

硬件配置：
- 主控：ESP32-C3（合宙或乐鑫 DevKitC）
- IR 发射：TSAL6200 + S8050 低边开关电路（修正后的正确拓扑）
- IR 接收：TSOP38238（新增，用于物理验证通道）
- 温湿度：SHT31（I2C，替代 DHT22）

固件要求：
- ESPHome 版本 ≥ 2024.6.x（推荐 2026.4.x+）
- 框架：ESP-IDF（默认，不要切换到 Arduino）
- 使用 `remote_transmitter` + `remote_receiver` 组件
- Climate 平台根据空调品牌选择（见 HARDWARE_BOM §5.2）

## Consequences

### 正面影响
- RMT hardware transmitter（硬件定时器）避免 WiFi 干扰 IR 时序问题
- 支持 ESP-IDF 新特性（signed OTA、蓝牙 proxy 等）
- 更强的安全特性（Secure Boot、Flash Encryption）
- 更充足的 GPIO 和内存（相比 ESP8266）
- 长期支持保障（ESP32 系列是乐鑫主力产品线）

### 负面影响 / 风险
- ⚠️ ESP32-C3 的 GPIO 编号与 ESP8266 不同，需注意接线图
- ⚠️ 部分 ESPHome 组件可能尚不支持 ESP-IDF（如 `heatpumpir`、`midea`）
  - 缓解：使用通用 `climate_ir` + 手动码表，或社区 BC7215 方案
- ⚠️ 功耗略高于 ESP8266（但对常供电网关无影响）

### 替代方案
- **继续用 ESP8266**：省钱但不值得承担技术债务 ❌
- **ESP32-S3**：性能更强但价格翻倍，对简单 IR 网关过剩 ❌
- **购买成品 IR 网关**（如极联小π）：省去焊接但定制性差，价格 ¥50+ 💰（可选备选）

## Related ADRs
- ADR-0001: HA 抽象层（ESP32-C3 通过 HA Integration 接入）
- ADR-0006: 物理验证子系统（IR 接收管是验证通道关键件）

## References
- ESPHome Changelog 2026.1.0: https://esphome.io/changelog/2026.1.0/
- ESP32-C3 Datasheet: https://www.espressif.com/sites/default/files/documentation/esp32-c3_datasheet_en.pdf
- 社区 IR 可靠性讨论: http://gist.github.com/nay-kang/b6804827a131a2aa52269659e9e04931

## Date
2026-08-16

## Reviewers
- Reviewed-by-simulated-role: Principal Architect | IoT Engineer
- **Note**: 最终由 **Owner** 通过 Architecture Gate。模拟角色审查不等于项目正式批准。
