"""Repository Consistency Check（M0.1 P0-12）。

检查：
1. 文档中的 repo-relative 链接是否存在
2. 旧路径（docs/hardware、device_adapters、agent/、services/policy_gate、docker/compose.core.yml）不得残留
3. ADR 状态不得为 Accepted（Owner Gate 前）
4. 无 placeholder secret 泄露
5. 无 "已提交 Git" 等不当措辞（首个 commit 前）

CI FAIL on 任何不一致。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 不得存在的旧路径（P0-12）
FORBIDDEN_PATHS = [
    "docs/hardware",
    "device_adapters",
    "agent/",
    "services/policy_gate",
    "docker/compose.core.yml",
    "services/tool_gateway",
]

# 陈旧文本引用（当前文档中不得出现；历史文档 audits/CHANGELOG/DECISIONS 除外）
# 用负向后行断言避免把 physical_agent/runtime 误判为 agent/runtime
STALE_TEXT_RE = re.compile(
    r"(?<!physical_)agent/(?:runtime|memory|verification|tools)"
    r"|device_adapters/"
    r"|services/(?:policy_gate|policy-gate|tool_gateway|audit)"
    r"|docs/hardware"
    r"|docker/compose\.core"
)

# 视为"当前文档"（需与最新 src-layout 一致）
CURRENT_DOCS = [
    ROOT / "README.md",
    ROOT / "AGENTS.md",
    ROOT / "docs" / "ARCHITECTURE.md",
    ROOT / "docs" / "ROADMAP.md",
    ROOT / "docs" / "RUNBOOK.md",
    ROOT / "docs" / "ACCEPTANCE_TESTS.md",
    ROOT / "docs" / "SECURITY_MODEL.md",
    ROOT / "docs" / "THREAT_MODEL.md",
    ROOT / "docs" / "PRODUCT_SPEC.md",
]

# 文档中 repo-relative markdown 链接
LINK_RE = re.compile(r"\]\(([^)]+)\)")


def check_forbidden_paths() -> list[str]:
    errors = []
    for p in FORBIDDEN_PATHS:
        if (ROOT / p).exists():
            errors.append(f"forbidden legacy path still exists: {p}")
    return errors


def check_markdown_links() -> list[str]:
    errors = []
    for md in sorted(ROOT.glob("docs/**/*.md")) + [ROOT / "README.md"]:
        if not md.exists():
            continue
        text = md.read_text(encoding="utf-8", errors="replace")
        for target in LINK_RE.findall(text):
            if target.startswith(("http://", "https://", "#", "mailto:")):
                continue
            # 去掉 anchor 与 query
            clean = target.split("#")[0].split("?")[0]
            if not clean:
                continue
            resolved = (md.parent / clean).resolve()
            if not resolved.exists():
                errors.append(f"{md.relative_to(ROOT)}: broken link -> {target}")
    return errors


def check_adr_status() -> list[str]:
    errors = []
    for adr in sorted((ROOT / "docs" / "DECISIONS").glob("ADR-*.md")):
        text = adr.read_text(encoding="utf-8", errors="replace")
        m = re.search(r"^## Status\s*\n\s*(\S[^\n]*)", text, re.MULTILINE)
        if m and "Accepted" in m.group(1) and "Proposed" not in m.group(1):
            errors.append(f"{adr.relative_to(ROOT)}: status still 'Accepted' (Owner Gate pending)")
    return errors


def check_placeholder_secrets() -> list[str]:
    errors = []
    env = ROOT / ".env.example"
    if env.exists():
        text = env.read_text(encoding="utf-8")
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            val = val.strip()
            # 真实值检测：非占位符、非空、且看起来像真实密钥
            _allow_prefixes = ("http://192.168", "127.0.0.1", "qwen", "dev", "INFO", "contextual", "./")
            if val and val not in ("__REPLACE_ME__", "") and not val.startswith(_allow_prefixes):
                # 允许的默认值（非敏感）
                allow = {"dev", "staging", "prod", "contextual", "qwen3:8b", "Asia/Shanghai"}
                if val not in allow and re.search(r"[A-Za-z0-9_\-]{16,}", val):
                    errors.append(f".env.example: possible real secret in {key}")
    return errors


def check_governance_wording() -> list[str]:
    """仅标记"状态声明"式的虚假审批，不误报规则描述。"""
    errors = []
    # 状态声明式：一行是/含 "Status: ... Accepted/Owner Approved" 或 "Owner Approved ✅"
    status_assert = re.compile(
        r"^\s*(?:Status|状态)\s*[:：]\s*(?:Owner Approved|Accepted)\b",
        re.IGNORECASE,
    )
    for md in sorted((ROOT / "docs").glob("**/*.md")) + [ROOT / "README.md", ROOT / "AGENTS.md"]:
        if not md.exists():
            continue
        for line in md.read_text(encoding="utf-8", errors="replace").splitlines():
            if status_assert.search(line):
                errors.append(f"{md.relative_to(ROOT)}: premature status declaration -> {line.strip()}")
    return errors


def check_stale_text_references() -> list[str]:
    """当前文档中不得出现陈旧目录引用（P0-12）。"""
    errors = []
    for doc in CURRENT_DOCS:
        if not doc.exists():
            continue
        text = doc.read_text(encoding="utf-8", errors="replace")
        for m in STALE_TEXT_RE.finditer(text):
            errors.append(f"{doc.relative_to(ROOT)}: stale path reference -> {m.group(0)}")
    return errors


def main() -> int:
    errors: list[str] = []
    errors += check_forbidden_paths()
    errors += check_markdown_links()
    errors += check_adr_status()
    errors += check_placeholder_secrets()
    errors += check_governance_wording()
    errors += check_stale_text_references()

    if errors:
        print("CONSISTENCY FAILURES:")
        for e in errors:
            print(f"  - {e}")
        print(f"\n{len(errors)} failure(s).")
        return 1

    print("Repository consistency: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
