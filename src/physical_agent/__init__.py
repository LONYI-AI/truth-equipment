"""Physical Agent OS — Safety Kernel 与 Runtime 核心包。

本项目是 v3.0 规格（Physical Agent OS）的 M0-Foundation 实现。

核心不变量（见 docs/ARCHITECTURE.md）：
- LLM 可以提出动作，但永远不直接拥有物理设备权限。
- 所有物理动作必须经 Physical Safety Kernel（确定性、不依赖 LLM）。
"""

__version__ = "0.3.0"
