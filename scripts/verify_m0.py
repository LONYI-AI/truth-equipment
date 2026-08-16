"""M0.1 Evidence Pipeline（P0-10 + 强化）。

生成 evidence/ 下所有证据文件，全部来自真实命令输出，
不允许 Agent 手写 "PASS"。

强化（P0-10 整改）：任何 **mandatory failure**（步骤返回码非零、覆盖率低于阈值、
secret 命中、工具缺失等）都使本脚本以非零退出码结束（`sys.exit(1)`），
不再吞掉失败。

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

# 最低行覆盖率（百分比）。低于此阈值视为 mandatory failure。
# 注：DeepSeek Harness SDK 集成代码仅在支持平台（Linux/macOS arm64）可执行，
# 该平台门控代码已用 `# pragma: no cover` 排除；此阈值反映"可测安全内核代码"的地板。
COVERAGE_THRESHOLD = 75.0


class StepFailure(Exception):
    """一步 mandatory 校验失败。"""


def run(cmd: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd or ROOT, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def require_ok(r: subprocess.CompletedProcess, label: str) -> None:
    """返回码非零 → StepFailure（mandatory failure）。"""
    if r.returncode != 0:
        raise StepFailure(f"{label} exited {r.returncode}\n{r.stdout}\n{r.stderr}")


def _check_coverage(report: str) -> None:
    """解析 coverage report 的 TOTAL 行覆盖率，低于阈值即失败。"""
    for line in report.splitlines():
        if line.strip().startswith("TOTAL"):
            pct = line.split()[-1].rstrip("%")
            try:
                value = float(pct)
            except ValueError as exc:
                raise StepFailure(f"could not parse coverage TOTAL line: {line!r}") from exc
            if value < COVERAGE_THRESHOLD:
                raise StepFailure(f"coverage {value}% below threshold {COVERAGE_THRESHOLD}%")
            return
    raise StepFailure("coverage TOTAL line not found")


def step_pytest() -> None:
    r = run([PYTHON, "-m", "pytest", "-q", "-m", "not harness_smoke"])
    write(EVIDENCE / "pytest" / "pytest.txt", r.stdout + r.stderr)
    require_ok(r, "pytest")

    # 用 coverage 模块（避免 pytest-cov 的 .coverage 文件被环境误删）
    cov_file = str(EVIDENCE / "pytest" / ".coverage")
    rc = run([PYTHON, "-m", "coverage", "run", f"--data-file={cov_file}",
              "--source=physical_agent", "-m", "pytest", "-q", "-m", "not harness_smoke"])
    require_ok(rc, "coverage run")
    c = run([PYTHON, "-m", "coverage", "report", f"--data-file={cov_file}"])
    write(EVIDENCE / "pytest" / "coverage.txt", c.stdout + c.stderr)
    require_ok(c, "coverage report")
    _check_coverage(c.stdout)


def step_lint() -> None:
    r = run([PYTHON, "-m", "ruff", "check", "src", "tests"])
    write(EVIDENCE / "lint" / "ruff.txt", r.stdout + r.stderr)
    require_ok(r, "ruff")


def step_typecheck() -> None:
    r = run([PYTHON, "-m", "mypy", "src"])
    write(EVIDENCE / "typecheck" / "mypy.txt", r.stdout + r.stderr)
    require_ok(r, "mypy")


def step_compose() -> None:
    r = run(["docker", "compose", "config"])
    write(EVIDENCE / "compose" / "compose-config.txt", r.stdout + r.stderr)
    require_ok(r, "docker compose config")


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
        raise StepFailure("secrets found in repository (see evidence/security/secret-scan.txt)")
    write(EVIDENCE / "security" / "secret-scan.txt", "No secrets found.\n")


def step_policy_bypass() -> None:
    r = run([PYTHON, "-m", "pytest", "tests/security/", "-q"])
    write(EVIDENCE / "security" / "policy-bypass.txt", r.stdout + r.stderr)
    require_ok(r, "policy bypass tests")


def step_conformance() -> None:
    r = run([PYTHON, "-m", "pytest", "tests/runtime-conformance/", "-q", "-m", "not harness_smoke"])
    write(EVIDENCE / "runtime-conformance" / "report.txt", r.stdout + r.stderr)
    require_ok(r, "runtime conformance")


def step_harness_smoke() -> None:
    # 真实 DeepSeek Harness smoke test：支持平台必须真实运行；不支持平台 skip（仍 exit 0）
    r = run([PYTHON, "-m", "pytest", "-m", "harness_smoke", "-q"])
    write(EVIDENCE / "runtime-conformance" / "harness-smoke.txt", r.stdout + r.stderr)
    require_ok(r, "DeepSeek Harness smoke test")


def step_consistency() -> None:
    r = run([PYTHON, "scripts/check_repo_consistency.py"])
    write(EVIDENCE / "repository" / "consistency.txt", r.stdout + r.stderr)
    require_ok(r, "repository consistency")


STEPS = [
    ("pytest", step_pytest),
    ("lint", step_lint),
    ("typecheck", step_typecheck),
    ("compose", step_compose),
    ("secret_scan", step_secret_scan),
    ("policy_bypass", step_policy_bypass),
    ("conformance", step_conformance),
    ("harness_smoke", step_harness_smoke),
    ("consistency", step_consistency),
]


def main() -> int:
    print("=== M0.1 Evidence Pipeline ===", flush=True)
    failures: list[str] = []
    for name, fn in STEPS:
        print(f"[{name}] ...", flush=True)
        try:
            fn()
            print(f"  PASS")
        except StepFailure as exc:
            failures.append(name)
            print(f"  FAIL: {exc}")
        except FileNotFoundError as exc:
            failures.append(name)
            print(f"  FAIL: missing tool: {exc}")

    print()
    if failures:
        print(f"MANDATORY FAILURES: {', '.join(failures)}")
        print("Evidence pipeline FAILED.")
        return 1
    print("Evidence pipeline OK. Evidence written to evidence/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
