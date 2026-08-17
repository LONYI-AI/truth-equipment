"""M1A Simulation CLI smoke（pytest 层）：真实走完整闭环，不另拼 demo 链路。"""

from __future__ import annotations

from physical_agent.cli import main


async def test_cli_main_loop_success(monkeypatch, capsys):
    """输入自然语言 → 审批批准 → SIMULATION 执行完成 → 退出。"""
    inputs = iter(["把客厅空调调到26度", "y", "exit"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(inputs))

    exit_code = await main()

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "此动作需要批准" in out
    assert "SIMULATION 执行完成" in out
    assert "V2 satisfied" in out


async def test_cli_main_loop_reject(monkeypatch, capsys):
    """审批拒绝 → 不执行 → 退出。"""
    inputs = iter(["开空调", "n", "exit"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(inputs))

    exit_code = await main()

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "此动作需要批准" in out
    assert "policy rejected" in out


async def test_cli_main_loop_eof_exits(monkeypatch, capsys):
    """EOF 立即退出（无输入）。"""

    def _eof(_prompt=""):
        raise EOFError

    monkeypatch.setattr("builtins.input", _eof)

    exit_code = await main()
    assert exit_code == 0
