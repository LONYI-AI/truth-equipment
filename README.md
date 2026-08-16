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

**阶段：M0.1 Hardening Sprint 完成，Pending Owner M0 Gate。**

v3.0 规格（Physical Agent OS）为权威基线（见 [`docs/SPEC_V3.0.md`](docs/SPEC_V3.0.md)）。M0 首次 Gate Review = REVISION REQUIRED，M0.1 已完成全部 14 项 P0 整改。

| 关键交付 | 状态 |
|---|---|
| Physical Safety Kernel（Capability Gateway / Policy / Approval / Execution / Verification / Audit / KillSwitch）| ✅ `src/physical_agent/` |
| DeepSeek Harness SDK 集成（pin 0.1.0rc6 + 双 profile）| ✅ `src/physical_agent/runtime/deepseek_harness.py` + `harness/` |
| LangGraph / Mock runtime | ✅ `src/physical_agent/runtime/` |
| 测试套件（unit/security/conformance/simulation）| ✅ 126 passed，coverage 88% |
| Evidence pipeline + CI + pre-commit + consistency | ✅ `scripts/` + `.github/` |
| M0.1 报告 | ✅ [`docs/audits/2026-08-16-m0.1-hardening.md`](docs/audits/2026-08-16-m0.1-hardening.md) |

**治理状态（铁律，见 [AGENTS.md](AGENTS.md) §6）**：
- 所有 ADR 状态 = `Proposed / Pending Owner Approval`，**非 Accepted**。
- 模拟角色审查 ≠ Owner 批准。**只有 Owner 能通过 Architecture Gate / M0 Gate。**
- **在 Owner 批准前：不进行真实设备控制、不采购硬件、不开始 M1。**

## 仓库结构

| 目录 | 内容 |
|---|---|
| `src/physical_agent/` | 核心包：runtime / capability / policy / execution / verification / adapters / memory / audit / safety（Safety Kernel）|
| `docs/` | 产品规格、架构、安全模型、威胁模型、路线图、验收测试、Runbook、兼容矩阵、证据矩阵、SPEC v3.0 |
| `docs/DECISIONS/` | ADR（架构决策记录，Proposed / Pending Owner Approval）|
| `docs/audits/` | 阶段性审计报告 |
| `hardware/` | 开发板选型、GPIO 分配、原理图、电气审查清单、BOM |
| `harness/` | DeepSeek Harness profile（development / physical）|
| `tests/` | unit / integration / contract / security / simulation / runtime-conformance / physical |
| `evidence/` | 真实命令输出的证据（pytest / lint / typecheck / compose / security / conformance）|
| `scripts/` | verify_m0.py（证据管道）、check_repo_consistency.py 等 |
| `compose.yaml` / `compose.dev.yaml` / `compose.prod.yaml` | 根目录 Compose |
| `docker/` | Mosquitto 加固配置、Compose 校验记录 |
| `observability/` | Prometheus / Grafana / Loki / 审计日志 |

## 快速开始

M0.1 完成后可运行测试与证据管道：

```bash
pip install -e ".[dev]"       # 安装包 + 开发依赖
pytest -q                     # 运行全部测试
python scripts/verify_m0.py   # 生成 evidence/
python scripts/check_repo_consistency.py
```

```bash
cp .env.example .env        # 填写真实值；.env 永不提交
docker compose config       # 校验（fail-closed：密钥缺失即报错）
```

## 治理

- 审查角色与变更流程见 [`AGENTS.md`](AGENTS.md)。
- 重大设计变更需 Architect + 实现负责人 + QA/Security 三方审查（模拟角色），最终由 **Owner** 批准。
- 所有密钥走 `.env` / secrets 管理，禁止进入 Git（见 `docs/SECURITY_MODEL.md`）。
