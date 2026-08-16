# ADR-0008: 远程访问使用 WireGuard（内核态 VPN）

## Status
Proposed / Pending Owner Approval（原 v0.1 为 Accepted，已撤回，见 P0-9）

## Context
需要从外部网络安全访问 Home Assistant 和 Agent 服务。

候选方案对比：

| 方案 | 安全性 | 性能 | 复杂度 | 自托管 |
|---|---|---|---|---|
| **WireGuard** | 加密认证 | 极快 | 简单 | |
| Tailscale | | | 简单 | ❌ 依赖其协调服务器 |
| headscale (自建 Tailscale) | | | ⚠️ 中等 | |
| OpenVPN | | ⚠️ 较慢 | ❌ 复杂 | |
| 反向代理 + TLS | ⚠️ 仅应用层 | | 简单 | |
| ZeroTier | | | 简单 | ❌ 依赖其根服务器 |

## Decision
**使用 WireGuard 作为远程访问 VPN 方案，headscale/Tailscale 暂不引入。**

理由：
1. WireGuard 是 Linux 内核模块，性能极低开销（比 OpenVPN 快 10x）
2. 配置极其简单（一个 .conf 文件）
3. 完全自托管，无第三方依赖
4. 社区成熟，文档丰富
5. 手机/电脑客户端齐全

架构：
```
Internet → Server :51820/UDP (WireGuard)
                ↓ (加密隧道)
         10.10.10.x 内网
                ├── HA :8123
                ├── Ollama :11434 (内部)
                ├── Agent Runtime
                └── Grafana :3000 (via Caddy)
```

headscale 推迟原因：
- 当前仅 1-2 个客户端（用户手机 + 笔记本），WireGuard 手动管理即可
- headscale 增加运维复杂度（额外服务、证书管理）
- 未来客户端 > 5 时再考虑迁移

## Consequences

### 正面影响
- 内网服务完全不暴露到公网（除 WireGuard 端口）
- 加密认证，无需密码
- 性能极佳（内核态处理）
- 配置简单，故障排查容易

### 负面影响 / 风险
- ⚠️ 需要服务器有公网 IP 或端口转发（UDP 51820）
  - 缓解：大多数家庭宽带/NAT 支持；或使用 VPS 中转
- ⚠️ 客户端需安装 WireGuard 应用
  - 缓解：iOS/Android/Windows/macOS/Linux 全支持
- ⚠️ 无自动 DNS 解析（需手动配置 /etc/hosts 或内部 DNS）
  - 缓解：少量服务，手动管理可行

### 替代方案
- **Tailscale**：更简单但依赖第三方协调服务器，违反"零厂商锁定"原则 ❌
- **纯反向代理 + 2FA**：HA/Grafana 暴露到公网，增加攻击面 ❌
- **Tailscale + headscale**：好方案但当前过度工程 💭（M3 后重新评估）

## Related ADRs
- SECURITY_MODEL.md: §5 Network Security
- infra/wireguard/ 目录（配置文件位置）

## References
- WireGuard Official: https://www.wireguard.com/
- WireGuard Quick Start: https://www.wireguard.com/quickstart/
- WireGuard Installation: https://www.wireguard.com/install/

## Date
2026-08-16

## Reviewers
- Reviewed-by-simulated-role: Principal Architect | Platform/DevOps Engineer
- **Note**: 最终由 **Owner** 通过 Architecture Gate。模拟角色审查不等于项目正式批准。
