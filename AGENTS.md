# AGENTS.md — 协作与治理规则

本文件约束所有在本仓库工作的 Agent 与人类协作者。

## 1. 角色定义（独立审查角色）

| 角色 | 职责 | 一票否决权范围 |
|---|---|---|
| **Principal Architect** | 架构一致性、ADR 审批、接口边界、技术选型 | 架构退化、未记录的决策 |
| **IoT / Home Assistant Engineer** | HA 集成、ESPHome 固件、MQTT、设备适配器 | 侵入式改造、不可逆固件操作 |
| **Agent Runtime Engineer** | 推理循环、规划、工具定义、记忆子系统 | 绕过 policy 的工具直调 |
| **Platform / DevOps / Security Engineer** | CI/CD、secrets、网络、备份、威胁模型落地 | 密钥入 Git、无鉴权暴露服务 |
| **QA / Reliability / Red-Team Engineer** | 验收测试、故障注入、对抗测试、DoD 守门 | 未过验收进入下一阶段 |

重大设计变更：**Architect + 实现负责人 + QA/Security 三方会签**，且必须有对应 ADR。

## 2. 铁律（任何 Agent/人类不得违反）

1. 密钥、令牌、WiFi 密码永不进 Git；发现即视为安全事故，立即轮换。
2. 未通过当前 Milestone 验收测试，不得开始下一 Milestone 的开发。
3. 所有物理执行动作必须经 Policy Gate（风险分级），并写审计日志。
4. 单向控制（IR）动作必须设计物理验证路径；无验证路径的动作自动升一级风险。
5. 每次会话结束，关键决策落 ADR 或更新相关文档——知识不许只留在对话里。
6. 禁止 `:latest` / `:stable` 浮动镜像标签进入 compose 文件；版本必须 pin。
7. 依赖、配置、命令以官方当前文档为准；任务书中的样例代码默认视为"参考"，必须重新验证。

## 3. 工作流

```
需求/想法 → Issue 描述 → ADR（如涉及架构）→ 三方审查
→ 实现 + 测试 → QA 验收（对照 ACCEPTANCE_TESTS.md）
→ 合并 → 更新 ROADMAP 状态
```

## 4. Definition of Done（每个任务通用）

- [ ] 代码/配置已落盘到工作区；**在首个 commit 存在前，只可说 "prepared for first commit"，不可说"已提交 Git"**（见 §6 治理状态）
- [ ] 相关测试通过（单元 + 适用的集成/验收测试）
- [ ] 无密钥泄露（`git grep` 检查 + pre-commit hook）
- [ ] 文档同步更新（架构行为变化必须更新 ARCHITECTURE.md 或 ADR）
- [ ] 审计日志格式未被破坏（若涉及执行路径）

## 5. Milestone 门禁

| Gate | 评审角色 | 放行条件 |
|---|---|---|
| M0 → M1A | QA + Platform | CI 绿、secrets 机制验证、架构评审通过 |
| M1A → M1B | QA | 模拟闭环验收测试全绿 |
| M1B → M1C | IoT + QA | HA 集成测试通过，真实实体只读验证完成 |
| M1C → M1D | IoT + QA + Red-Team | IR 闭环物理演示成功，失败注入测试通过 |
| M1D → M1E | QA | 物理验证准确率达标（见 ACCEPTANCE_TESTS）|
| M1E → M2（视觉）| 全体评审 | 安全加固、回滚演练、可观测性验收通过 |

## 6. 治理状态（对应 P0-9，铁律）

1. **Architecture Gate 只有 Owner 能通过。** 模拟角色（Architect/IoT/QA/Security 等）的审查只能记录为 `Reviewed-by-simulated-role`，**不等同项目正式批准**。
2. **所有 ADR 在 Owner 批准前状态必须是 `Proposed / Pending Owner Approval`**，禁止标 `Accepted`。
3. **禁止自代表 Owner 批准任何 architecture decision。**
4. **Git 状态措辞**：本仓库当前**无 commit**。在 `git log` 出现首个 commit 前，一律说 "prepared for first commit"，禁止说"已提交 Git"。
5. **未通过当前 Architecture Gate，不得开始真实设备控制、不得采购硬件、不得声称 M0 已通过。**
