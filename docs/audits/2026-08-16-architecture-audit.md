# Architecture Audit — 2026-08-16（v0.1，已取代）

> ⚠️ **本报告已被 [architecture-audit-v0.2.md](2026-08-16-architecture-audit-v0.2.md) 取代。**
> v0.1 被外部独立审查驳回（REVISION REQUIRED），其中部分声明（Chroma CVE 编号、IR 回读 99%、端到端 <3s、temperature=0 确定性等）已在 v0.2 撤回或修正。
> 保留本文件仅为历史存档，**请以 v0.2 为准**。

审计对象：《Agent 物理世界感知与操控系统 – 项目任务书》（Kimi 生成，13 页）
审计人：Principal Engineer / TPM
状态：**Superseded（被 v0.2 取代）**

---

## 0. 总体结论

任务书作为 Product Brief 是合格的：方向正确（非侵入、自托管、闭环）、工具链覆盖面广、有明确的第一个闭环目标。但作为**实施方案**不合格：

- **2 处会直接烧硬件/留安全窟窿的硬错误**（红外电路缺限流电阻、MQTT 匿名开放）；
- **6 处已过时或与当前官方文档冲突**（模型、Chroma 配置、DHT 平台、compose 语法等）；
- **3 个架构级缺口**（无 policy/权限层、无物理验证子系统设计、无审计子系统）——恰好是本项目"完整闭环"目标的核心；
- **1 个未说明的关键资源假设**：本地 LLM 推理需要 GPU 主机，BOM 中完全没有。

建议：保留方向与大部分工具链，替换关键组件版本，新增 Policy/Verification/Audit 三个子系统，按 M0→M1A→…→M1E 门禁推进。

---

## 1. 逐条审计结果

### 1.1 硬错误（必须修正）

| # | 位置 | 问题 | 后果 | 修正 |
|---|---|---|---|---|
| E1 | §5.1 接线图 | 红外 LED 阳极经 100Ω 接 GPIO（D1），LED 无串联限流电阻、未接 5V 电源轨；2N2222 低边开关拓扑画错 | GPIO 驱动能力（~12mA）无法驱动 IR LED 有效脉冲电流（50-100mA），发射距离极短或完全无效；长期使用损伤 GPIO | 正确拓扑：5V → [22-47Ω 限流] → IR LED → 2N2222 C；E → GND；GPIO → [1kΩ] → B。见 HARDWARE_BOM.md |
| E2 | §5.3 mosquitto.conf | `listener 1883` + `allow_anonymous true`，且端口直接映射到宿主机 | 局域网内任何人可读写全部 MQTT 主题（未来门锁/摄像头接入即灾难）。Mosquitto 2.x 官方默认要求鉴权，任务书是在主动关闭安全机制 | `allow_anonymous false` + password_file + ACL；M1 阶段 ESPHome 走 HA 原生 API，**MQTT 整体推迟启用**（ADR-0009） |

### 1.2 已过时 / 与当前官方文档冲突

| # | 任务书内容 | 当前事实（已联网验证 2026-08） | 处置 |
|---|---|---|---|
| O1 | Ollama + Qwen2.5:7b + LangChain ReAct | Qwen3 全系（0.6B-72B）已发布，Ollama 原生 tool calling API 成熟，qwen3:8b（~6GB VRAM）工具调用准确率显著优于 Qwen2.5 时代的 prompt-based ReAct | 替换为 **qwen3:8b**（GPU 充足升 14b），ADR-0003 |
| O2 | Chroma `IS_PERSISTENT=TRUE` / `ANONYMIZED_TELEMETRY=FALSE`，挂载 `/chroma/chroma` | Chroma v1.x（当前 1.5.x）：上述环境变量为 legacy 已废弃，数据目录改为 `/data`；另有 **CVE-2026-45829**（1.0+ 预鉴权代码注入，未修复） | 弃用 Chroma server，改 **Qdrant**（带 API key 鉴权），ADR-0004 |
| O3 | DHT 配置 `model: DHT22` 隐式可选 | ESPHome 2025.2+ DHT 平台要求引脚支持内部上拉；白色裸 AM2302 必须显式 `model: AM2302`，否则读数失败 | 固件模板修正；同时建议换 **SHT31（I2C）**，DHT22 漂移大、故障率高 |
| O4 | `version: "3.8"` compose 头 | Compose v2 已废弃 version 字段（仅告警噪音） | 删除 |
| O5 | `ollama/ollama:latest`、`chromadb/chroma:latest`、`home-assistant:stable` | 浮动标签破坏可复现性；HA 当前稳定线 2026.7.x | 全部 pin 版本（compose 中注明升级流程） |
| O6 | Barrier 键鼠共享 | Barrier 上游已死（Wayland 不兼容），社区迁移到 Deskflow / Input Leap | Phase 3 时替换为 Deskflow |

### 1.3 安全风险（威胁模型详见 THREAT_MODEL.md）

| # | 风险 | 等级 |
|---|---|---|
| S1 | MQTT 匿名 + 明文 + 无 ACL（E2 的安全面） | **Critical** |
| S2 | ESPHome fallback AP 密码 `12345678` 硬编码进 YAML（且该 YAML 计划进 Git） | High |
| S3 | HA 容器 `privileged: true` 无必要（无 USB 直通需求时），扩大容器逃逸面 | Medium |
| S4 | HA 长期令牌 = 上帝权限，Agent 持有它即可控制所有设备，无分级、无吊销策略 | High |
| S5 | `.env` 模板存在但任务书全文未提 `.gitignore`，secrets.yaml 示例含明文 WiFi 密码 | High |
| S6 | Chroma 8000 端口无鉴权暴露（叠加 CVE-2026-45829） | High |
| S7 | Phase 3 的 ADB over TCP 是巨大攻击面，任务书无任何加固说明 | High（届时处理，M2 之前必须出方案） |
| S8 | Agent 无任何速率限制/确认机制，LLM 幻觉可直接转化为物理动作 | **Critical**（本项目特有） |

### 1.4 架构缺口（相对"完整闭环"目标）

| # | 缺口 | 说明 | 对应新子系统 |
|---|---|---|---|
| G1 | **无 Policy / 权限层** | 任务书里 LLM 拿到 tool 即直通 HA。LLM 输出不可信，物理执行前必须有确定性（非 LLM）的策略闸门：风险分级、参数边界（如温度 16-30℃）、速率限制、Tier 2+ 人工确认 | `services/policy-gate`（ADR-0005） |
| G2 | **物理验证只是"读一下 DHT22"** | IR 单向，DHT22 30s 采样、分钟级滞后、±0.5℃ 误差，无法可靠判定"空调是否真的响应"。需要多信号验证器：蜂鸣确认、IR 接收回读（追踪物理遥控器）、功率检测、温度趋势 | `agent/verification` + 硬件加 TSOP38238 接收管（ADR-0006） |
| G3 | **无审计子系统** | 终验标准要求 audit logs，但架构里不存在。需要 append-only 审计：intent → plan → policy 判定 → 执行 → 验证证据，全链路 correlation ID | `services/audit`（JSONL → Loki） |
| G4 | LLM 推理主机未定义 | Qwen3:8b 需 ~6GB VRAM；BOM 里没有 GPU 主机，<3s 端到端延迟在纯 CPU 上不可能 | 阻塞项 B1，需用户确认 |
| G5 | 状态机缺失 | "感知→决策→执行→验证→记忆"在任务书里是一句话，没有显式状态模型。用 LangGraph 显式建模闭环状态机（含失败补偿/回滚路径） | `agent/runtime`（ADR-0003） |
| G6 | `asyncio.run()` 包在同步 lambda 里当 LangChain tool | 在异步 agent 循环中直接 RuntimeError；且每次调用新建 event loop | M1A 实现时禁止此模式，统一 async-native |

### 1.5 保留 / 替换 / 删除清单

**保留（方向正确）：**
- Home Assistant 作为设备抽象层（ADR-0001）——核心决策正确
- ESPHome + IR 发射方案（修正电路后）——非侵入原则的最佳实践
- Docker Compose 编排、WireGuard 远程访问、Prometheus/Grafana、Syncthing
- 渐进式路线（先一个闭环再复制）

**替换：**
| 原 | 新 | 理由 |
|---|---|---|
| Qwen2.5:7b + ReAct prompt | Qwen3:8b + Ollama 原生 tool calling + LangGraph 状态机 | O1 / G5 |
| Chroma server | Qdrant（API key 鉴权） | O2 / S6 |
| ESP8266 D1 mini | ESP32-C3（新购） | ESP8266 进入维护期，C3 同价位、性能/安全更好；已有 D1 mini 可留作备用 |
| DHT22 | SHT31（I2C）为主，DHT22 备用 | 精度/漂移/故障率 |
| Barrier | Deskflow（Phase 3 时） | O6 |
| `allow_anonymous true` MQTT | 鉴权 + ACL，且 M1 不启用 | E2 |

**删除：**
- `version: "3.8"`、所有 `:latest` 标签、`privileged: true`（无 USB 需求时）、fallback AP 硬编码弱密码、`asyncio.run` tool 包装模式

---

## 2. 推荐新架构

```
┌──────────────────────────────────────────────────────────────┐
│ Interface: CLI / Chat / (Phase 2+ Voice)                     │
└──────────────────────────┬───────────────────────────────────┘
                           ▼
┌──────────────────────────────────────────────────────────────┐
│ AGENT RUNTIME (agent/)                                       │
│  LangGraph 状态机:                                           │
│  Perceive → Recall(Memory) → Plan → [Policy Gate] → Execute  │
│       ↑                                  │                   │
│       └──────── Verify(物理验证) ←────────┘                  │
│                 ↓ 失败: retry(≤2) → compensate → escalate    │
│  LLM: Ollama qwen3:8b (native tool calling, temperature≤0.2) │
└───────┬──────────────────────┬───────────────────┬───────────┘
        │ tool calls           │ memory            │ every step
        ▼                      ▼                   ▼
┌────────────────┐   ┌─────────────────┐   ┌──────────────────┐
│ TOOL GATEWAY   │   │ MEMORY          │   │ AUDIT            │
│ (services/)    │   │ Qdrant + episodic│  │ append-only JSONL│
│ - schema 校验  │   │ store (SQLite)  │   │ correlation ID   │
│ - 风险分级     │   │                 │   │ → Loki           │
│ - 速率限制     │   │                 │   │                  │
│ - Tier2+ 确认  │   │                 │   │                  │
└───────┬────────┘   └─────────────────┘   └──────────────────┘
        ▼
┌──────────────────────────────────────────────────────────────┐
│ DEVICE ABSTRACTION                                           │
│ Home Assistant (pinned, WebSocket 订阅状态 + REST 调服务)     │
└───────┬──────────────────────────────────────────────────────┘
        ▼
┌──────────────────────────────────────────────────────────────┐
│ DEVICE ADAPTERS (device_adapters/)                           │
│ ESPHome IR Gateway (ESP32-C3):                               │
│   - remote_transmitter (IR 发射)                             │
│   - remote_receiver  (IR 回读/物理遥控器追踪)  ← 新增         │
│   - SHT31 温湿度 (I2C)                        ← 替换 DHT22    │
│   - beep 声学确认 + 温度趋势 + (可选)功率检测 → 物理验证      │
└──────────────────────────────────────────────────────────────┘
```

关键架构决策（均已落 ADR，见 docs/DECISIONS/）：

1. **ADR-0001** 保留 HA 为唯一设备抽象面，Agent 永不直连设备协议
2. **ADR-0002** IR 网关换 ESP32-C3 + 修正发射电路 + 增加 IR 接收管
3. **ADR-0003** Agent 运行时 = LangGraph 显式状态机 + Qwen3 原生 tool calling，禁止 free-form ReAct
4. **ADR-0004** 向量记忆用 Qdrant；episodic 记忆（事件流水）用 SQLite
5. **ADR-0005** Policy Gate：Tier 0 只读 / Tier 1 可逆低风险（空调）/ Tier 2 需确认 / Tier 3 禁止自动
6. **ADR-0006** 物理验证多信号制：蜂鸣 + IR 回读 + 温度趋势，任一验证器可独立否决"成功"结论
7. **ADR-0007** secrets 走 .env（dev）/ SOPS（prod 候选），pre-commit 扫描
8. **ADR-0008** 远程访问用 WireGuard（内核态、简单），headscale 暂缓
9. **ADR-0009** MQTT 推迟到首个 Zigbee 设备接入时再启用，启用即鉴权+ACL

---

## 3. Phase 1（M0 + M1A-1E）详细实施计划

详见 ROADMAP.md 与 ACCEPTANCE_TESTS.md，摘要：

| Milestone | 内容 | 门禁（DoD 摘要） | 预计 |
|---|---|---|---|
| **M0** | 工程骨架、CI（lint/test/secret-scan/yaml 校验）、secrets 机制、dev 容器栈、架构评审 | CI 绿；`git grep` 无密钥；ADR 全签 | 2-3 天 |
| **M1A** | 全模拟闭环：Fake HA（ recorded fixtures ）+ LangGraph 状态机 + Policy Gate + Audit + 模拟验证器 | 20+ 单测；E2E 模拟用例（含失败注入：IR 未命中、验证超时、LLM 幻觉参数越界）全绿 | 3-4 天 |
| **M1B** | 真实 HA 集成：WebSocket 状态订阅 + 只读 smoke → 受控写 | 对真实 HA 的集成测试通过；token 权限审计 | 2 天 |
| **M1C** | ESPHome + 物理 IR：硬件组装、固件、协议匹配（确认空调品牌）、HA 实体上线 | 手机摄像头确认 IR 发射；HA 控制空调响应率 ≥95%（20 次） | 2-3 天（含等快递） |
| **M1D** | 物理验证上线：蜂鸣/IR 回读/温度趋势三通道，准确率标定 | 验证器真阳性 ≥95%、假阳性 ≤5%（各 20 次对抗测试） | 3 天 |
| **M1E** | 加固：速率限制、kill switch、回滚演练、Prometheus/Grafana/Loki、备份恢复演练 | 红队用例通过；备份恢复 RTO < 30min 实测 | 3-4 天 |

**只有 M1E 通过后才允许启动视觉系统（Frigate/摄像头）。**

---

## 4. 需要用户购买或确认的硬件

| 项 | 规格 | 估价 | 紧迫度 |
|---|---|---|---|
| **LLM 推理主机**（确认，B1） | GPU ≥ 8GB VRAM（qwen3:8b Q4）；或确认用现有机器/纯 CPU 降级方案 | — | **阻塞 M1A 之外的所有 LLM 实测** |
| **常开服务器**（确认，B2） | 任一台 Linux x86 主机跑 Docker（HA host 网络需要 Linux；Windows 仅作 dev） | — | 阻塞 M1B |
| ESP32-C3 开发板 | 如合宙/乐鑫 C3 | ¥20-30 | M1C |
| IR 发射管 ×2 | TSAL6200 940nm | ¥2 | M1C |
| IR 接收管 | TSOP38238（38kHz） | ¥2 | M1C（验证通道关键件） |
| NPN 三极管 + 电阻 | S8050/2N2222；1kΩ ×1、22-47Ω ×1 | ¥1 | M1C |
| 温湿度传感器 | **SHT31 模块（I2C）** | ¥10-15 | M1C |
| 面包板 + 杜邦线 | — | ¥10 | M1C |
| （可选）计量智能插座 | 非侵入功率验证通道（Zigbee 方案需另购 CC2652P 网关棒 ~¥80） | ¥40-120 | M1D 可选增强 |
| USB 充电器 5V/1A | 给网关独立供电 | 已有 | M1C |

**需确认：卧室空调品牌/型号**（决定 ESPHome climate 平台：tcl112 / gree / midea / coolix…），以及遥控器是否可用（IR 学习用）。

## 5. 只有真人才能完成的操作

1. 采购、焊接/插接硬件，给设备上电
2. 创建 HA 管理员账号、生成长期令牌、把真实值填入 `.env`
3. 按空调遥控器配合 IR 学习/验证；确认空调品牌型号
4. 提供/确认 GPU 主机与常开 Linux 服务器，安装 Docker
5. Tier 2+ 高风险动作的审批（制度上不可委托给 Agent）
6. 路由器侧操作（如需 IoT VLAN 隔离）

## 6. 我（Agent）可自主完成的操作

- 全部代码、配置、固件 YAML、CI、测试、文档
- 模拟环境（Fake HA、fixtures、故障注入）与 M1A 全部工作
- Docker compose 栈定义与本地 dev 验证（容器内）
- ESPHome 固件编译（`esphome compile`，烧录需真人插线）
- 审计/可观测性管道、备份脚本、红队用例实现

## 7. 阻塞项

| # | 阻塞项 | 影响 | 需要 |
|---|---|---|---|
| B1 | GPU/LLM 主机未确认 | M1A 可用 mock LLM 绕过；真实推理无法标定延迟 | 用户确认硬件 |
| B2 | 常开 Linux 服务器未确认 | M1B 起 blocked | 用户确认 |
| B3 | 空调品牌/型号未知 | M1C 固件 platform 无法定 | 用户查看空调铭牌/遥控器 |
| B4 | 本 Architecture Audit 待批准 | 一切实施工作 | 用户批复 |

---

## 8. 本批提交 Git 的文件清单

```
README.md  AGENTS.md  .gitignore  .env.example
docs/PRODUCT_SPEC.md  ARCHITECTURE.md  SECURITY_MODEL.md
THREAT_MODEL.md  HARDWARE_BOM.md  ROADMAP.md
ACCEPTANCE_TESTS.md  RUNBOOK.md
docs/audits/2026-08-16-architecture-audit.md（本文件）
docs/DECISIONS/ADR-0000-template.md, ADR-0001 ~ ADR-0009
docker/compose.core.yml（M0 草案，含 mosquitto 加固配置）
docker/mosquitto/config/mosquitto.conf, acl.example
{infra,services,device_adapters,agent,tests,scripts,observability}/.gitkeep
```
