# Truth Equipment — Physical AI Agent Platform

Production-grade、self-hosted、non-invasive 的物理世界感知与操控 Agent 平台。

核心目标不是"LLM 调一下 Home Assistant API"，而是形成完整闭环：

```
Perception → State → Reasoning → Planning → Tool Execution
→ Physical Verification → Memory → Audit
```

## 设计原则（不可妥协）

1. **Non-invasive**：不拆机、不改线、不刷目标设备原厂固件，控制端可随时物理移除。
2. **Self-hosted**：全部基础设施本地部署，零厂商云锁定。
3. **Verified actuation**：IR 等单向控制必须配独立的物理验证通道（传感器/功率/接收回读）。
4. **Policy-gated**：所有物理动作按风险分级（Tier 0-3），高风险动作需人工确认 + 审计 + 可回滚。
5. **Auditable**：每次推理、每次工具调用、每次物理验证结果都落 append-only 审计日志。
6. **Docs-as-code**：架构决策必须落 ADR（`docs/DECISIONS/`），不允许关键知识只存在于对话中。

## 当前状态

**阶段：Integration Simulation MVP runnable；M1A milestone Gate 仍 In Progress。**

- ✅ **M0 Safety Kernel** 已通过验收（Capability Gateway / Policy / Approval / Execution / Verification / Audit / KillSwitch）。
- ✅ **Integration Simulation MVP runnable**（M1A 全模拟闭环已可运行）：一个命令即可在本机启动，输入自然语言走完整闭环
  `Perceive → Recall → Reason → Plan → Policy → Approval → Execute → Verify → Memory → Audit`。
- ⏳ **M1A milestone Gate**：仍 In Progress（本轮 Integration Hardening 产出待 Owner 验收，尚未通过）。
- 🔲 **M1B NOT STARTED**：Home Assistant 真实集成未开始（本轮禁止）。
- 🔲 **PHYSICAL execution / ESPHome / 真实设备控制**：NOT STARTED（本轮禁止）。

当前权威设计由 [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) 与正式产品/安全文档共同定义；历史规格和阶段审计仅保留在 Git history。

| 关键交付 | 状态 |
|---|---|
| Physical Safety Kernel（Capability Gateway / Policy / Approval / Execution / Verification / Audit / KillSwitch）| ✅ `src/physical_agent/` |
| M1A Simulation StateGraph（Perceive → Recall → Reason → Plan → Policy → Approval → Execute → Verify → Memory → Audit）| ✅ `src/physical_agent/runtime/` |
| 正式 LangGraphRuntime（真实 StateGraph + `Command(resume)` 审批挂起/恢复）| ✅ `src/physical_agent/runtime/langgraph.py` |
| Composition root（单一组装：registry / adapters / policy / approval / gateway / audit / memory / reasoning / handlers / checkpointer / runtime）| ✅ `src/physical_agent/composition.py` |
| ReasoningModel provider（可配置确定性 `RuleBasedReasoningModel`；测试用 `MockReasoningModel`）| ✅ `src/physical_agent/runtime/reasoning.py` |
| M1A Simulation CLI（`python -m physical_agent.cli`）| ✅ `src/physical_agent/cli.py` |
| DeepSeek Harness 真实 SDK 集成（官方 `deepseek_harness.DeepSeekHarness` + Cordis composition + CI smoke test）| ✅ `src/physical_agent/runtime/deepseek_harness.py` |
| 测试套件（unit / integration / security / conformance / simulation + DeepSeek smoke）| ✅ 本地安全回归；Linux Harness smoke 仅能由支持平台 CI 作为 Gate evidence |

**如实区分（本轮边界）**：
- **M1A Simulation（Integration Simulation MVP）**：✅ runnable，全模拟（MockDevice/MockAdapter + `mode=SIMULATION`），不接真实设备；**M1A milestone Gate 仍 In Progress**。
- **M1B Home Assistant**：🔲 NOT STARTED，本轮禁止。
- **PHYSICAL execution**：🔲 NOT STARTED，本轮禁止（不接真实 Home Assistant、不做 ESPHome、不控制真实设备、不做 Web UI / 手机 App / 多 Agent、不开始 M1B）。

**治理状态（铁律，见 [AGENTS.md](AGENTS.md) §6）**：
- 所有 ADR 状态 = `Proposed / Pending Owner Approval`，**非 Accepted**。
- 模拟角色审查 ≠ Owner 批准。**只有 Owner 能通过 Architecture Gate / 各 Milestone Gate。**
- **在 Owner 批准对应阶段前：不进行真实设备控制、不采购硬件、不开始 M1B / M1C 物理执行。**

## 仓库结构

| 目录 | 内容 |
|---|---|
| `src/physical_agent/` | 核心包：runtime / capability / policy / execution / verification / adapters / memory / audit / safety（Safety Kernel）|
| `docs/` | 当前产品规格、架构、安全模型、威胁模型、路线图、验收测试、Runbook、兼容矩阵 |
| `docs/DECISIONS/` | ADR（架构决策记录，Proposed / Pending Owner Approval）|
| `hardware/` | 开发板选型、GPIO 分配、原理图、电气审查清单、BOM |
| `harness/` | DeepSeek Harness profile（development / physical）|
| `tests/` | unit / integration / contract / security / simulation / runtime-conformance / physical |
| `evidence/` | 真实命令输出的证据（pytest / lint / typecheck / compose / security / conformance）|
| `scripts/` | verify_m0.py（证据管道）、check_repo_consistency.py 等 |
| `compose.yaml` / `compose.dev.yaml` / `compose.prod.yaml` | 根目录 Compose |
| `docker/` | Mosquitto 加固配置、Compose 校验记录 |
| `observability/` | Prometheus / Grafana / Loki / 审计日志 |

## 快速开始

M1A Simulation MVP 可运行测试与交互式 CLI：

```bash
pip install -e ".[dev]"          # 安装包 + 开发依赖
pytest -q                        # 运行全部测试（含 M1A end-to-end acceptance）
python -m physical_agent.cli     # 交互式 M1A Simulation CLI（真实闭环）
```

CLI 目标体验：:

```text
You: 把客厅空调调到26度
Agent: 此动作需要批准。
Approve? [y/N]: y
Agent: SIMULATION 执行完成。
Verification: V2 satisfied
```

> **M1A Simulation 边界**：CLI 只走全模拟闭环（`mode=SIMULATION` + MockDevice/MockAdapter），
> 不接真实 Home Assistant、不做 ESPHome、不控制真实设备。

```bash
cp .env.example .env        # 填写真实值；.env 永不提交
docker compose config       # 校验（fail-closed：密钥缺失即报错）
```

## 治理

- 审查角色与变更流程见 [`AGENTS.md`](AGENTS.md)。
- 重大设计变更需 Architect + 实现负责人 + QA/Security 三方审查（模拟角色），最终由 **Owner** 批准。
- 所有密钥走 `.env` / secrets 管理，禁止进入 Git（见 `docs/SECURITY_MODEL.md`）。
