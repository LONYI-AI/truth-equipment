# ADR-0007: Secrets Management — .env + Pre-commit + SOPS

## Status
Proposed / Pending Owner Approval（原 v0.1 为 Accepted，已撤回，见 P0-9）

## Context
项目涉及多种密钥和凭据：
- HA Token（设备控制权限）
- Qdrant API Key（数据库访问）
- MQTT Username/Password（M1B+）
- WiFi SSID/Password（ESPHome 固件编译用）
- Agent Session Secret（会话签名）
- Audit Log Signing Key（审计日志完整性）

任务书的问题：
1. `.env` 模板存在但全文未提 `.gitignore` 和 pre-commit 保护
2. `secrets.yaml` 示例包含明文 WiFi 密码且计划进 Git
3. 无密钥轮换策略

## Decision
**分层 Secrets 管理：dev 用 .env 文件，prod 候选 SOPS。**

### 开发环境（M0-M1E）
- 所有密钥存储在 `.env` 文件（gitignored）
- `.env.example` 作为模板（仅占位符，无真实值）
- `scripts/generate_secrets.sh` 生成随机密钥
- Pre-commit hooks 扫描防止意外提交

```bash
# .pre-commit-config.yaml 核心配置
repos:
  - repo: https://github.com/gitleaks/gitleaks
    rev: v8.18.0
    hooks:
      - id: gitleaks  # 检测 300+ 种密钥模式
```

### 生产环境（M2+ 候选）
- 评估迁移到 Mozilla SOPS 或 Docker Secrets
- 加密存储 + Git 版本控制（加密后可安全提交）
- 自动轮换脚本（90 天周期）

### 运行时安全
- 密钥通过环境变量注入容器（不在 compose 文件中明文）
- 文件权限 600（owner only）
- 进程内存中的密钥最小化（用完即弃，不缓存）

## Consequences

### 正面影响
- ✅ 密钥永不进入 Git 仓库
- ✅ Pre-commit 自动扫描拦截常见人为误提交（拦截率以 gitleaks 规则覆盖为准，**不作百分比承诺**）
- ✅ 分离关注：模板 vs 真实值
- ✅ 生成脚本确保密码强度（openssl rand -hex 32）

### 负面影响 / 风险
- ⚠️ `.env` 文件需手动管理同步（团队成员间不共享）
  - 缓解：当前单人项目；多人协作时迁移到 SOPS
- ⚠️ 生成脚本丢失后需重新生成所有密钥
  - 缓解：脚本幂等；备份 .env 到加密位置
- ⚠️ CI 环境需要通过 GitHub Actions Secrets 注入
  - 缓解：标准做法，GitHub 原生支持

### 替代方案
- **HashiCorp Vault**：过重，个人项目不需要 ❌
- **AWS Secrets Manager / GCP Secret Manager**：违反自托管原则 ❌
- **明文存 Git（encrypted repo）**：不够安全 ❌

## Related ADRs
- ADR-0004: Qdrant API Key 管理
- ADR-0008: WireGuard 密钥对管理
- SECURITY_MODEL.md: §4 Secrets Management

## References
- Gitleaks: https://github.com/gitleaks/gitleaks
- Mozilla SOPS: https://getsops.io/
- 12-Factor App Config: https://12factor.net/config/

## Date
2026-08-16

## Reviewers
- Reviewed-by-simulated-role: Principal Architect | Platform/Security Engineer
- **Note**: 最终由 **Owner** 通过 Architecture Gate。模拟角色审查不等于项目正式批准。
