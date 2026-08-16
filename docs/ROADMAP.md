# ROADMAP — Physical AI Agent Platform

版本：v0.1（2026-08-16）
状态：**待批准** —— 与 Architecture Audit 联合审批
原则：**未通过当前阶段验收，不得进入下一阶段**

---

## 1. 里程碑总览

```
M0 ──→ M1A ──→ M1B ──→ M1C ──→ M1D ──→ M1E ──┬──→ M2 (视觉感知)
 │      │      │      │      │      │          ├──→ M3 (电脑/手机)
骨架   模拟    HA     物理    验证    加固        └──→ M4 (多设备协同)
CI     闭环    集成    IR     系统    安全
secrets                                                (冻结至 M1E 通过)
dev env
```

### 时间估算（单人 + Agent 协作，不含等待硬件/物流时间）

| Milestone | 内容 | 预计工期 | 前置依赖 |
|---|---|---|---|
| **M0** | 工程骨架 + CI + secrets + dev environment | 2-3 天 | 无 |
| **M1A** | 全模拟 AC 闭环 | 3-4 天 | M0 |
| **M1B** | Home Assistant 真实集成 | 2 天 | M0 |
| **M1C** | ESPHome + 物理红外空调控制 | 2-3 天（含等快递）| M1B |
| **M1D** | 物理验证子系统上线 | 3 天 | M1C |
| **M1E** | 安全加固 + 可观测性 + 回滚演练 | 3-4 天 | M1D |
| **M1 全部** | **Phase 1 完整闭环** | **~15-20 天** | - |
| **M2** | 视觉感知系统（Frigate + VLM）| 5-7 天 | M1E ✅ |
| **M3** | 电脑与手机操控 | 5-7 天 | M1E ✅ |
| **M4** | 多设备协同与场景自动化 | 持续迭代 | M2+M3 |

---

## 2. Milestone 0：工程基础设施

**目标**：建立可重复、可审计、安全的开发基础

### 2.1 任务清单

| # | 任务 | 产出 | 验收标准 |
|---|---|---|---|
| M0-01 | 初始化 Git 仓库结构 | 目录树 + .gitignore | `git status` 无异常文件 |
| M0-02 | 配置 pre-commit hooks | .pre-commit-config.yaml | `gitleaks` 扫描通过；secret pattern 检查启用 |
| M0-03 | 编写 CI pipeline | .github/workflows/ci.yml | PR 自动触发：lint → test → secret-scan → yaml-lint |
| M0-04 | 建立 secrets 机制 | .env.example + scripts/generate_secrets.sh | `.env` 被 gitignore；生成脚本可用 |
| M0-05 | Docker Compose 栈草案 | compose.yaml | HA + Ollama + Qdrant + Mosquitto（注释掉）；版本全 pin |
| M0-06 | Mosquitto 加固配置 | docker/mosquitto/config/* | 匿名关闭；password_file 示例；ACL 示例 |
| M0-07 | Python 项目初始化 | pyproject.toml + requirements.txt | ruff + pytest + mypy 配置就绪 |
| M0-08 | ADR-0000 模板 + ADR-0001~0009 | docs/DECISIONS/ | 每个 ADR 有 Status、Context、Decision、Consequences |
| M0-09 | 架构评审会议 | 会议纪要 | Architect + IoT + Security 三方签字确认 |

### 2.2 DoD（Definition of Done）

- [ ] CI pipeline 绿灯（main 分支）
- [ ] `git grep` 扫描无硬编码密钥
- [ ] 所有 ADR 已创建并 review 通过
- [ ] Docker compose 栈可 `docker compose up -d` 启动（服务健康检查通过）
- [ ] README.md + AGENTS.md 已更新反映 M0 状态

### 2.3 门禁放行条件

**守门人**：Platform/DevOps Engineer + QA Engineer

**放行检查表**：
- [ ] CI 全绿且已合并到 main
- [ ] Secrets 机制验证：`.env.example` 可生成工作配置
- [ ] 架构评审与 Owner Gate 状态已记录在正式文档和 Git history
- [ ] 无 P0/P1 级安全问题遗留

---

## 3. Milestone 1A：全模拟闭环

**目标**：在无真实设备的情况下，验证完整 Agent 循环逻辑正确性

### 3.1 任务清单

| # | 任务 | 产出 | 验收标准 |
|---|---|---|---|
| M1A-01 | 实现 Fake HA Server | tests/fake_ha_server.py | 可启动，返回预设 fixture 数据 |
| M1A-02 | 实现 Mock LLM（可选 Ollama）| tests/mock_llm.py | 返回预定义 tool_call 或文本 |
| M1A-03 | LangGraph State Machine 骨架 | src/physical_agent/runtime/graph.py | State 定义完整；节点函数签名正确 |
| M1A-04 | 实现 Perceive 节点 | src/physical_agent/runtime/nodes/perceive.py | 从 Fake HA 读取状态并更新 world_state |
| M1A-05 | 实现 Reason + Plan 节点 | src/physical_agent/runtime/nodes/reason.py | LLM 输出解析为结构化 Plan |
| M1A-06 | 实现 Policy Gate | src/physical_agent/policy/__init__.py | Tier 分级；参数校验；速率限制；Tier 2 阻塞 |
| M1A-07 | 实现 Tool Gateway | src/physical_agent/safety/__init__.py | Schema 校验；审计埋点；HA client 封装 |
| M1A-08 | 实现 Execute 节点 | src/physical_agent/runtime/nodes/execute.py | 经 Gateway 调用工具；错误处理 |
| M1A-09 | 实现模拟验证器 | src/physical_agent/verification/mock_verifier.py | 返回预设 VerificationResult |
| M1A-10 | 实现 Memory 子系统（SQLite + Qdrant stub）| src/physical_agent/memory/__init__.py | Episodic 写入 SQLite；Semantic 写入 Qdrant（或 mock）|
| M1A-11 | 实现 Audit 子系统 | src/physical_agent/audit/__init__.py | JSONL append-only；correlation ID；链式哈希 |
| M1A-12 | 实现 Kill Switch | src/physical_agent/policy/kill_switch.py | 文件开关；自动触发条件 |
| M1A-13 | 单元测试（≥20 个）| tests/test_*.py | 核心逻辑覆盖 |
| M1A-14 | 集成测试：正常流程 E2E | tests/integration/test_normal_flow.py | "开空调 26 度"完整流程通过 |
| M1A-15 | 故障注入测试 | tests/integration/test_failure_injection.py | IR 未命中、验证超时、LLM 幻觉参数越界、Policy 拒绝 |

### 3.2 关键测试用例

```python
# 正常流程
def test_open_ac_normal_flow():
    """用户指令 → perceive → reason → plan → policy(approve) → execute → verify(success) → memory → END"""

# 参数越界
def test_llm_hallucination_out_of_bounds():
    """LLM 输出 temperature=100 → Policy Gate 拒绝 → 不执行"""

# 验证失败重试
def test_verification_failure_retry():
    """首次 verify failed → retry → 第二次 success → 继续"""

# 验证失败升级
def test_verification_failure_escalate():
    """连续 2 次 verify failed → compensate(回滚) → escalate(通知管理员)"""

# Tier 2 人工确认
def test_tier2_requires_human_approval():
    """turn_on_ac 是 Tier 2 → 阻塞 → 模拟人工批准 → 执行"""

# Kill Switch
def test_kill_switch_blocks_writes():
    """激活 kill switch → Tier 1 操作被拒绝"""

# 速率限制
def test_rate_limit_exceeded():
    """同操作 4 次/分钟 → 第 4 次被拒绝"""
```

### 3.3 DoD

- [ ] ≥20 个单元测试通过（coverage ≥80%）
- [ ] 5 个 E2E 集成测试通过（正常 + 4 种故障注入）
- [ ] Audit log 格式正确，每条记录有 correlation ID
- [ ] Policy Gate 正确拦截所有越界请求
- [ ] Kill Switch 可正常激活/取消
- [ ] 无 `asyncio.run()` 在 async 上下文中的反模式

### 3.4 门禁放行

**守门人**：QA Engineer

**放行条件**：
- [ ] 全部测试通过（pytest）
- [ ] 覆盖率报告达标
- [ ] 故障注入测试全部通过
- [ ] Code Review 完成（至少 Architect + Agent Runtime Engineer）

---

## 4. Milestone 1B：Home Assistant 真实集成

**目标**：Agent 连接真实 HA，只读验证通过后开放受控写权限

### 4.1 任务清单

| # | 任务 | 产出 | 验收标准 |
|---|---|---|---|
| M1B-01 | 部署 HA Docker 容器（生产服务器）| compose.yaml 更新 | HA 可通过 `http://server:8123` 访问 |
| M1B-02 | 创建 HA 专用 Integration Token | 文档记录步骤 | Token 权限最小化（仅白名单 entity）|
| M1B-03 | 替换 Fake HA 为真实 HA Client | src/physical_agent/adapters/ha_client.py | WebSocket 状态订阅 + REST API 调用 |
| M1B-04 | 只读 Smoke Test | tests/integration/test_ha_readonly.py | 能读取实体状态、传感器数值 |
| M1B-05 | 受控写测试（手动确认每次）| tests/integration/test_ha_controlled_write.py | 经人工确认后可成功调用 climate.turn_on |
| M1B-06 | Token 权限审计脚本 | scripts/audit_token_permissions.py | 列出 token 可访问的全部 entity |
| M1B-07 | MQTT Broker 启动（可选，见 ADR-0009）| compose.yaml 更新 | Mosquitto 运行且鉴权生效 |

### 4.2 DoD

- [ ] HA 容器稳定运行（7 天无崩溃）
- [ ] 只读集成测试通过
- [ ] 受控写测试通过（≥10 次，成功率 100%）
- [ ] Token 权限审计报告无越权
- [ ] 审计日志记录了所有 HA API 调用

### 4.3 门禁放行

**守门人**：IoT Engineer + QA Engineer

---

## 5. Milestone 1C：ESPHome + 物理红外控制

**目标**：硬件组装、固件刷写、IR 发射控制真实空调

### 5.1 任务清单

| # | 任务 | 产出 | 验收标准 |
|---|---|---|---|
| M1C-01 | 硬件接收与检验 | 开箱照片 + 元件清单 | H1-H8 全部到位，无缺损坏 |
| M1C-02 | 面包板插接电路 | 接线图照片 | 按 `hardware/schematic/IR_GATEWAY_SCHEMATIC.md` 接线完成 |
| M1C-03 | ESPHome 固件编写 | src/physical_agent/adapters/esphome/bedroom-ac.yaml | 含 IR transmitter + SHT31 + IR receiver |
| M1C-04 | 固件编译（本地或云端）| 编译日志 | `esphome compile` 成功，无 error/warning |
| M1C-05 | 固件烧录 | 设备串口日志 | ESP32-C3 成功连接 WiFi，出现在 HA 中 |
| M1C-06 | HA 自动发现实体 | HA UI 截图 | climate.bedroom_ac + sensor.bedroom_temperature 出现 |
| M1C-07 | IR 学习（如需要）| 学习到的码值 | 如果品牌 platform 不支持，手动学习遥控器码 |
| M1C-08 | HA UI 手动控制测试 | 测试记录 | HA UI 操作空调，记录成功率（目标 ≥95%，待实测，附样本量+CI）|
| M1C-09 | Agent 控制（首次物理动作）| audit log + 视频/照片 | Agent 成功发送"开启空调"指令，空调响应 |
| M1C-10 | 安全检查 | 检查清单 | fallback AP 密码强随机；无明文密码进 Git |

### 5.2 DoD

- [ ] 硬件组装完成并通过照片记录
- [ ] 固件编译烧录成功，设备在线
- [ ] HA 实体正常显示并可手动控制
- [ ] HA UI 控制成功率 ≥95%（20 次样本，目标值，待实测）
- [ ] Agent 至少成功执行 1 次物理写操作
- [ ] 安全检查清单全部通过

### 5.3 门禁放行

**守门人**：IoT Engineer + QA Engineer + Red-Team（安全抽查）

---

## 6. Milestone 1D：物理验证子系统

**目标**：多信号验证机制上线，准确率标定

### 6.1 任务清单

| # | 任务 | 产出 | 验收标准 |
|---|---|---|---|
| M1D-01 | IR 回读验证器实现 | src/physical_agent/verification/ir_readback.py | TSOP38238 捕获的码与发射码匹配判定 |
| M1D-02 | 声学验证器实现（如有麦克风）| src/physical_agent/verification/acoustic.py | 检测空调蜂鸣特征频率 |
| M1D-03 | 温度趋势验证器实现 | src/physical_agent/verification/temp_trend.py | SHT31 连续采样，检测温度变化方向 |
| M1D-04 | 多信号融合算法 | src/physical_agent/verification/fusion.py | 加权投票输出 VerificationResult |
| M1D-05 | 验证器标定测试 | tests/integration/test_verification_calibration.py | 各信号源独立准确率测试 |
| M1D-06 | 对抗测试 | tests/integration/test_verification_adversarial.py | 故意误导验证器的攻击测试 |

### 6.2 标定目标

> **数字纪律（对应 P0-4）**：以下为**目标阈值**，非已测得事实。实测结果必须附 sample size、conditions、FPR、FNR、CI。

| 指标 | 目标值（待实测）| 测试方法 |
|---|---|---|
| IR 回读真阳性率（V2）| ≥99%（待实测）| 发射 N 次统计 + CI |
| IR 回读假阳性率（V2）| ≤1%（待实测）| 无发射时监听统计 + CI |
| 声学检测真阳性率（V3，如有硬件）| ≥90%（待实测）| 开机蜂鸣统计 + CI |
| 温度趋势检测灵敏度（V4）| 检测到明确温度变化（阈值实测标定）| 人为改变环境温度测试 |
| 融合结论准确率 | ≥95%（待实测）| 操作 + 干扰测试 + CI |

### 6.3 DoD

- [ ] ≥3 个验证器实装（IR 回读必须，其余按硬件情况）
- [ ] 标定测试达到目标值
- [ ] 对抗测试通过（假阳性 ≤5%，无法被简单欺骗）
- [ ] 验证结果写入审计日志

### 6.4 门禁放行

**守门人**：IoT Engineer + QA Engineer + Red-Team

---

## 7. Milestone 1E：安全加固与可观测性

**目标**：生产级安全、监控、备份、应急能力

### 7.1 任务清单

| # | 任务 | 产出 | 验收标准 |
|---|---|---|---|
| M1E-01 | Prometheus + Grafana 部署 | observability/docker-compose.monitor.yml | 监控面板可访问 |
| M1E-02 | 关键指标采集 | src/physical_agent/runtime/metrics.py | 延迟、成功率、验证准确率、资源使用 |
| M1E-03 | 告警规则配置 | observability/alerts/*.yml | Tier 2 高频、验证失败率超限等告警 |
| M1E-04 | Loki 日志收集 | observability/loki/ | 审计日志 + 应用日志集中存储 |
| M1E-05 | 备份脚本 | scripts/backup.sh | HA config + Qdrant snapshots + 审计日志定期备份 |
| M1E-06 | 备份恢复演练 | 演练报告 | RTO < 30 分钟实测 |
| M1E-07 | Kill Switch 自动触发规则 | src/physical_agent/policy/auto_trigger.py | 连续 5 次验证失败自动激活 |
| M1E-08 | 安全加固 Checklist | docs/security_hardening_checklist.md | 全部项 checked |
| M1E-09 | 红队渗透测试 | 渗透报告 | 无 Critical/High 漏洞 |
| M1E-10 | 运维手册更新 | RUNBOOK.md 最终版 | 故障排查、日常运维、应急响应流程完整 |

### 7.2 DoD

- [ ] Prometheus + Grafana 运行，关键 Dashboard 就绪
- [ ] 告警通知渠道可用（邮件/Webhook/钉钉等）
- [ ] 备份自动化运行，恢复演练成功
- [ ] Kill Switch 自动触发经测试
- [ ] 红队渗透测试通过（或所有 High 以上问题已修复）
- [ ] RUNBOOK.md 覆盖所有已知故障模式

### 7.3 门禁放行（Phase 1 最终门禁）

**守门人**：**全体会签**（Architect + IoT + Agent Runtime + Platform/Security + QA/Red-Team）

**Phase 1 放行条件**：
- [ ] M0-M1D 全部 DoD 满足
- [ ] M1E 全部任务完成
- [ ] 安全评估报告通过
- [ ] 性能基线建立（延迟分布、资源使用）
- [ ] 备份恢复验证通过
- [ ] 文档完整性审核通过

**⚠️ 只有 M1E 门禁通过后，才允许启动视觉系统（M2）。**

---

## 8. Phase 2+ 路线图（冻结至 M1E 通过）

> 以下内容为规划参考，**不在本次 Architecture Audit 审批范围内**。
> M1E 通过后将重新评估技术栈和需求后更新。

### 8.2 Milestone 2：视觉感知系统（预估 5-7 天）

- Frigate NVR 部署 + IP Camera 接入
- VLM 集成（qwen3-vl 或专用模型）
- 视觉感知节点接入 Agent 图像
- 视觉验证通道（如"看到空调面板显示 26°C"）
- **新增安全评审**：摄像头隐私、图像数据存储加密

### 8.3 Milestone 3：电脑与手机操控（预估 5-7 天）

- Windows: MeshCentral / RustDesk Agent
- Android: scrcpy + ADB over TCP
- 新工具注册 + Policy Gate 更新
- **独立安全评审**：ADB 攻击面、远程桌面安全

### 8.4 Milestone 4：多设备协同（持续）

- 场景编排引擎（LangGraph workflow）
- "回家模式"、"睡眠模式"
- 记忆驱动的自动化学习
- 多 Agent 协作架构

---

## 9. 风险与依赖

### 9.1 外部风险

| 风险 | 可能性 | 影响 | 缓解 |
|---|---|---|---|
| 硬件物流延误 | 中 | M1C 延迟 | 提前下单；国内快递通常 2-5 天 |
| 空调品牌不支持 ESPHome 平台 | 低 | M1C 需手动学习 IR 码 | BC7215 通用方案兜底 |
| GPU 主机不可用 | 中 | LLM 延迟高或降级 CPU | CPU 降级方案已准备；M1A 可用 mock |
| ESPHome 版本 breaking change | 低 | 固件需适配 | Pin 版本；关注 changelog |

### 9.2 技术风险

| 风险 | 可能性 | 影响 | 缓解 |
|---|---|---|---|
| Qwen3 tool calling 准确率不足 | 中 | Agent 行为不稳定 | temperature≤0.2；few-shot examples；fallback 到 prompt-based |
| IR 发射可靠性问题（社区反馈）| 中 | 空调不响应 | 使用 RMT hardware transmitter（非软件 bit-banging）；社区方案 BC7215 |
| LangGraph 学习曲线 | 中 | 开发效率初期低 | 参考官方 tutorial + 社区示例 |

---

## 10. 里程碑状态追踪

| Milestone | 状态 | 开始日期 | 完成日期 | 备注 |
|---|---|---|---|---|
| M0 | ⏳ Planning | - | - | 待 Audit 批准后启动 |
| M1A | 🔲 Not Started | - | - | 依赖 M0 |
| M1B | 🔲 Not Started | - | - | 依赖 M0 |
| M1C | 🔲 Not Started | - | - | 依赖 M1B + 硬件 |
| M1D | 🔲 Not Started | - | - | 依赖 M1C |
| M1E | 🔲 Not Started | - | - | 依赖 M1D |
| M2 | 🚫 Frozen | - | - | M1E 通过后才解冻 |
| M3 | 🚫 Frozen | - | - | 同上 |
| M4 | 🚫 Frozen | - | - | 同上 |

---

*本文档是项目进度的唯一权威来源。每个里程碑完成后由 QA Engineer 更新状态。*
