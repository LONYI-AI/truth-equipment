# ACCEPTANCE_TESTS — Physical AI Agent Platform

版本：v0.1（2026-08-16）
状态：**待批准** —— 与 Architecture Audit 联合审批
原则：**未通过当前阶段验收测试，不得进入下一阶段**

---

## 1. 验收测试框架

### 1.1 测试层级

```
┌─────────────────────────────────────────────┐
│ E2E Acceptance (本文件)                      │ ← 每个 Milestone 门禁
│  端到端业务场景验证                           │
├─────────────────────────────────────────────┤
│ Integration Tests (tests/integration/)       │ ← 组件间交互验证
│  HA Client + Agent Runtime + Policy Gate     │
├─────────────────────────────────────────────┤
│ Unit Tests (tests/unit/)                     │ ← 单函数/类逻辑验证
│  Policy Gate 校验、Verification 融合算法等    │
└─────────────────────────────────────────────┘
```

### 1.2 测试工具栈

| 工具 | 用途 | 版本 |
|---|---|---|
| **pytest** | 测试框架 | ≥8.0 |
| **pytest-asyncio** | 异步测试支持 | ≥0.23 |
| **pytest-cov** | 覆盖率报告 | ≥5.0 |
| **pytest-timeout** | 超时控制 | ≥2.3 |
| **responses / aioresponses** | HTTP mock | 最新 |
| **factory-boy** | 测试数据工厂 | 最新 |
| **Faker** | 假数据生成 | 最新 |

### 1.3 测试环境分类

| 环境 | 用途 | 数据来源 |
|---|---|---|
| **unit** | 纯逻辑，无外部依赖 | Mock 全部 |
| **integration** | 组件交互，可用真实服务 | Fake HA / Stub Qdrant |
| **acceptance** | 端到端业务场景 | 真实 HA（M1B+）/ 真实硬件（M1C+）|
| **e2e** | 完整系统（含 LLM）| 可用真实 Ollama 或 Mock |

---

## 2. Milestone 0 验收标准

### AC-M0-01: 项目结构完整性

```bash
test_project_structure():
    """必须的目录和文件都存在"""
    required = [
        "docs/PRODUCT_SPEC.md",
        "docs/ARCHITECTURE.md",
        "docs/SECURITY_MODEL.md",
        "docs/THREAT_MODEL.md",
        "hardware/BOM.md",
        "docs/ROADMAP.md",
        "docs/ACCEPTANCE_TESTS.md",  # 本文件
        "docs/RUNBOOK.md",
        "docs/DECISIONS/",
        "compose.yaml",
        ".env.example",
        ".gitignore",
        "AGENTS.md",
        "README.md",
        "pyproject.toml",
        "tests/conftest.py",
    ]
    for path in required:
        assert Path(path).exists(), f"Missing: {path}"
```

**通过条件**：全部文件存在 ✅

### AC-M0-02: Git 安全配置

```bash
test_git_security():
    """.gitignore 覆盖所有敏感文件类型"""
    ignored_patterns = [".env", "*.pem", "*.key", "secrets.yaml", "**/password_file"]
    # 验证 .gitignore 包含这些模式
```

**通过条件**：敏感模式全部在 .gitignore 中 ✅

### AC-M0-03: CI Pipeline 可运行

```bash
test_ci_pipeline():
    """CI 在 PR 时自动触发并全绿"""
    # 触发 CI → 检查 status → 全绿
```

**通过条件**：main 分支 CI 绿灯 ✅

### AC-M0-04: Secrets 生成机制

```bash
test_secrets_generation():
    """scripts/generate_secrets.sh 可生成有效 .env"""
    # 运行脚本 → 输出 .env → 所有变量非占位符
```

**通过条件**：生成的 `.env` 无 `__REPLACE_ME__` 占位符 ✅

### AC-M0-05: Docker Compose 栈可启动

```bash
test_docker_stack_health():
    """docker compose up -d 后所有服务健康"""
    services = ["homeassistant", "ollama", "qdrant"]
    for svc in services:
        assert docker_check_healthy(svc), f"{svc} not healthy"
```

**通过条件**：声明的服务全部 healthy ✅（Mosquitto 可注释掉）

### AC-M0-06: ADR 完整性

```bash
test_adr_completeness():
    """ADR-0001 ~ ADR-0009 全部存在且格式正确"""
    required_adrs = [
        "ADR-0001-ha-abstraction.md",
        "ADR-0002-esp32-c3-gateway.md",
        "ADR-0003-agent-runtime.md",
        "ADR-0004-vector-memory-qdrant.md",
        "ADR-0005-policy-gate.md",
        "ADR-0006-physical-verification.md",
        "ADR-0007-secrets-management.md",
        "ADR-0008-remote-access-wireguard.md",
        "ADR-0009-mqtt-postponed.md",
    ]
    for adr in required_adrs:
        assert adr_exists(adr), f"Missing ADR: {adr}"
        assert adr_has_required_fields(adr)  # Status, Context, Decision, Consequences
```

**通过条件**：9 个 ADR 全部存在且格式正确 ✅

---

## 3. Milestone 1A 验收标准（模拟闭环）

### AC-M1A-01: 正常流程闭环（模拟验证）

**场景**：用户说"把空调打开到 26 度制冷"

> **M1A 语义（W0.1 规范化）**：M1A 为全模拟闭环。verification 只能使用明确标记为
> **SIMULATED VERIFICATION EVIDENCE** 的 deterministic fixture / mock verifier 结果。
> 不得声称获得真实 IR 回读 / 真实声学确认 / 真实物理效果，不得预设经验置信度阈值（如 0.9）。

```python
@pytest.mark.acceptance
@pytest.mark.asyncio
async def test_full_loop_open_ac_normal():
    """
    Given: Fake HA 返回空调 off，室温 28℃；模拟验证器 fixture 返回 confirmed 类 verdict
    When: 用户输入"打开空调到26度"
    Then:
      1. perceive → world_state 更新
      2. reason → LLM 输出 turn_on_ac(temp=26, mode=cool)
      3. plan → 结构化 Plan 对象
      4. policy_gate → 上下文风险分级 → Tier 2 → 阻塞等待确认
      5. 人工批准 → approved（审批单次消费）
      6. execute → 经 CapabilityGateway 调用 Mock Adapter（模拟设备，非真实 HA）
      7. verify → simulated verifier 被调用 → verdict 按 deterministic fixture 返回
      8. graph 根据 verdict 正确进入 success 分支（全程不产生任何 PHYSICAL execute()）
      9. memory_update → episodic + structured semantic 已写入（SQLite）
      10. audit log → correlation ID 一致、事件链完整、可 load_and_verify()
    """
    result = await agent.run("打开空调到26度")
    assert result.status == "completed"          # 真实字段 AgentResult.status（不新增 result 字段）

    # 1. 模拟验证器被调用
    assert simulated_verifier.was_called() is True

    # 2. 产生的 VerificationEvidence（M0 已冻结类型）明确标记 simulation provenance；
    #    level 由 deterministic fixture 决定，不预设经验置信度
    verification = simulated_verifier.last_evidence
    assert verification.evidence["provenance"] == "simulated"
    assert verification.level == fixture_verdict.level

    # 3. 无物理执行：通过 adapter registry / domain spy 观察——SIMULATION 域收到执行，
    #    PHYSICAL 域 adapter 从未被调用（不新增 result 字段）
    assert simulation_adapter.invocation_count == 1
    assert physical_domain_adapter.invocation_count == 0

    # 4. 审计链完整
    assert audit_log.load_and_verify() is True
    assert len(audit_log.get_records(result.correlation_id)) >= 11
```

> 注：验收契约保持**语义级**（W1 的精确 graph result 形状尚未定义）。断言只依赖
> M0 已冻结字段（`AgentResult.status` / `VerificationEvidence.level` / `VerificationEvidence.evidence`）
> 与测试侧观察（verifier spy / adapter registry），**不新增任何 result 字段**。

**通过条件**：模拟验证器被调用 ✅；证据带 simulation provenance ✅；PHYSICAL adapter 未被调用 ✅；审计链完整 ✅

### AC-M1A-02: LLM 参数越界拦截

**场景**：LLM 幻觉输出 temperature=100

```python
@pytest.mark.acceptance
@pytest.mark.asyncio
async def test_policy_gate_blocks_out_of_bounds():
    """
    Given: LLM 输出 turn_on_ac(temp=100, mode=cool)
    When: Policy Gate 校验
    Then: 拒绝执行，返回 ParameterOutOfBoundsError
          Audit log 记录拒绝事件
    """
    plan = Plan(tools=[ToolCall(name="turn_on_ac", params={"temperature": 100})])
    with pytest.raises(ParameterOutOfBoundsError):
        await policy_gate.check(plan)
    assert audit_log.last_event.type == "policy_rejected"
    assert audit_log.last_event.reason == "temperature out of bounds [16,30]"
```

**通过条件**：Policy Gate 拒绝 ✅；审计日志记录 ✅

### AC-M1A-03: 验证失败重试机制

**场景**：首次发射 IR 但空调未响应

```python
@pytest.mark.acceptance
@pytest.mark.asyncio
async def test_verification_failure_retry_success():
    """
    Given: 模拟验证器第 1 次返回 failed，第 2 次返回 confirmed
    When: execute → verify (fail) → retry → verify (success)
    Then: 最终成功，retry_count = 1
    """
    mock_verifier.set_sequence([VerificationResult.failed, VerificationResult.confirmed])
    result = await agent.run_with_retry("打开空调")
    assert result.success is True
    assert result.retry_count == 1
```

**通过条件**：重试后成功 ✅；retry_count 正确 ✅

### AC-M1A-04: 验证失败升级补偿

**场景**：连续 2 次验证失败

```python
@pytest.mark.acceptance
@pytest.mark.asyncio
async def test_verification_failure_compensate():
    """
    Given: 模拟验证器连续 2 次返回 failed
    When: execute → verify (fail) → retry → verify (fail) → compensate
    Then:
      1. 尝试回滚（关闭空调）
      2. 通知管理员
      3. 返回用户友好错误信息
      4. 审计记录完整失败链
    """
    mock_verifier.always_fail()
    result = await agent.run("打开空调")
    assert result.success is False
    assert result.compensation_attempted is True
    assert result.escalated_to_human is True
```

**通过条件**：补偿逻辑触发 ✅；升级通知发送 ✅

### AC-M1A-05: Tier 2 人工确认流程（审批单次使用 + 防重放）

**场景**：开启空调需要人工批准

> **M1A 语义（W0.1 规范化）**：批准路径与拒绝路径必须使用**两个独立** approval request。
> 复用 M0 已冻结的 ApprovalEngine 单次使用 / 过期 / 绑定 / 防重放语义，
> 不得为匹配旧验收伪代码而弱化。第二次消费同一审批必须失败。

```python
@pytest.mark.acceptance
@pytest.mark.asyncio
async def test_tier2_human_approval_flow():
    """
    Given: turn_on_ac 是 Tier 2 操作
    When: Agent 请求执行
    Then:
      1. 状态变为 awaiting_approval
      2. 不自动执行
      3. 批准路径（独立请求 a）→ 消费一次 → 执行
      4. 拒绝路径（独立请求 b）→ 关闭一次 → 不执行
    """
    # 批准路径（独立 approval request a）
    approval_req_a = await agent.request_approval(tool_call)
    assert approval_req_a.status == "awaiting"

    result_approved = await agent.execute_after_approval(approval_req_a.id, approve=True)
    assert result_approved.executed is True

    # 防重放 regression：第二次消费 approval_req_a 必须失败
    with pytest.raises(ApprovalError):
        await agent.execute_after_approval(approval_req_a.id, approve=True)

    # 拒绝路径（独立 approval request b）
    approval_req_b = await agent.request_approval(tool_call)
    result_rejected = await agent.execute_after_approval(approval_req_b.id, approve=False)
    assert result_rejected.executed is False
    assert result_rejected.rejection_reason is not None
    # 拒绝后同样被关闭/消费一次，不可再消费
    with pytest.raises(ApprovalError):
        await agent.execute_after_approval(approval_req_b.id, approve=True)
```

**通过条件**：批准/拒绝两条独立路径正确 ✅；防重放（第二次消费失败）✅

### AC-M1A-06: Kill Switch 生效（按 side_effect 语义）

**场景**：激活 Kill Switch 后写操作被阻止

> **M1A 语义（W0.1 规范化）**：Kill Switch 硬不变量 = 「所有 side-effecting / write 操作被阻止、
> read-only 操作放行」。是否写操作由 `side_effect` / `operation` 元数据决定，**不得按 risk tier 推断**。

```python
@pytest.mark.acceptance
def test_kill_switch_blocks_writes():
    """
    Given: Kill Switch 已激活
    When: 尝试执行任何 side_effect != NONE 的操作
    Then: 抛出 OperationBlockedError
    """
    kill_switch.activate()
    with pytest.raises(OperationBlockedError):
        policy_gate.check(write_operation)   # side_effect = REVERSIBLE_WRITE / IRREVERSIBLE_WRITE

    # 只读操作（side_effect = NONE, operation = OBSERVE）不受影响
    result = policy_gate.check(read_only_operation)
    assert result.approved is True

def test_kill_switch_fail_closed_regardless_of_context_risk():
    """
    Regression（W0.1 新增）：即使上下文风险分级变化，side-effecting 操作在
    Kill Switch active 时仍必须 fail-closed 被阻止。risk tier 只影响审批策略，
    不是 write/read 分类来源。
    """
    kill_switch.activate()
    with pytest.raises(OperationBlockedError):
        policy_gate.check(write_operation, context=RiskContext(time_of_day="day"))
    with pytest.raises(OperationBlockedError):
        policy_gate.check(write_operation, context=RiskContext(time_of_day="night"))
```

**通过条件**：side-effecting 写操作被阻止 ✅；只读操作放行 ✅；上下文风险变化不影响 fail-closed ✅

### AC-M1A-07: 速率限制生效

**场景**：短时间内频繁操作同一设备

```python
@pytest.mark.acceptance
@pytest.mark.asyncio
async def test_rate_limit_exceeded():
    """
    Given: 同一设备同操作已执行 3 次（1 分钟内）
    When: 第 4 次请求
    Then: RateLimitError，审计记录超限事件
    """
    for i in range(3):
        await policy_gate.check_and_record(ac_operation)

    with pytest.raises(RateLimitError):
        await policy_gate.check_and_record(ac_operation)  # 第 4 次

    assert audit_log.last_event.type == "rate_limited"
```

**通过条件**：第 4 次被拒绝 ✅

### AC-M1A-08: 审计日志完整性

**场景**：完整操作周期的审计追踪

```python
@pytest.mark.acceptance
def test_audit_log_integrity():
    """
    Given: 一次完整的操作周期
    Then: 审计日志包含以下事件（按时间顺序）：
      1. user_input_received
      2. perceive_complete
      3. recall_complete
      4. reason_complete
      5. plan_created
      6. policy_evaluated (approved/pending/rejected)
      7. tool_call_dispatched (if approved)
      8. execution_result
      9. verification_result
      10. memory_updated
      11. session_complete
    And: 所有记录共享同一 correlation_id
    And: 每条记录包含前一条的 hash（链式结构）
    And: 无敏感信息明文（token/password masked）
    """
    records = audit_log.get_records(correlation_id="test_xxx")
    expected_events = [
        "user_input_received", "perceive_complete", "recall_complete",
        "reason_complete", "plan_created", "policy_evaluated",
        "tool_call_dispatched", "execution_result", "verification_result",
        "memory_updated", "session_complete"
    ]
    actual_events = [r.event_type for r in records]
    assert actual_events == expected_events

    # 验证 correlation ID 一致
    assert all(r.correlation_id == "test_xxx" for r in records)

    # 验证 SHA-256 链式哈希（真实密码学校验，禁止 Python built-in hash()）
    # 每条记录的 hash 字段 = SHA256(prev_hash ‖ canonical(event))
    for i in range(1, len(records)):
        expected = sha256(records[i-1].hash + canonical(records[i])).hexdigest()
        assert records[i].hash == expected, f"chain broken at {i}"

    # 验证 checkpoint 签名：复用 M0 已冻结的 persistent audit checkpoint HMAC 机制。
    # 不引入 "HMAC public key" 概念；使用 checkpoint verification key / HMAC secret。
    assert audit_log.load_and_verify() is True  # 内部校验 HMAC 签名 + 链尾一致 + tamper detection

    # 验证脱敏
    for r in records:
        assert "token" not in str(r.data).lower() or "***" in str(r.data)
```

> 注：`canonical()` 为事件规范化序列化（字段顺序固定、UTF-8）；链式哈希与 checkpoint HMAC 复用
> M0 已验证的 audit 实现（`load_and_verify()` / `verify_checkpoint()`，标准库 `hashlib`/`hmac`，**非** `hash()`），
> 不引入 "HMAC public key" 概念。

**通过条件**：事件完整 ✅；correlation ID 一致 ✅；链式哈希正确 ✅；脱敏完成 ✅

### AC-M1A-09: 单元测试覆盖率

```bash
test_coverage_threshold():
    """核心模块覆盖率 ≥80%"""
    # pytest --cov=agent --cov=services --cov-report=term-missing
    # src/physical_agent/runtime/: ≥85%
    # src/physical_agent/policy/: ≥90%
    # src/physical_agent/verification/: ≥85%
    # src/physical_agent/audit/: ≥80%
```

**通过条件**：总覆盖率 ≥80%，关键模块更高 ✅

### AC-M1A-10: 审批挂起/恢复（suspend/resume）

**场景**：审批等待期间 graph 安全挂起，人工决定后恢复

> **M1A 语义（W0.1 规范化）**：LangGraphRuntime.resume() 是 M1A 真实缺口（M0 为 stub）。
> 验收契约只约束**可观察不变量**，复用 M0 已冻结协议：`AgentRuntime.run(UserIntent, RuntimeContext)`
> 与 `AgentRuntime.resume(session_id, RuntimeEvent)`；审批绑定用 `ApprovalRequest.canonical_request_hash`
> 并绑定 `correlation_id / principal / device_id / capability_id / canonical_request_hash / risk_tier`。
> 内部 LangGraph checkpoint/state API 在 W1 依官方文档选定，**不在 W0.1 冻结**。

```python
@pytest.mark.acceptance
@pytest.mark.asyncio
class TestApprovalSuspendResume:
    """四个独立场景，各自使用独立 approval request。"""

    # 场景 1：approve → resume → 恰好执行一次
    async def test_approve_executes_exactly_once(self, agent, simulation_adapter):
        result = await agent.run(
            UserIntent(text="打开空调到26度", session_id="s1"),
            RuntimeContext(correlation_id="c1", session_id="s1"),
        )
        assert result.status == "needs_approval"          # A. 初始 run 返回/进入 needs_approval
        approval_id = result.evidence["approval_id"]      # B. runtime 保留 approval_id + correlation_id

        resumed = await agent.resume(                     # C. RuntimeEvent 风格审批决策
            "s1", RuntimeEvent(event_type="approval_decision",
                               payload={"approval_id": approval_id, "decision": "approve"}),
        )
        assert resumed.status == "completed"
        assert simulation_adapter.invocation_count == 1   # 恰好执行一次

    # 场景 2：reject → 执行次数保持 0
    async def test_reject_never_executes(self, agent, simulation_adapter):
        result = await agent.run(
            UserIntent(text="打开空调到26度", session_id="s2"),
            RuntimeContext(correlation_id="c2", session_id="s2"),
        )
        assert result.status == "needs_approval"
        approval_id = result.evidence["approval_id"]

        resumed = await agent.resume(
            "s2", RuntimeEvent(event_type="approval_decision",
                               payload={"approval_id": approval_id, "decision": "reject"}),
        )
        assert resumed.status in ("rejected", "completed")   # 语义：未执行
        assert simulation_adapter.invocation_count == 0      # 拒绝后执行 0

    # 场景 3：过期审批 → resume 被拒绝 → 执行 0（确定性时间控制，不 sleep）
    async def test_expired_approval_never_executes(self, agent, simulation_adapter, clock):
        result = await agent.run(
            UserIntent(text="打开空调到26度", session_id="s3"),
            RuntimeContext(correlation_id="c3", session_id="s3"),
        )
        assert result.status == "needs_approval"
        approval_id = result.evidence["approval_id"]

        clock.advance(ttl_seconds + 1)                      # 越过过期点（injectable clock）

        with pytest.raises(ApprovalError):
            await agent.resume(
                "s3", RuntimeEvent(event_type="approval_decision",
                                   payload={"approval_id": approval_id, "decision": "approve"}),
            )
        assert simulation_adapter.invocation_count == 0      # 过期不执行

    # 场景 4：重放已消费审批 → ApprovalError → 不产生第二次执行
    async def test_replay_consumed_approval_fails(self, agent, simulation_adapter):
        result = await agent.run(
            UserIntent(text="打开空调到26度", session_id="s4"),
            RuntimeContext(correlation_id="c4", session_id="s4"),
        )
        assert result.status == "needs_approval"
        approval_id = result.evidence["approval_id"]

        await agent.resume("s4", RuntimeEvent(event_type="approval_decision",
                                              payload={"approval_id": approval_id, "decision": "approve"}))
        assert simulation_adapter.invocation_count == 1

        with pytest.raises(ApprovalError):                  # F. ApprovalEngine.consume 保持 exactly-once
            await agent.resume(
                "s4", RuntimeEvent(event_type="approval_decision",
                                   payload={"approval_id": approval_id, "decision": "approve"}),
            )
        assert simulation_adapter.invocation_count == 1      # 无第二次执行
```

**不变量**：
- A. 初始 run 返回/进入 `needs_approval`
- B. runtime 保留 `session_id` / `correlation_id` / `approval_id` / `canonical_request_hash`
- C. resume 用 `RuntimeEvent` 风格审批决策
- D. 批准的 resume 只执行 canonical hash 与审批匹配的那个请求
- E. 重新规划不得改动 `principal` / `device_id` / `capability_id` / `parameters`
- F. `ApprovalEngine.consume` 保持 exactly-once

**通过条件**：approve=执行一次 ✅；reject=执行 0 ✅；expire=执行 0 ✅；replay=ApprovalError ✅

---

## 4. Milestone 1B 验收标准（HA 集成）

### AC-M1B-01: HA 连接与只读查询

```python
@pytest.mark.integration
@pytest.mark.asyncio
async def test_ha_connection_and_read():
    """
    Given: 真实 HA 运行中，Token 有效
    When: 查询 climate.bedroom_ac 状态
    Then: 返回有效状态（含 temperature, hvac_mode 等）
    And: 延迟 < 500ms
    """
    ha = HomeAssistantClient()
    state = await ha.get_state("climate.bedroom_ac")
    assert state["entity_id"] == "climate.bedroom_ac"
    assert "temperature" in state["attributes"]
```

**通过条件**：查询成功 ✅；延迟达标 ✅

### AC-M1B-02: 受控写操作

```python
@pytest.mark.integration
@pytest.mark.asyncio
async def test_ha_controlled_write():
    """
    Given: 人工在测试监控台确认
    When: Agent 调用 climate.turn_on
    Then: HA 返回 2xx 且实体状态发生变更
    And: 审计日志记录完整
    """
    # 需要人工确认步骤（集成测试中模拟或手动）
    resp = await ha.post("/api/services/climate/turn_on",
                         json={"entity_id": "climate.bedroom_ac"})
    assert resp.status == 200
    # HA 服务调用成功返回被影响实体的状态列表（list），
    # 而非 {"result": "success"}。不假设固定 JSON 结构。
    body = resp.json()
    assert isinstance(body, list)
    # 可选：校验响应中包含 climate.bedroom_ac 的状态
    assert any(s["entity_id"] == "climate.bedroom_ac" for s in body)
```

**通过条件**：HA 返回 200 且实体状态变更 ✅（需人工配合观察空调是否真的启动）

### AC-M1B-03: 授权边界验证（Layer A + Layer B）

> **注意**：HA long-lived token **无 entity scope**（见 SECURITY_MODEL.md §2.2）。本测试验证的是 **Layer B（Capability Gateway）** 的 allowlist 边界，而非 HA token 的 entity 权限。

```bash
test_authorization_boundary():
    """Capability Gateway 的 entity/action allowlist 生效"""
    # 断言 Layer B 行为：
    # - 允许: home.climate.bedroom_ac.set_temperature（白名单内）
    # - 拒绝: home.switch.*（白名单外）
    # - 拒绝: 参数越界（temperature=100）
    #
    # 同时验证 Layer A：
    # - HA token 由 dedicated non-admin user 生成（人工检查 HA 用户角色）
    # - 该用户非管理员（人工检查）
```

**通过条件**：Layer B allowlist 拦截越权 ✅；Layer A 使用非管理员用户 ✅（后者为人工检查项）

---

## 5. Milestone 1C 验收标准（物理 IR 控制）

### AC-M1C-01: 设备在线与实体发现

```python
@pytest.mark.hardware
def test_esp32_online_and_discovered():
    """
    Given: ESP32-C3 已烧录固件并上电
    When: 检查 HA 设备列表
    Then: bedroom-ac-gateway 在线
    And: climate.bedroom_ac 实体存在
    And: sensor.bedroom_temperature 实体存在
    """
    devices = ha.list_devices()
    assert any(d.name == "Bedroom AC Gateway" and d.available for d in devices)
```

**通过条件**：设备在线 ✅；实体存在 ✅

### AC-M1C-02: HA UI 手动控制成功率

```python
@pytest.mark.hardware
@pytest.mark.parametrize("trial", range(20))
def test_ha_manual_control_success_rate(trial):
    """
    Given: 通过 HA UI 手动操作空调 20 次（开关、调温、切换模式混合）
    When: 每次操作后等待 5 秒检查状态
    Then: 成功率 ≥95%（即至少 19/20 成功）
    """
    operation = random.choice([turn_on, turn_off, set_temp_24, set_temp_26, mode_cool])
    result = ha.ui_manual_operation(operation)
    time.sleep(5)
    assert verify_ac_responded(result), f"Trial {trial} failed"
```

**通过条件**：≥19/20 成功 ✅

### AC-M1C-03: Agent 首次物理动作

```python
@pytest.mark.hardware
@pytest.mark.asyncio
async def test_agent_first_physical_action():
    """
    Given: M1B 已通过，Agent 可连接真实 HA
    When: Agent 执行"打开空调到26度"（经人工批准）
    Then:
      1. HA API 返回 success
      2. 物理空调响应（蜂鸣或面板变化）
      3. 审计日志记录首次物理写操作
    """
    result = await agent.run("打开空调到26度", auto_approve_tier2=True)
    assert result.execution_success is True
    assert wait_for_physical_response(timeout=10)  # 等待物理证据
    assert audit_log.contains(event_type="first_physical_actuation")
```

**通过条件**：Agent 成功操控真实空调 ✅

---

## 6. Milestone 1D 验收标准（物理验证）

> **数字纪律（对应 P0-4）**：以下数值为**验收目标阈值（target）**，不是已测得的事实。任何实测结果必须附带：**sample size、conditions、FPR（假阳性率）、FNR（假阴性率）、CI95（置信区间）**。实测前，下列"≥99% / ≥95%"仅作为"待验证目标"，不得引用为已达成事实。

### AC-M1D-01: IR 回读验证准确率（V2 层）

```python
@pytest.mark.hardware
@pytest.mark.calibration
def test_ir_readback_accuracy():
    """
    Given: TSOP38238 接收管已连接
    When: 发射 N 次 IR 码（不同命令）+ 无发射时监听 M 分钟
    Then: 记录并报告（而非仅断言）：
      - sample size N=___（待填实测值）
      - conditions=___（距离/角度/环境光）
      - TPR=___（真阳性率）
      - FPR=___（假阳性率）
      - FNR=___（假阴性率）
      - CI95=___（95% 置信区间）
    验收目标：TPR ≥ 99%（待验证，非已达成事实）
    """
    # 目标阈值：TPR≥99%、FPR≤1%（数据未测前仅为目标）
    report = calibration_report()
    assert "sample_size" in report and "FPR" in report and "CI95" in report
```

**通过条件**：校准报告字段完整 ✅；TPR/FPR 落在目标阈值内（以实测为准）✅

### AC-M1D-02: 多信号融合准确率（V2+V4）

```python
@pytest.mark.hardware
def test_fusion_accuracy():
    """
    Given: 验证器在线（V2 IR 回读 + V4 温度趋势；V3 依硬件到位情况）
    When: 40 次操作（真开/关 + 干扰测试）
    Then: 报告融合结论的准确率，带 FPR/FNR/CI
    验收目标：融合准确率 ≥95%（待验证，非已达成事实）
    """
    results = []
    for i in range(40):
        execute_action()
        signals = collect_all_signals()
        verdict = fuse_evidence(signals)  # 权重/阈值由本次标定确定
        results.append((verdict, ground_truth[i]))
    report = accuracy_report(results)  # 含 FPR/FNR/CI
```

**通过条件**：准确率报告字段完整 ✅；落在目标阈值内（以实测为准）✅

### AC-M1D-03: 对抗测试

```python
@pytest.mark.adversarial
def test_adversarial_verification_bypass():
    """
    Given: 攻击者尝试欺骗验证器
    When:
      1. 手电筒照射 IR 接收管（光干扰）
      2. 另一遥控器同时发射（信号干扰）
      3. 人为改变环境温度（传感器欺骗）
    Then: 报告假阳性率 FPR，带 sample size 与 CI
    验收目标：FPR ≤5%（待验证，非已达成事实）
    """
    false_positive_rate, report = measure_false_positive_rate()
    assert report_has_fields(report)  # sample size/conditions/FPR/CI
```

---

## 7. Milestone 1E 验收标准（安全加固）

### AC-M1E-01: 监控告警可用

```python
@pytest.mark.observability
def test_monitoring_alerts():
    """
    Given: Prometheus + Grafana + Alertmanager 运行中
    When: 触发告警条件（如高频 Tier 2 操作）
    Then: 告警通知发出（邮件/Webhook/钉钉）
    """
    # 模拟触发条件
    generate_high_frequency_tier2_operations()
    # 验证告警
    alert = wait_for_alert(timeout=5m)
    assert alert.fired is True
    assert alert.severity in ["warning", "critical"]
```

**通过条件**：告警触发 ✅；通知送达 ✅

### AC-M1E-02: 备份恢复 RTO

```bash
test_backup_restore_rto():
    """
    Given: 自动备份正在运行
    When: 模拟灾难（删除 config 目录）
    Then: 从备份恢复，RTO < 30 分钟
    """
    start_time = now()
    run_restore_script()
    restore_time = now() - start_time
    assert restore_time < 30_minutes
    assert ha_is_healthy()  # 恢复后服务正常
```

**通过条件**：RTO < 30min ✅；服务恢复 ✅

### AC-M1E-03: Kill Switch 自动触发

```python
@pytest.mark.safety
def test_kill_switch_auto_trigger():
    """
    Given: 配置连续 5 次验证失败自动激活 Kill Switch
    When: 模拟连续 5 次验证失败
    Then: Kill Switch 自动激活
    And: 后续写操作全部被阻止
    """
    for i in range(5):
        simulate_verification_failure()

    assert kill_switch.is_active is True

    with pytest.raises(OperationBlockedError):
        execute_tier1_operation()
```

**通过条件**：自动激活 ✅；写操作阻止 ✅

### AC-M1E-04: 渗透测试通过

```bash
test_penetration_test_results():
    """
    Given: Red-Team 完成渗透测试
    Then: 无 Critical 或 High 漏洞
    Or: 所有 High 以上漏洞已有修复计划 + 临时缓解措施
    """
    report = load_pentest_report()
    critical_count = count_vulnerabilities(report, severity="Critical")
    high_count = count_vulnerabilities(report, severity="High")
    assert critical_count == 0, f"{critical_count} Critical vulns!"
    assert high_count == 0, f"{high_count} High vulns!"
```

**通过条件**：无 Critical/High ✅

---

## 8. 性能验收指标

> **数字纪律**：以下所有数值为**验收目标（target）**，非已测得事实。最终以 M1E 实测基线为准（见 COMPATIBILITY_MATRIX.md）。

### 8.1 延迟指标（M1E 标定）

| 阶段 | 目标延迟（待验证）| 测量方法 | 备注 |
|---|---|---|---|
| LLM 推理（含 tool calling）| GPU 与 CPU 分别实测标定 | Ollama metrics | 具体模型由 benchmark 决定 |
| HA API 调用 | 实测标定 | HA 内置计时 | 本地网络 |
| Policy Gate 校验 | 实测标定 | 内部计时 | 纯内存计算 |
| IR 发射 → 接收回读 | 实测标定 | ESPHome 日志 | 硬件响应 |
| 端到端（用户→物理确认）| **实测标定（不预设 <3s/<5s）** | 全链路 tracing | 含 LLM + HA + 验证 |

> **v0.1 修正**：v0.1 曾写"端到端 <3s / <5s"。这些数字在无实测硬件前不作承诺。任务书原定"<3s 端到端"需在真实 GPU/CPU 上标定后确认是否可达。

### 8.2 可靠性指标（目标，实测后填样本量/条件/CI）

| 指标 | 目标值（待验证）| 测量方法 |
|---|---|---|
| HA UI 控制成功率 | ≥95%（待实测）| 20 次采样 + CI |
| Agent 写操作成功率 | ≥90%（待实测）| 生产统计 + CI |
| 验证器真阳性率 | ≥95%（待实测）| 标定测试 + FPR/FNR/CI |
| 验证器假阳性率 | ≤5%（待实测）| 对抗测试 + CI |
| 系统可用性（HA）| ≥99%（待实测）| Uptime 监控 |

---

## 9. 测试执行与门禁流程

### 9.1 每个 Milestone 的测试执行步骤

```bash
# 1. 运行单元测试
pytest tests/unit/ -v --cov=agent --cov=services --cov-report=html

# 2. 运行集成测试
pytest tests/integration/ -v --integration

# 3. 运行验收测试（对应 Milestone）
pytest tests/acceptance/ -v --acceptance -m "m1a"  # 或 m1b, m1c, etc.

# 4. 生成覆盖率报告
# 查看 htmlcov/index.html

# 5. 收集性能基线
pytest tests/benchmark/ --benchmark-only

# 6. 人工审查项（QA Checklist）
#   - 代码 Review 完成
#   - 安全 Check 通过
#   - 文档同步更新
#   - ADR 如有变更已更新
```

### 9.2 门禁决策矩阵

| 检查项 | M0 | M1A | M1B | M1C | M1D | M1E |
|---|---|---|---|---|---|---|
| 单元测试全绿 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| 集成测试全绿 | - | ✅ | ✅ | ✅ | ✅ | ✅ |
| 验收测试全绿 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| 覆盖率达标 | - | ✅ | ✅ | ✅ | ✅ | ✅ |
| Code Review | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| 安全扫描通过 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| 文档更新 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| 性能基线 | - | - | - | - | - | ✅ |
| 备份恢复验证 | - | - | - | - | - | ✅ |
| 渗透测试 | - | - | - | - | - | ✅ |
| **守门人** | Platform+QA | QA | IoT+QA | IoT+QA+Red | IoT+QA+Red | **全体** |

---

*本文档是项目质量的唯一判定标准。任何偏离须走 ADR 流程更新本文件。*
