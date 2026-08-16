"""M0.1 Evidence Pipeline（P0-10）。

生成 evidence/ 下所有证据文件，全部来自真实命令输出，
不允许 Agent 手写 "PASS"。

用法：
    python scripts/verify_m0.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "evidence"
PYTHON = sys.executable


def run(cmd: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd or ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def step_pytest() -> None:
    r = run([PYTHON, "-m", "pytest", "-q"])
    write(EVIDENCE / "pytest" / "pytest.txt", r.stdout + r.stderr)

    # 用 coverage 模块（避免 pytest-cov 的 .coverage 文件被环境误删）
    cov_file = str(EVIDENCE / "pytest" / ".coverage")
    run([PYTHON, "-m", "coverage", "run", f"--data-file={cov_file}",
         "--source=physical_agent", "-m", "pytest", "-q"])
    c = run([PYTHON, "-m", "coverage", "report", f"--data-file={cov_file}"])
    write(EVIDENCE / "pytest" / "coverage.txt", c.stdout + c.stderr)


def step_lint() -> None:
    r = run([PYTHON, "-m", "ruff", "check", "src", "tests"])
    write(EVIDENCE / "lint" / "ruff.txt", r.stdout + r.stderr)


def step_typecheck() -> None:
    r = run([PYTHON, "-m", "mypy", "src"])
    write(EVIDENCE / "typecheck" / "mypy.txt", r.stdout + r.stderr)


def step_compose() -> None:
    r = run(["docker", "compose", "config"])
    write(EVIDENCE / "compose" / "compose-config.txt", r.stdout + r.stderr)


def step_secret_scan() -> None:
    # 简单的 secret 扫描（真实 grep 输出）
    patterns = [
        r"(?i)(api[_-]?key|secret|token|password|passwd)\s*[:=]\s*['\"][^'\"]{8,}['\"]",
        r"-----BEGIN (RSA|OPENSSH|EC) PRIVATE KEY-----",
        r"(?i)eyJhbGciOiJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+",  # JWT
        r"sk-[A-Za-z0-9]{20,}",  # OpenAI-style key
    ]
    hits: list[str] = []
    for pattern in patterns:
        r = run(["grep", "-rnE", pattern, "src", "tests", "docs", "harness", "hardware",
                 "compose.yaml", "compose.dev.yaml", "compose.prod.yaml", "pyproject.toml",
                 "--exclude-dir=.venv", "--exclude-dir=__pycache__"])
        if r.stdout.strip():
            hits.append(f"[pattern {pattern}]\n{r.stdout}")
    if hits:
        write(EVIDENCE / "security" / "secret-scan.txt", "SECRETS FOUND:\n\n" + "\n\n".join(hits))
    else:
        write(EVIDENCE / "security" / "secret-scan.txt", "No secrets found.\n")


def step_policy_bypass() -> None:
    r = run([PYTHON, "-m", "pytest", "tests/security/", "-q"])
    write(EVIDENCE / "security" / "policy-bypass.txt", r.stdout + r.stderr)


def step_conformance() -> None:
    r = run([PYTHON, "-m", "pytest", "tests/runtime-conformance/", "-q"])
    write(EVIDENCE / "runtime-conformance" / "report.txt", r.stdout + r.stderr)


def step_consistency() -> None:
    r = run([PYTHON, "scripts/check_repo_consistency.py"])
    write(EVIDENCE / "repository" / "consistency.txt", r.stdout + r.stderr)


def main() -> None:
    print("=== M0.1 Evidence Pipeline ===")
    for step in (step_pytest, step_lint, step_typecheck, step_compose,
                 step_secret_scan, step_policy_bypass, step_conformance, step_consistency):
        name = step.__name__.replace("step_", "")
        print(f"[{name}] ...")
        try:
            step()
        except FileNotFoundError as exc:
            print(f"  skipped (missing tool): {exc}")
    print("Done. Evidence written to evidence/")


if __name__ == "__main__":
    main()
