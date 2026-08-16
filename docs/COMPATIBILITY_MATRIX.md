# COMPATIBILITY_MATRIX — 组件兼容性与版本矩阵

版本：v0.3（2026-08-16，M0.1 Hardening Sprint / P0-13 刷新）
状态：**Proposed / Pending Owner Approval**

> **目的（P0-13）**：明确区分 **Current upstream** / **Selected baseline** / **Experimental prerelease**，不得混淆。
> 所有版本经官方渠道核实（2026-08-16）；"Current upstream" 不代表最终 selected baseline，须经本项目测试后 pin。

---

## 1. 版本矩阵总表

| Component | Current upstream | Selected baseline | 类型 | 核实日期 |
|---|---|---|---|---|
| DeepSeek Harness | 0.1.0-rc.6（Developer Preview）| **pin commit SHA**（见 §0）| **Experimental prerelease** | 2026-08-16 |
| deepseek-harness-sdk | 0.1.0rc6 | **==0.1.0rc6（exact）** | **Experimental prerelease** | 2026-08-16 |
| LangGraph | 1.2.x（1.2.5 已证实；Owner 引 1.2.11，待 pin）| **1.x LTS，M0 定 patch** | Stable | 2026-08-16 |
| Home Assistant | 2026.8.2 | 2026.8.2 | Stable | 2026-08-16 |
| ESPHome | 2026.8.0 generation | ≥2026.4.0，M0 定 patch | Stable | 2026-08-16 |
| Ollama | 0.32.13 | 0.32.13 | Stable | 2026-08-16 |
| Qwen model | qwen3.5/3.6 系 | qwen3:8b（候选，benchmark 决定）| 非架构不变量 | 2026-08-16 |
| Qdrant | v1.18.1 | v1.18.1（M1 不启用）| Stable（planned）| 2026-08-16 |
| Docker Engine / Compose | 29.x / v5.1.1 | ≥25.0 / v2 插件 | Stable | 2026-08-16 |
| Mosquitto | 2.0.x | 2.0.x（M1 禁用）| Stable | 2026-08-16 |

---

## 0. DeepSeek Harness（重点，P0-13）

| 字段 | 值 |
|---|---|
| Component | DeepSeek Harness（deepseek-ai/deepseek-harness）|
| Current upstream | **0.1.0-rc.6**（npm latest/next 与 PyPI 均仍 rc.6）|
| Selected baseline | **pin commit SHA**（禁止 master/latest；M0-D 在 Linux 上 pin 后回填）|
| 类型 | **Experimental prerelease**（官方 README 明确 Developer Preview，会有 breaking changes）|
| Python SDK | `deepseek-harness-sdk==0.1.0rc6`（依赖 `deepseek-harness-runtime-bin==0.1.0rc6`）|
| **平台限制** | 运行时二进制仅发布 **Linux x64/arm64、macOS 14+ arm64**；**不支持 Windows**（本机无法运行 SDK）|
| Known limitations | ① Windows 不支持；② 跨进程 session resume 存在 id collision 未见修复；③ 无稳定版；④ headless 无交互 TUI |
| Tested with | **未在本机（Windows）实测**；集成代码已实现，Linux/macOS 上跑 platform-gated 测试 |
| Upgrade policy | 跟踪 rc 版本，pin exact version + commit SHA；升级前过 Promotion Gate（v3.0 §36 H1-H9）|
| Primary source | https://github.com/deepseek-ai/deepseek-harness |

> **P0-13 结论**：ESPHome prerelease 不得标为 production stable；DeepSeek Harness Developer Preview 已 pin exact version + 记录 known limitations。

---

## 2. 逐组件详情

### 2.1 Home Assistant

| 字段 | 值 |
|---|---|
| Component | Home Assistant (Core Container) |
| Current upstream stable | **2026.8.2**（2026-08-14，34 个 bug 修复；2026.8 于 08-05 发布）|
| Selected production baseline | 2026.8.2 |
| Selected version date | 2026-08-14 |
| Reason for pin | 逐月发布；pin 到具体 patch 保证可复现；2026.8.2 无 breaking change |
| API compatibility | REST `/api/*` + WebSocket；**auth 无 entity-scope**（见 §7）|
| Known CVEs / security notes | 无已知未修复 Critical；**长期令牌=用户全权限**（非 CVE，但为安全设计约束）|
| Tested with | 尚未实启（M0 待验）|
| Upgrade policy | 逐 patch 跟进；先 dev 后 prod；回滚靠 config 备份 |
| Last verification date | 2026-08-15（版本核实）；实启验证待 M0 |
| Primary source | https://www.home-assistant.io/blog/ + https://github.com/home-assistant/core/releases |

### 2.2 ESPHome

| 字段 | 值 |
|---|---|
| Component | ESPHome |
| Current upstream stable | 2026.7.x（patch 待定；已确认 2026.1.0、2026.4.0 存在）|
| Selected production baseline | ≥2026.4.0（M0 定精确 patch）|
| Selected version date | 2026-08（patch 待定）|
| Reason for pin | 2026.1 起 ESP32-C3 **默认 ESP-IDF 框架**；需 pin 避免框架/组件 breaking change |
| API compatibility | ESPHome Native API → HA Integration；RMT `remote_transmitter`/`remote_receiver` |
| Known CVEs / security notes | 关注 API encryption key 与 OTA 签名（2026.4 起支持 signed OTA）|
| Tested with | 未实编译（M0 装 esphome CLI 后验证 `esphome config`）|
| Upgrade policy | 季度跟进，固件重编译+OTA |
| Last verification date | 2026-08-15（版本线核实）|
| Primary source | https://esphome.io/changelog/ |

### 2.3 Ollama

| 字段 | 值 |
|---|---|
| Component | Ollama |
| Current upstream stable | **v0.32.13**（2026-08-14）|
| Selected production baseline | v0.32.x（M0 定 patch）|
| Selected version date | 2026-08 |
| Reason for pin | **v0.1 曾写 `0.5.7`，为 2024 年早期版本，已废弃**；0.32.x 含 Qwen3.8 工具调用支持 |
| API compatibility | 原生 `/api/chat`（支持 tools）、OpenAI-compatible endpoint |
| Known CVEs / security notes | 绑定 127.0.0.1；无鉴权层，仅限本机访问 |
| Tested with | 未实启（M0 待验）|
| Upgrade policy | 月度跟进；升级前 `ollama pull` 保留旧模型 |
| Last verification date | 2026-08-15 |
| Primary source | https://github.com/ollama/ollama/releases |

### 2.4 LangGraph

| 字段 | 值 |
|---|---|
| Component | LangGraph (Python) |
| Current upstream stable | **1.2.5**（2026-06-12）|
| Selected production baseline | 1.x（LTS；M0 定 patch）|
| Selected version date | 2026-06 |
| Reason for pin | LangGraph 1.0 为 LTS 风格；legacy 0.4 维护至 2026-12；选 1.x 长期稳定 |
| API compatibility | StateGraph / checkpoint / human-in-the-loop |
| Known CVEs / security notes | LangChain core 2026 有 SSRF 加固（关注升级）|
| Tested with | 未实装（M1A 装）|
| Upgrade policy | 跟随 1.x LTS 补丁 |
| Last verification date | 2026-08-15 |
| Primary source | https://pypi.org/project/langgraph/ |

### 2.5 Qwen model

| 字段 | 值 |
|---|---|
| Component | Qwen（本地模型）|
| Current upstream | qwen3 系（0.6B–235B）；qwen3.5/3.6 系已出（8b 仍为性价比点）|
| Selected production baseline | **qwen3:8b（候选）—— 非架构不变量** |
| Reason for pin | 需 benchmark 决定（见 §3）|
| API compatibility | Ollama 原生 tool calling |
| Known CVEs / security notes | 模型本身无 CVE；关注量化产物来源可信度 |
| Tested with | 未实测（M1A benchmark）|
| Upgrade policy | 由 benchmark + 硬件决定，不写死 |
| Primary source | https://ollama.com/library/qwen3 |

### 2.6 Qdrant

| 字段 | 值 |
|---|---|
| Component | Qdrant |
| Current upstream stable | **v1.18.1**（2026-05-22；v1.18.0 TurboQuant）|
| Selected production baseline | v1.18.1（**若 M1 启用**）|
| Selected version date | 2026-05-22 |
| Reason for pin | 带 API key 鉴权；**M1 默认不启用**（见 §4）|
| API compatibility | REST 6333 + gRPC 6334；`QDRANT__SERVICE__API_KEY` 鉴权 |
| Known CVEs / security notes | 无已知未修复 Critical；必须 API key + 127.0.0.1 绑定 |
| Tested with | 未实启 |
| Upgrade policy | 逐 minor 升级（1.16→1.17→1.18）|
| Last verification date | 2026-08-15 |
| Primary source | https://qdrant.tech/blog/qdrant-1.18.x/ |

### 2.7 Docker Engine / Compose

| 字段 | 值 |
|---|---|
| Component | Docker Engine + Compose |
| Current upstream stable | Engine 29.x；Compose CLI v5.1.1 |
| Selected production baseline | Engine ≥25.0；Compose v2 插件 |
| Reason for pin | HA 要求 Engine ≥23；Compose v2 废弃 `version:` 字段 |
| Known CVEs / security notes | 常规安全补丁 |
| Primary source | https://docs.docker.com/engine/release-notes/ |

### 2.8 Mosquitto

| 字段 | 值 |
|---|---|
| Component | Eclipse Mosquitto |
| Current upstream stable | 2.0.x |
| Selected production baseline | 2.0.x（**M1 禁用**，见 §6）|
| Reason for pin | 2.x 默认要求鉴权（anonymous false 更安全）|
| Known CVEs / security notes | 禁用 anonymous；启用即 password_file + ACL |
| Primary source | https://mosquitto.org/download/ |

---

## 3. 模型选型（对应 P1-2：非架构不变量）

**qwen3:8b 不是 architecture invariant。** 最终选型由 benchmark + 可用硬件决定。

建立 `ModelProvider` 抽象：

```python
# agent/llm/provider.py（接口，M1A 实现）
from typing import Protocol

class ModelProvider(Protocol):
    """本地模型提供者抽象。具体实现：OllamaProvider。"""
    async def complete(self, messages: list[dict], tools: list[dict] | None = None) -> dict: ...
    async def stream(self, messages: list[dict]) -> ...: ...
    @property
    def model_id(self) -> str: ...

class OllamaProvider:
    """Ollama 实现。M1A 落地。"""
    def __init__(self, url: str, model: str, *, temperature: float = 0.2): ...
```

**benchmark 套件（tests/benchmarks/model_tool_calling/）**，候选模型对比维度：

| 维度 | 指标 |
|---|---|
| JSON/schema 遵循率 | 输出可解析 JSON 比例 |
| 正确工具选择率 | 选对工具的比例 |
| 错误工具率 | 选错工具的比例 |
| 不安全参数率 | 越界/危险参数比例 |
| 中文指令理解 | 中文意图理解正确率 |
| 延迟 | 首 token / 总耗时 |
| tokens/sec | 吞吐 |
| 工具失败后恢复 | 失败后能否正确修正 |
| 内存占用 | VRAM/RAM |

候选模型（按硬件降序）：qwen3:14b、qwen3:8b、qwen3:4b。**基准数据在 benchmark 跑出前不作任何性能/可靠性断言。**

---

## 4. Qdrant 是否 M1 启用（对应 P1-1）

**结论：M1 默认不启用 Qdrant。**

| 记忆类型 | M1 实现 | 说明 |
|---|---|---|
| Working memory | Agent State（LangGraph 内存）| 会话内 |
| Episodic / action history | **SQLite** | 结构化查询足够 |
| Preferences | **SQLite（结构化）** | key-value/表，无需向量 |

**Qdrant 保留为 planned adapter**：只有出现明确的 semantic retrieval acceptance case（如"从历史自然语言描述中语义检索相似场景"）后才启用。避免为"有向量数据库"而无谓增加 M1 攻击面与运维复杂度。

定义 MemoryStore 接口（M1A）：

```python
# agent/memory/store.py（接口）
from typing import Protocol

class MemoryStore(Protocol):
    async def append_event(self, event: dict) -> str: ...
    async def query_events(self, *, session_id: str | None = None, limit: int = 100) -> list[dict]: ...
    async def get_preference(self, key: str) -> object | None: ...
    async def set_preference(self, key: str, value: object) -> None: ...

class SqliteMemoryStore: ...  # M1 默认实现
class QdrantMemoryStore: ...  # planned adapter，未实现
```

---

## 5. Docker 部署结构（对应 P0-8，详见 compose 文件）

- 生产基线：Compose v2 插件；**根目录 `compose.yaml`（prod 默认）+ `compose.dev.yaml`（dev override）**
- 已废弃 `version:` 字段；已废弃 `docker/compose.core.yml`（v0.1 路径冲突）
- 详见根目录 compose 文件与 CHANGELOG_FROM_V01.md

---

## 6. Mosquitto 状态

- **M1 禁用**（ADR-0009 维持）。
- 启用条件：首个需要 MQTT 的设备接入（如 Zigbee via Zigbee2MQTT）。
- 启用即 `allow_anonymous false` + password_file + ACL。

---

## 7. HA 鉴权关键事实（对应 P0-5，已核实）

**事实（官方文档 + 多方核实，2026-08-15）**：
- HA long-lived access token **继承创建它的用户的全部权限**。
- **无法**在 UI 中给 token 配 entity-level scope 或 read-only scope。
- 限制权限的唯一方式是：**创建一个 dedicated non-admin HA user（受限角色）**，再用该用户生成 token。

> v0.1 SECURITY_MODEL.md 曾出现"给 Integration Token 配 entity-level permissions"的错误 UI 描述，**已删除**（见 SECURITY_MODEL.md v0.2）。

---

## 8. 版本核实置信度说明

| 版本事实 | 置信度 | 说明 |
|---|---|---|
| HA 2026.8.2 / Ollama 0.32.13 / Qdrant 1.18.1 / LangGraph 1.2.5 | 高 | 官方 release 页面直接核实 |
| ESPHome 2026.7.x 精确 patch | 中 | 版本线已确认，精确 patch 待 M0 拉取时定 |
| Docker Compose CLI v5.1.1 | 中 | 社区教程引用，非官方 release 页直接核实 |

> 所有"已核实"标注以 Evidence Matrix 的 primary source 为准；中等置信度项在 M0 落地时补齐。

---

*本文档是版本选型的权威记录。任何版本变更需更新本表 + Evidence Matrix + 对应 compose 文件。*
