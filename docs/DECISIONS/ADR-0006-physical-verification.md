# ADR-0006: 物理验证 — V0–V4 证据链模型

## Status
**Proposed / Pending Owner Approval**（原 v0.1 为 Accepted，已撤回，见 P0-4 / P0-9）

## Context

任务书"物理验证"仅提"DHT22 读室温确认空调已响应"——严重不足。

原 v0.1 ADR-0006 把 **"IR readback"（TSOP38238 检测本机 IR 发射）误认为"设备物理状态验证"**，并给出"99% reliability"等**未经实测的数字**。

外部审查指出（P0-4）：
1. TSOP38238 检测本机 IR 发射**只能证明"发射器输出了信号"（V2）**，不能证明"空调收到并执行了命令"（V3/V4）。
2. "99% reliability"等数字在无实测数据前不得写成事实。

## Decision

**重构为 V0–V4 五级验证证据链，严格区分不同验证层级。**

### 验证层级模型

| 层级 | 定义 | 证据 | 能否由 TSOP38238 回读证明 |
|---|---|---|---|
| **V0** | request accepted | Policy Gate 通过、请求被受理 | ❌（软件层）|
| **V1** | command dispatched | 命令已发往 HA/ESPHome | ❌（软件层）|
| **V2** | actuator output verified | **执行器（IR LED）确实输出了信号** | **仅此层** |
| **V3** | target-device acknowledgement | 目标设备（空调）收到并应答（蜂鸣/面板变化）| ❌（需声学/视觉）|
| **V4** | physical effect verified | 物理效果达成（室温趋势/功率变化）| ❌（需传感器）|

### 关键结论（对应 P0-4）

> **TSOP38238 检测本机 IR 发射 = V2（actuator output verified），不能单独证明空调收到/执行了命令（V3/V4）。**

### 验证证据状态机（修订）

```
command_sent            ← V1：命令已派发（软件层返回）
actuation_verified      ← V2：IR 发射器输出已确认（TSOP38238 回读）
device_acknowledged     ← V3：空调应答确认（声学蜂鸣 / 面板视觉）
physical_effect_verified← V4：物理效果确认（温度趋势 / 功率突变）
inconclusive            ← 证据不足，无法判定
failed                  ← 明确失败（证据链断裂）
```

### 各层级证据采集手段

| 层级 | 手段 | 硬件 | 状态 |
|---|---|---|---|
| V2 | TSOP38238 捕获本机发射码并比对 | TSOP38238（¥2）| M1C 必需 |
| V3 | 声学（麦克风检测空调蜂鸣）/ 视觉（Phase 2 摄像头看面板）| MAX9814（可选）| M1D 可选 |
| V4 | SHT31 温度趋势 / 计量插座功率突变 | SHT31（已购）/ 智能插座（可选）| M1D |

### 融合规则（不写死权重，实测标定）

- 单信号证据按层级组合，**高层级证据优先**。
- V2 成功 ≠ V3/V4 成功；V4 成功可回证 V3。
- 融合权重、阈值**以 M1D 实测标定为准**，实测前不预设具体数值。
- 结论带 confidence，但 confidence 的计算方法待标定（见 ACCEPTANCE_TESTS.md）。

### 可靠性数字纪律（对应 P0-4）

> **禁止在实测前写出 "99% reliability" 等数字。** 实验结果必须带：
> - sample size（样本量）
> - conditions（实验条件）
> - false positive rate（假阳性率）
> - false negative rate（假阴性率）
> - confidence interval（置信区间）

示例（正确写法，待实测填空）：
```
IR 回读（V2）实测：N=___，条件=___，TPR=___，FPR=___，CI95%=___
```

## Consequences

### 正面影响
- 验证语义清晰：不把"发射了"误当"生效了"
- 证据链可追溯：每层证据独立记录到审计
- 数字纪律：杜绝未经实测的可靠性宣称

### 负面影响 / 风险
- ⚠️ V3（设备应答）需要额外硬件（麦克风/视觉），M1 可能只有 V2+V4
  - 缓解：M1 验收以 V2 + V4 为主，V3 依赖声学硬件到位情况，缺失时明确标注 evidence 缺口
- ⚠️ 多级验证增加复杂度
  - 缓解：每级独立实现、独立测试、独立记录

## Related ADRs
- ADR-0002: IR 网关硬件（TSOP38238 是 V2 通道）
- ADR-0005: Policy Gate（验证结果反馈给 Policy 决定重试/升级）

## References
- TSOP38238 Datasheet: https://www.vishay.com/docs/82491/tsop382.pdf

## Date
2026-08-16（v0.2 修订）

## Reviewers
- Reviewed-by-simulated-role: IoT Engineer、Agent Runtime Engineer、QA/Reliability Engineer
- **Note**: 模拟角色审查不等于项目正式批准。最终由 **Owner** 通过 Architecture Gate。
