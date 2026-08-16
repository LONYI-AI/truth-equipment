# ADR-0003: Agent 运行时 = LangGraph 状态机 + ModelProvider 抽象

## Status
**Proposed / Pending Owner Approval**（原 v0.1 为 Accepted，已撤回，见 P0-9）

## Context

任务书原方案：LangChain ReAct Agent + Qwen2.5:7b + prompt-based tool calling。

审计发现的问题：
1. **Qwen2.5 已过时**：Qwen3 全系发布，原生 tool calling 支持、128K 上下文、混合推理。
2. **ReAct 模式不稳定**：prompt-based tool calling 准确率依赖 prompt 工程，易格式错误。
3. **无显式状态机**："感知→决策→执行→验证"是一句话描述，没有可执行状态模型。
4. **asyncio.run() 反模式**：在 async 上下文中嵌套调用会 RuntimeError。

## Decision

**Agent 运行时采用 LangGraph StateGraph 显式状态机 + ModelProvider 抽象（本地模型不写死为架构不变量）。**

### 技术栈

- **框架**：LangGraph 1.x（LTS，StateGraph + checkpointing + human-in-the-loop）
- **模型**：经 `ModelProvider` 抽象访问；**候选模型 qwen3:8b，最终由 benchmark + 硬件决定**（见 ADR 备注 P1-2）
- **Tool Calling**：Ollama 原生 `/api/chat` tool calling API（非 prompt parsing）
- **温度**：低温度（≤0.2）以降低输出方差
- **异步模型**：全程 async-native，禁止 `asyncio.run()` 嵌套

### ModelProvider 抽象

```python
# agent/llm/provider.py（接口，M1A 实现）
from typing import Protocol

class ModelProvider(Protocol):
    async def complete(self, messages: list[dict],
                       tools: list[dict] | None = None) -> dict: ...
    @property
    def model_id(self) -> str: ...

class OllamaProvider:
    def __init__(self, url: str, model: str, *, temperature: float = 0.2) -> None: ...
```

**模型选型纪律**：qwen3:8b 是**候选**，不是不变量。最终选型由 `tests/benchmarks/model_tool_calling/` 的 benchmark 结果 + 可用硬件决定（见 COMPATIBILITY_MATRIX.md §3）。

### State Machine 节点定义

```
Perceive → Recall → Reason → Plan → PolicyGate → Execute → Verify → MemoryUpdate
                ↑                                                    │
                └────────────── (retry/compensate) ←─────────────────┘
```

## Consequences

### 正面影响
- ✅ 显式状态机可绘制、可调试、可单节点测试
- ✅ LangGraph checkpointing 支持断点恢复和人机协同
- ✅ ModelProvider 抽象允许无痛换模型（Ollama→vLLM→云端）
- ✅ 低温度降低输出方差，利于调试与回归测试

### 负面影响 / 风险
- ⚠️ LangGraph 学习曲线比简单 AgentExecutor 陡峭
  - 缓解：官方 tutorial + 示例丰富
- ⚠️ qwen3:8b 需要 ~6GB VRAM（纯 CPU 慢）
  - 缓解：CPU 降级方案；M1A 用 mock LLM 绕过
- ⚠️ Ollama 原生 tool calling 与 LangChain tool schema 可能需适配层
  - 缓解：LangChain 已有 Ollama integration，或用 LangGraph raw LLM call

### 关键澄清（对应 P0-11）

> **删除 v0.1 的两条不当断言**：
> 1. ~~"Qwen3 原生 tool calling 格式错误率 < 1%（vs ReAct 5-10%）"~~ —— 该数字**未经本项目实测**，已删除。真实错误率待 benchmark 测得。
> 2. ~~"temperature=0 保证相同输入相同输出"~~ —— **错误**。即使 temperature=0，浮点非确定性、并行调度、采样实现仍可能引入输出差异。正确表述：低温度**降低**（而非消除）输出方差。

## Related ADRs
- ADR-0004: 记忆存储（MemoryStore 抽象，Qdrant 非 M1 必需）
- ADR-0005: Policy Gate（在 Reason/Plan 与 Execute 之间）
- ADR-0001: Capability Gateway（Agent 只面对 Capability Schema）

## References
- LangGraph Docs: https://langchain-ai.github.io/langgraph/
- Ollama Tool Calling: https://github.com/ollama/ollama/blob/main/docs/tool-use.md
- Qwen3 模型库: https://ollama.com/library/qwen3

## Date
2026-08-16（v0.2 修订）

## Reviewers
- Reviewed-by-simulated-role: Principal Architect、Agent Runtime Engineer
- **Note**: 模拟角色审查不等于项目正式批准。最终由 **Owner** 通过 Architecture Gate。
