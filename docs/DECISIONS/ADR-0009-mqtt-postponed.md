# ADR-0009: MQTT Broker 推迟到 Zigbee 设备接入时启用

## Status
Proposed / Pending Owner Approval（原 v0.1 为 Accepted，已撤回，见 P0-9）

## Context
任务书 Phase 0 就部署 Mosquitto MQTT Broker，且配置为：
- `allow_anonymous true`（匿名开放）
- 端口直接映射到宿主机
- 无 password_file、无 ACL

审计评定：**Critical 安全风险**（S1/I-03）。

实际情况：
- M1 阶段（空调闭环）ESPHome 通过 **HA Native API** 通信，不需要 MQTT
- MQTT 在以下场景才需要：
  - Zigbee 设备接入（通过 ZHA 或 Zigbee2MQTT）
  - 多个 ESPHome 设备间通信
  - 第三方 IoT 设备（Tasmota、Sonoff 等）
- 提前部署 MQTT = 提前暴露攻击面，无实际收益

## Decision
**M1 阶段不启用 MQTT Broker。推迟到首个需要 MQTT 的设备接入时再启用，启用即强鉴权。**

时间线：
- **M0-M1E**：Mosquitto 在 docker-compose.core.yml 中注释掉
- **M2+（如需 Zigbee）**：取消注释 + 完整安全配置

启用时的强制配置：
```yaml
# mosquitto.conf（启用时必须使用此配置）
listener 1883
allow_anonymous false
password_file /mosquitto/config/password_file
acl_file /mosquitto/config/acl_file

# 权限示例
# agent_user: 可读写 ac/control 主题（只读 ac/status）
# monitor_user: 只读所有主题
# 禁止匿名订阅 #
```

## Consequences

### 正面影响
- 消除 M1 最大安全风险（匿名 MQTT = 局域网任何人可操控设备）
- 减少运行服务数量，降低维护负担
- 延迟攻击面到真正需要时

### 负面影响 / 风险
- ⚠️ 如 M1 期间临时需要调试 MQTT，需手动启用
  - 缓解：compose 文件中有注释好的配置，取消注释即可
- ⚠️ 未来启用时需完整安全配置（不能忘记）
  - 缓释：本 ADR 记录了强制配置清单；CI 可检查

### 替代方案
- **现在部署但加固**：增加无意义的运维工作 ❌
- **永远不用 MQTT**：不现实，Zigbee 场景必需 💭（届时重新评估）
- **用 HA 内置 MQTT**：功能有限，不如独立 broker 灵活 ❌

## Related ADRs
- THREAT_MODEL.md: I-03 MQTT 匿名开放威胁
- SECURITY_MODEL.md: §5.2 网络隔离
- docker/mosquitto/config/（配置文件预留位置）

## References
- Mosquitto Security: https://mosquitto.org/documentation/authentication-methods/
- MQTT Security Best Practices: https://www.hivemq.com/blog/mqtt-security-fundamentals/

## Date
2026-08-16

## Reviewers
- Reviewed-by-simulated-role: Principal Architect | IoT Engineer | Platform/Security Engineer
- **Note**: 最终由 **Owner** 通过 Architecture Gate。模拟角色审查不等于项目正式批准。
