# THREAT MODEL — Physical AI Agent Platform

版本：v0.1（2026-08-16）
状态：**待批准** —— 与 Architecture Audit 联合审批
方法论：STRIDE + 物理安全扩展

---

## 1. 威胁建模范围

### 1.1 资产清单

| 资产 | 类型 | 敏感度 | 所在层 |
|---|---|---|---|
| Home Assistant Token | 密钥 | 🔴 Critical | Interface |
| MQTT Credentials (M1B+) | 凭据 | 🔴 Critical | Infrastructure |
| Qdrant API Key | 密钥 | 🟠 High | Memory |
| 审计日志 | 完整性证据 | 🟠 High | Audit |
| 用户偏好数据 | 隐私 | 🟡 Medium | Memory |
| 物理设备控制权 | 安全/财产 | 🔴 Critical | Device |
| Agent 推理链 | 可解释性 | 🟡 Medium | Runtime |
| 网络访问权限 | 横向移动 | 🟠 High | Infrastructure |

### 1.2 信任边界

```
┌─ Internet ──────────────────────────────────────────────┐
│   ↓ Caddy (TLS)                                         │
│ ├─ Trust Boundary 1: External → DMZ                    │
│ │   ↓                                                   │
│ ├─ WireGuard VPN ──────────────────────────────────────┤
│ │   ↓                                                   │
│ ├─ Trust Boundary 2: VPN → Internal Network             │
│ │   ↓                                                   │
│ ├─ Docker Internal Network                              │
│ │   ├─ Trust Boundary 3: Container → Container          │
│ │   │   ↓                                               │
│ │   ├─ Agent Runtime ↔ HA API                           │
│ │   │   └─ Trust Boundary 4: Agent → Physical Device    │
│ │   │       ↓                                           │
│ │   ├─ WiFi Network                                     │
│ │       └─ ESP32-C3 → AC (IR)                          │
│ └───────────────────────────────────────────────────────┘
```

---

## 2. STRIDE 威胁分析

### 2.1 Spoofing（身份伪装）

| # | 威胁场景 | 可能性 | 影响 | 风险等级 | 缓解措施 |
|---|---|---|---|---|---|
| S-01 | 攻击者伪造 HA Token 调用 API | 低 | 🔴 Critical | **高** | Token 存储 .env + 文件权限 600；HA IP 白名单；Token 最小权限；定期轮换 |
| S-02 | 攻击者伪造 Agent 身份发送指令 | 中 | 🟠 High | **高** | 内部服务间 mTLS 或 shared secret；Agent session token 签名验证 |
| S-03 | 攻击者伪造物理 IR 信号操控空调 | 低 | 🟡 Medium | **中** | IR 回读验证：Agent 发射的码必须被接收管捕获匹配；异常频率检测 |

### 2.2 Tampering（数据篡改）

| # | 威胁场景 | 可能性 | 影响 | 风险等级 | 缓解措施 |
|---|---|---|---|---|---|
| T-01 | 攻击者篡改审计日志掩盖痕迹 | 低 | 🔴 Critical | **高** | Append-only 文件属性（`chattr +a`）；SHA-256 链式哈希；HMAC signed checkpoint（签名密钥与 Agent Runtime 隔离）；周期性离机副本。**语义：tamper-evident，非 tamper-proof** |
| T-02 | 攻击者修改 Docker 镜像注入后门 | 低 | 🔴 Critical | **高** | 镜像签名验证（docker content trust）；pin 版本；定期扫描漏洞 |
| T-03 | 攻击者修改 ESPHome 固件改变行为 | 极低 | 🟠 High | **中** | 固件二进制哈希校验；OTA 签名（ESPHome 原生支持）；不使用未知固件 |
| T-04 | LLM 输出被中间人篡改（MITM） | 极低 | 🟠 High | **低** | Ollama 绑定 127.0.0.1；内部网络通信 |

### 2.3 Repudiation（否认行为）

| # | 威胁场景 | 可能性 | 影响 | 风险等级 | 缓解措施 |
|---|---|---|---|---|---|
| R-01 | 操作者否认执行了某物理动作 | N/A（内部威胁） | 🟠 High | **中** | 全链路审计日志 + correlation ID；每条记录含时间戳、操作者身份、完整参数 |
| R-02 | Agent 否认做出了某决策 | N/A（系统行为） | 🟡 Medium | **低** | 推理链落盘（LLM think mode）；决策依据可追溯 |

### 2.4 Information Disclosure（信息泄露）

| # | 威胁场景 | 可能性 | 影响 | 风险等级 | 缓解措施 |
|---|---|---|---|---|---|
| I-01 | HA Token / 密钥泄露到 Git | 中（人为错误） | 🔴 Critical | **高** | `.gitignore` 严格规则；pre-commit gitleaks 扫描；CI secret detection |
| I-02 | Qdrant 无鉴权暴露向量数据 | 中（配置错误） | 🟠 High | **高** | 强制 API Key；绑定 127.0.0.1；Chroma 因 CVE 弃用改 Qdrant（ADR-0004）|
| I-03 | MQTT 匿名开放，泄露设备状态 | 高（任务书原配置） | 🔴 Critical | **高** | `allow_anonymous false` + password_file + ACL；M1 不启用（ADR-0009）|
| I-04 | 审计日志含敏感信息被读取 | 低 | 🟡 Medium | **低** | 日志脱敏规则；文件权限 640；Loki 访问控制 |
| I-05 | ESPHome fallback AP 弱密码被利用 | 中 | 🟠 High | **中** | 禁用 fallback AP 或使用强随机密码；不在 Git 存明文密码 |

### 2.5 Denial of Service（拒绝服务）

| # | 威胁场景 | 可能性 | 影响 | 风险等级 | 缓解措施 |
|---|---|---|---|---|---|
| D-01 | 大量请求淹没 Agent 导致频繁物理动作 | 中 | 🟠 High | **高** | 速率限制（同操作 ≤3次/分钟）；Kill Switch；队列缓冲 |
| D-02 | 攻击者 DoS HA 导致无法控制设备 | 低 | 🟡 Medium | **中** | HA 独立运行；Agent 有降级模式（离线缓存最后已知状态）|
| D-03 | WiFi 干扰导致 ESP32-C3 离线 | 低 | 🟡 Medium | **中** | 本地策略缓存（ESPHome 支持）；断连告警；手动控制回退路径 |
| D-04 | 磁盘满导致审计日志写入失败 | 低 | 🟠 High | **中** | 磁盘监控告警（Prometheus）；日志轮转；保留策略 |

### 2.6 Elevation of Privilege（权限提升）

| # | 威胁场景 | 可能性 | 影响 | 风险等级 | 缓解措施 |
|---|---|---|---|---|---|
| E-01 | 从 Tier 0 只读操作提升到 Tier 2 写操作 | 低 | 🔴 Critical | **高** | Policy Gate 强制分层；工具元数据声明 risk_tier；Gateway 层强制检查 |
| E-02 | 容器逃逸获得主机权限 | 极低 | 🔴 Critical | **高** | 不使用 `privileged: true`（除非必需）；`cap_drop: ALL`；`no-new-privileges`；只读根文件系统 |
| E-03 | 通过 ADB over TCP 控制手机（Phase 3） | 未来 | 🔴 Critical | **未来** | Phase 3 前必须完成独立安全评审；ADB 仅在隔离网络；专用低权限用户 |

---

## 3. 物理安全威胁（本项目特有）

### 3.1 LLM 幻觉导致物理动作

| # | 场景 | 可能性 | 影响 | 缓解 |
|---|---|---|---|---|
| P-01 | LLM 输出越界参数（如温度 = 100℃） | 中（模型缺陷） | 🟡 Medium | 参数边界硬校验（Schema + Gateway 双重检查） |
| P-02 | LLM 幻觉调用不存在的工具或错误操作 | 低 | 🟠 High | Tool schema 白名单；未知工具直接拒绝 |
| P-03 | LLM 被提示注入攻击诱导执行恶意操作 | 低 | 🔴 Critical | **高** | 输入消毒；用户意图分类器；敏感操作强制人工确认 |

**核心防御**：
> **LLM 的输出永远不可信。所有物理动作必须经过确定性（非 LLM）的 Policy Gate 校验。**

### 3.2 单向控制的验证失败

| # | 场景 | 可能性 | 影响 | 缓解 |
|---|---|---|---|---|
| P-04 | IR 发射但空调未响应（障碍物/电池/角度） | 中 | 🟡 Medium | 多信号验证（声学 + IR 回读 + 温度趋势）；失败自动重试 + 升级 |
| P-05 | IR 信号干扰邻近设备 | 极低 | 🟡 Medium | 定向发射（LED 加反射罩）；发射功率最小化；频率隔离 |

### 3.3 硬件物理攻击

| # | 场景 | 可能性 | 影响 | 缓解 |
|---|---|---|---|---|
| P-06 | 攻击者物理接触 ESP32-C3 并提取密钥/重刷固件 | 极低（需物理接近） | 🟠 High | 设备放置在受限区域；固件加密（ESP32 Secure Boot）；不存储长期密钥在设备上 |
| P-07 | 攻击者物理破坏传感器导致错误读数 | 极低 | 🟡 Medium | 传感器数据异常检测（突变、超范围）；多传感器交叉验证 |

---

## 4. 威胁-缓解矩阵（优先级排序）

### Critical（必须 M0-M1E 解决）

| 威胁 | 缓解措施 | 负责人 | Milestone |
|---|---|---|---|
| **I-01** 密钥泄露 Git | pre-commit + CI 扫描 + .gitignore | Platform/Security | M0 |
| **I-03** MQTT 匿名开放 | 禁用或强鉴权 + ACL | IoT Engineer | M0（配置就绪）|
| **S-08** LLM 幻觉→物理动作 | Policy Gate + 参数校验 + Tier 分级 | Agent Runtime + QA | M1A |
| **E-01** 权限提升 | 工具 risk_tier 元数据 + Gateway 强制检查 | Agent Runtime | M1A |
| **T-01** 审计日志篡改 | SHA-256 链 + signed checkpoint + 离机副本（tamper-evident）| Platform/Security | M1A |

### High（M1E 前解决）

| 威胁 | 缓解措施 | 负责人 | Milestone |
|---|---|---|---|
| **I-02** Qdrant 无鉴权 | API Key + 绑定 127.0.0.1 | Platform/Security | M0 |
| **D-01** Agent 被 DoS | 速率限制 + Kill Switch | Agent Runtime | M1A |
| **P-01/P-03** LLM 参数越界/提示注入 | Schema 校验 + 输入消毒 | Agent Runtime | M1A |
| **P-04** IR 发射未响应 | 多信号验证子系统 | Agent Runtime + IoT | M1D |
| **E-02** 容器逃逸 | 最小权限容器配置 | Platform/DevOps | M0 |

### Medium（持续改进）

| 威胁 | 缓解措施 | 负责人 | Milestone |
|---|---|---|---|
| **S-03** IR 信号伪造 | IR 回读验证 | IoT Engineer | M1C |
| **D-02/D-03** HA/ESP 离线 | 降级模式 + 断连告警 | 全体 | M1E |
| **I-05** ESPHome AP 弱密码 | 禁用或强随机密码 | IoT Engineer | M1C |

---

## 5. 攻击面分析

### 5.1 当前攻击面（M1 范围）

```
                    攻击面大小
                       │
                       ▼
┌─────────────────────────────────────────────────┐
│ Internet                                        │ ← Caddy TLS (唯一入口)
│  ├─ HA Dashboard (8123)                         │ ← 2FA (M1E+)
│  ├─ Grafana (3000)                              │ ← Read-only for monitor
│  └─ WireGuard (51820/UDP)                      │ ← 公钥认证
│                                                 │
│ Internal Network                                │
│  ├─ Ollama (11434)                             │ ← 127.0.0.1 only ✅
│  ├─ Qdrant (6333/6334)                         │ ← 127.0.0.1 only ✅
│  ├─ Mosquitto (1883)                            │ ← Disabled in M1 ✅
│  ├─ HA API (8123)                               │ ← Token auth + IP restrict
│  └─ Agent Runtime (internal)                   │ ← Service-to-service auth
│                                                 │
│ IoT Network                                      │
│  └─ ESP32-C3 (WiFi)                            │ ← WPA2/WPA3 + ESPHome API encryption
│      ├─ IR Transmitter → AC                     │ ← 单向，不可逆
│      ├─ IR Receiver ← Remote                   │ ← 只读验证
│      └─ SHT31 Sensor                            │ ← 只读
└─────────────────────────────────────────────────┘
```

### 5.2 攻击面缩减目标

| 当前状态 | 目标状态 | 措施 |
|---|---|---|
| HA `privileged: true` | 显式 device mapping | M1B 配置优化 |
| Qdrant 对外暴露 | 仅 127.0.0.1 | M0 compose 修正 |
| MQTT 开放且匿名 | 禁用（M1）/ 鉴权+ACL（M2）| M0/M2 |
| Agent 直接调 HA API | 经 Tool Gateway | M1A 实现 |
| 无 Kill Switch | 文件开关 + 自动触发 | M1A 实现 |
| 审计日志可修改 | SHA-256 链 + signed checkpoint（tamper-evident）| M1A 实现 |

---

## 6. 威胁监控与检测

### 6.1 安全事件指标（Prometheus）

```yaml
# 关键告警规则
groups:
  - name: security_alerts
    rules:
      - alert: HighRateTier2Operations
        expr: rate(audit_log_operations{tier="2"}[5m]) > 0.5
        for: 2m
        labels:
          severity: warning
        annotations:
          summary: "高频 Tier 2 操作检测"

      - alert: VerificationFailureRateHigh
        expr: |
          rate(audit_log_verifications{verdict="failed"}[10m])
          /
          rate(audit_log_verifications[10m]) > 0.2
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "物理验证失败率超过 20%"

      - alert: UnauthorizedAccessAttempt
        expr: rate(ha_api_unauthorized_errors[1m]) > 0
        for: 1m
        labels:
          severity: critical
```

### 6.2 异常行为基线

建立正常行为基线后检测偏离：
- 每日操作次数分布
- 典型时间段（如夜间应无操作）
- 温度调整幅度分布
- 工具调用序列模式

---

## 7. 渗透测试计划

| 阶段 | 测试内容 | 负责人 | 时间 |
|---|---|---|---|
| M1A | 模拟环境红队测试（LLM 注入、参数越界、权限提升）| QA/Red-Team | M1A 结束前 |
| M1B | HA 集成安全测试（Token 权限、API 滥用）| Security Engineer | M1B |
| M1D | 物理层测试（IR 干扰、传感器欺骗）| IoT + Red-Team | M1D |
| M1E | 全面渗透测试 + 应急演练 | 全体 | M1E |
| M2+ | 季度自动化渗透测试 | Red-Team | 每季度 |

---

*本文档是活文档。每次安全事件后必须复盘更新。新组件接入前必须完成对应威胁建模。*
