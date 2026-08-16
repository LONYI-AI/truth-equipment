# RUNBOOK — Physical AI Agent Platform 运维手册

版本：v0.1（2026-08-16）
状态：**待批准** —— 与 Architecture Audit 联合审批
适用阶段：M0 起（内容随 Milestone 演进）

---

## 1. 快速参考

### 1.1 服务端口速查

| 服务 | 端口 | 绑定 | 访问方式 |
|---|---|---|---|
| Home Assistant | 8123 | host (via Caddy TLS) | `https://ha.yourdomain.com` |
| Ollama | 11434 | 127.0.0.1 | 仅本地 |
| Qdrant REST | 6333 | 127.0.0.1 | 仅本地 |
| Qdrant gRPC | 6334 | 127.0.0.1 | 仅本地 |
| Mosquitto | 1883 | Docker internal | M1B+ 启用 |
| Prometheus | 9090 | 127.0.0.1 | Grafana 数据源 |
| Grafana | 3000 | via Caddy TLS | `https://grafana.yourdomain.com` |
| WireGuard | 51820/UDP | 0.0.0.0 (VPN) | VPN 客户端 |

### 1.2 常用命令

```bash
# ===== Docker =====
docker compose up -d                    # 启动所有服务
docker compose logs -f homeassistant     # 查看 HA 日志
docker compose ps                        # 检查服务状态
docker compose restart <service>         # 重启单个服务
docker compose down                      # 停止所有服务

# ===== Home Assistant =====
curl -s -H "Authorization: Bearer $HA_TOKEN" \
  $HA_URL/api/states/climate.bedroom_ac  # 查询空调状态
curl -s -X POST -H "Authorization: Bearer $HA_TOKEN" \
  -H "Content-Type: application/json" \
  $HA_URL/api/services/climate/turn_on \
  -d '{"entity_id": "climate.bedroom_ac"}'  # 开启空调（测试用）

# ===== Ollama =====
docker exec -it ollama ollama list       # 列出已下载模型
docker exec -it ollama ollama pull qwen3:8b  # 拉取模型
curl http://localhost:11434/api/generate  # 测试推理 API

# ===== Qdrant =====
curl -s http://localhost:6333/collections \
  -H "api-key: $QDRANT_API_KEY"          # 检查 Qdrant 集合

# ===== Agent Runtime =====
python -m agent.cli                       # 启动 Agent CLI
python -m agent.cli --mode interactive    # 交互模式
python -m tests.run_acceptance m1a        # 运行 M1A 验收测试

# ===== ESPHome =====
esphome run src/physical_agent/adapters/esphome/bedroom-ac.yaml  # 编译+烧录
esphome logs bedroom-ac-gateway          # 查看设备日志
esphome clean bedroom-ac-gateway         # 清理编译缓存

# ===== WireGuard =====
wg show                                   # 查看 VPN 状态
sudo wg-quick up wg0                     # 启动 VPN
sudo wg-quick down wg0                   # 停止 VPN

# ===== 备份 =====
bash scripts/backup.sh                   # 手动触发备份
bash scripts/restore.sh <timestamp>      # 从备份恢复

# ===== Kill Switch =====
touch .kill_switch                        # 激活（禁用所有写操作）
rm .kill_switch                           # 取消激活（需人工确认）
```

### 1.3 紧急命令卡

```bash
# ⚠️ 紧急：立即停止所有 Agent 写操作
touch .kill_switch
echo "[$(date)] KILL SWITCH ACTIVATED" >> observability/audit/audit.jsonl

# ⚠️ 紧急：停止所有 Docker 服务
docker compose down

# ⚠️ 紧急：查看最近审计日志（排查问题）
tail -100 observability/audit/audit.jsonl | jq '.'

# ⚠️ 紧急：手动关闭空调（绕过 Agent）
curl -s -X POST -H "Authorization: Bearer $HA_TOKEN" \
  -H "Content-Type: application/json" \
  $HA_URL/api/services/climate/turn_off \
  -d '{"entity_id": "climate.bedroom_ac"}'
```

---

## 2. 日常运维

### 2.1 每日检查（5 分钟）

- [ ] `docker compose ps` — 所有服务 Up + Healthy
- [ ] Grafana Dashboard — 无红色告警
- [ ] Agent 日志 — 无未处理的 ERROR/CRITICAL
- [ ] ESP32-C3 在线（HA 设备页面检查）
- [ ] 审计日志 — 无异常高频操作

**自动化建议**：M1E 后配置每日健康报告邮件。

### 2.2 每周维护（30 分钟）

- [ ] Docker 镜像更新检查（`docker compose pull` 不执行，仅查看）
- [ ] 磁盘使用率检查（`df -h`）
- [ ] 审计日志轮转检查（文件大小、保留策略）
- [ ] 备份完整性验证（最新备份可读）
- [ ] 安全扫描结果 review（依赖漏洞）

### 2.3 每月任务（2 小时）

- [ ] 密钥轮换评估（HA Token、Qdrant Key 等）
- [ ] Ollama 模型更新评估（新版本？性能改进？）
- [ ] HA 版本更新（测试环境先验证 → 生产）
- [ ] ESPHome 固件更新（如有安全修复）
- [ ] 容量规划（向量数据增长、审计日志存储）
- [ ] 文档更新（本 RUNBOOK 反映当前状态）

---

## 3. 故障排查

### 3.1 Agent 无响应

**症状**：CLI 输入无反应或超时

```
诊断步骤：
1. 检查 Agent 进程：ps aux | grep agent
2. 检查 Ollama：curl http://localhost:11434/api/tags
   └─ 若失败 → 重启 Ollama：docker restart ollama
3. 检查 HA 连接：curl $HA_URL/api/
   └─ 若失败 → 检查网络、Token 是否过期
4. 检查审计日志是否有异常错误
5. 检查 Kill Switch 是否误激活：ls -la .kill_switch
```

### 3.2 空调不响应 Agent 指令

**症状**：Agent 显示"已发送指令"但空调无动作

```
诊断步骤：
1. 先用 HA UI 手动控制空调
   └─ 若 UI 也不行 → 问题在 HA/ESPHome/硬件层
   └─ 若 UI 可以 → 问题在 Agent 层

2. 检查 HA 实体状态：
   curl -H "Authorization: Bearer $TOKEN" $HA_URL/api/states/climate.bedroom_ac
   └─ state 应为 "off" 或目标模式

3. 检查 ESPHome 设备日志：
   esphome logs bedroom-ac-gateway
   └─ 查找 IR transmit 相关日志
   └─ 查找 WiFi 断连记录

4. 检查物理层：
   └─ ESP32-C3 LED 是否闪烁（表示收到指令）
   └─ IR 发射管方向是否对准空调接收窗
   └─ 距离是否过远（通常 < 8 米）

5. 检查验证器日志：
   └─ IR 回读是否捕获到发射码
   └─ 声学检测是否听到蜂鸣
```

### 3.3 ESP32-C3 离线

**症状**：HA 显示设备 unavailable

```
诊断步骤：
1. 检查 WiFi：ESP32-C3 是否在同一网络
2. 检查电源：USB 供电是否稳定（电压不足会导致重启循环）
3. 检查 ESPHome 日志（若有串口连接）：
   esphome logs bedroom-ac-gateway --device /dev/ttyUSB0
4. 重启设备：拔电 5 秒后重新上电
5. 若频繁离线：
   └─ 检查 WiFi 信号强度（RSSI > -70dBm）
   └─ 考虑更换 WiFi 信道或添加外置天线
   └─ 检查路由器 DHCP 租约时间
```

### 3.4 LLM 推理极慢或超时

**症状**：Agent 响应时间 > 30s 或 Ollama 报错

```
诊断步骤：
1. 检查 GPU 使用率：nvidia-smi（若使用 NVIDIA 显卡）
   └─ GPU 利用率低 → 模型未加载到 GPU
   └─ VRAM 不足 → 模型回退到 CPU
2. 检查 Ollama 模型加载：
   docker exec -it ollama ollama ps
   └─ qwen3:8b 应出现在列表中
3. 检查系统内存：free -h
   └─ 若可用内存 < 2GB → OOM 风险
4. 测试纯推理延迟：
   time curl http://localhost:11434/api/generate \
     -d '{"model":"qwen3:8b","prompt":"hi","stream":false}'
   └─ 正常应 < 5s（GPU）或 < 15s（CPU）
5. 若持续慢：
   └─ 考虑减小模型（qwen3:4b）或升级硬件
```

### 3.5 审计日志异常

**症状**：日志文件过大、写入失败或格式错误

```
诊断步骤：
1. 检查文件大小：ls -lh observability/audit/audit.jsonl
   └─ > 100MB → 需要轮转
2. 检查磁盘空间：df -h
   └─ 磁盘满 → 清理旧日志或扩容
3. 检查文件权限：ls -la observability/audit/
   └─ 应为 640（owner rw, group r）
4. 检查链式哈希完整性：
   python scripts/verify_audit_chain.py
   └─ 报告断链位置
5. 若文件损坏：
   └─ 从备份恢复
   └─ 记录安全事件
```

### 3.6 Prometheus/Grafana 无法访问

**症状**：监控面板空白或数据缺失

```
诊断步骤：
1. 检查 Prometheus：curl http://localhost:9090/-/healthy
2. 检查数据源配置：Grafana → Configuration → Data Sources
3. 检查 Agent metrics endpoint 是否暴露：
   curl http://localhost:8000/metrics  # 若 Agent 暴露 metrics
4. 检查 Prometheus targets：
   http://localhost:9090/targets
   └─ 所有 target 应为 UP
5. 重启服务：
   docker compose restart prometheus grafana
```

---

## 4. 安全事件响应

### 4.1 检测到可疑操作

**场景**：审计日志显示非预期的 Tier 2 操作序列

```bash
# 1. 立即激活 Kill Switch
touch .kill_switch

# 2. 收集证据
cp observability/audit/audit.jsonl evidence_$(date +%Y%m%d_%H%M%S).jsonl
docker logs homeassistant > ha_logs_$(date +%Y%m%d_%H%M%S).log 2>&1

# 3. 分析影响范围
grep "correlation_id=XXX" evidence_*.jsonl | jq '.'  # 追踪完整操作链

# 4. 评估物理影响
# 检查空调当前状态（可能被恶意操控）
curl -s -H "Authorization: Bearer $HA_TOKEN" $HA_URL/api/states/climate.bedroom_ac

# 5. 如需回滚：手动将设备恢复到安全态
# （见紧急命令卡）

# 6. 记录事件
echo "[$(date)] SECURITY INCIDENT: Suspicious activity detected" \
  >> observability/security_incidents.log
```

### 4.2 密钥疑似泄露

**场景**：Token 出现在日志中或怀疑被窃取

```bash
# 1. 立即轮换受影响密钥
# HA Token: HA UI → Profile → Security → 删除旧 token → 创建新 token
# Qdrant Key: 重新生成并更新 .env 和 compose

# 2. 更新 .env（所有使用该密钥的服务）
vim .env  # 替换新值

# 3. 重启相关服务
docker compose up -d qdrant  # 或其他受影响服务

# 4. 审计密钥泄露前的所有操作
# 检查泄露时间窗口内的审计日志，确认无恶意操作

# 5. 记录轮换事件到 ADR
```

### 4.3 物理安全事件

**场景**：发现硬件被篡改或异常物理访问

```bash
# 1. 激活 Kill Switch
touch .kill_switch

# 2. 物理检查
# 拍照记录当前硬件状态
# 对比 HARDWARE_BOM.md 中的接线图

# 3. 检查固件完整性
esphome compile src/physical_agent/adapters/esphome/bedroom-ac.yaml
# 对比编译出的二进制与设备运行版本（如支持）

# 4. 如确认被篡改：
# - 断开设备电源
# - 烧录已知良好固件
# - 更改 WiFi 密码和 ESPHome API 加密密钥
# - 视为安全事件，全面审查
```

---

## 5. 备份与恢复

### 5.1 自动备份内容

| 数据 | 路径 | 频率 | 保留期 |
|---|---|---|---|
| HA 配置 | ./docker/volumes/ha_config/ | 每日 | 30 天 |
| Qdrant 向量数据（**M1 不启用**，见 ADR-0004）| ./docker/volumes/qdrant_storage/ | 每周 | 4 周 |
| 审计日志 | ./observability/audit/ | 实时（追加）| 90 天 |
| SQLite episodic 记忆 | ./data/memory.db | 每日 | 90 天 |
| ESPHome 固件编译缓存 | ~/.esphome/ | - | （可重建）|

### 5.2 手动备份

```bash
# 创建完整备份
bash scripts/backup.sh --full

# 备份输出示例：
# backup_20260816_013000.tar.gz
# ├── ha_config/
# ├── qdrant_storage/
# ├── audit_logs/
# ├── memory.db
# ├── .env.example  # 注意：不含真实 .env
# └── manifest.json  # 备份元数据（哈希、时间戳）
```

### 5.3 恢复流程

```bash
# 1. 停止所有服务
docker compose down

# 2. 选择备份点
ls backups/
# backup_20260816_013000.tar.gz

# 3. 执行恢复
bash scripts/restore.sh backup_20260816_013000.tar.gz

# 4. 重新填写 .env（备份不包含真实密钥）
cp .env.example .env
vim .env  # 填写真实值

# 5. 启动服务
docker compose up -d

# 6. 验证恢复
bash scripts/health_check.sh
# 应返回全部 OK
```

### 5.4 RTO 目标

| 场景 | RTO 目标 | 实测值（M1E 时标定）|
|---|---|---|
| HA 配置损坏恢复 | < 10 min | _____ |
| 全量灾难恢复 | < 30 min | _____ |
| 单容器故障恢复 | < 2 min | _____ |

---

## 6. 性能调优

### 6.1 LLM 推理优化

| 问题 | 方案 | 效果 |
|---|---|---|
| 首次加载慢 | 预加载模型到内存 | `ollama pull` 后自动常驻 |
| 推理速度慢 | 使用 GPU（vs CPU）| 5-10x 加速 |
| VRAM 不足 | 使用更小量化版本 | qwen3:8b_Q4_K_M (~5GB) |
| 并发请求多 | Ollama 并发参数调整 | OLLAMA_NUM_PARALLEL |

### 6.2 HA 性能优化

| 问题 | 方案 |
|---|---|
| 数据库膨胀 | 配置 recorder keep_days |
| 日志过多 | 调整 logger default 日志级别 |
| WebSocket 延迟 | 确保 LAN 连接（非跨子网）|

### 6.3 Agent 运行时优化

| 问题 | 方案 |
|---|---|
| 内存占用高 | 限制对话历史长度；定期清理 working memory |
| 启动慢 | Lazy load 重组件；预热 LLM 连接 |
| 验证超时 | 调整各验证器 timeout 参数 |

---

## 7. 升级流程

### 7.1 组件升级 Checklist

```
升级前：
□ 当前备份已完成且验证可恢复
□ 新版本 release notes 已阅读
□ 测试环境已验证新版本
□ 回滚方案就绪（知道如何降级）
□ 维护窗口已通知用户（如有协同使用者）

升级中：
□ docker compose pull <service>
□ 备份当前镜像 tag（以防需要回滚）
□ 更新 compose 文件中的版本号
□ docker compose up -d <service>
□ 等待 health check 通过
□ 运行冒烟测试（smoke test）

升级后：
□ 功能验证（关键路径测试）
□ 性能基线对比（无明显退化）
□ 监控确认无异常告警
□ 文档更新（RUNBOOK、CHANGELOG）
□ 如有问题：立即回滚到上一版本
```

### 7.2 回滚命令

```bash
# Docker 镜像回滚
docker compose stop <service>
# 编辑 compose.yml 改回旧版本号
docker compose up -d <service>

# HA 配置回滚
bash scripts/restore.sh <backup_containing_old_config>

# ESPHome 固件回滚
esphome upload <old_firmware_binary>  # 需保留旧编译产物
```

---

## 8. 联系与支持

### 8.1 内部资源

| 资源 | 位置 |
|---|---|
| 架构文档 | docs/ARCHITECTURE.md |
| 安全模型 | docs/SECURITY_MODEL.md |
| 威胁模型 | docs/THREAT_MODEL.md |
| ADR 决策记录 | docs/DECISIONS/ |
| 审计报告 | docs/audits/ |
| 硬件手册 | docs/HARDWARE_BOM.md |
| 验收标准 | docs/ACCEPTANCE_TESTS.md |

### 8.2 外部社区（遇到问题时查阅）

| 组件 | 官方文档 | 社区论坛 |
|---|---|---|
| Home Assistant | https://www.home-assistant.io/docs/ | https://community.home-assistant.io/ |
| ESPHome | https://esphome.io/components/ | https://community.esphome.io/ |
| Ollama | https://github.com/ollama/ollama | GitHub Discussions |
| Qdrant | https://qdrant.tech/documentation/ | Discord |
| LangGraph | https://langchain-ai.github.io/langgraph/ | Discord |
| WireGuard | https://www.wireguard.com/install/ | mailing list |

---

*本文档是活文档。每次故障、变更、演练后必须更新。*
