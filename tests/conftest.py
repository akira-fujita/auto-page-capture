# tests/conftest.py
"""テスト全体の安全ガード"""

import subprocess

import pytest
from PyQt6.QtWidgets import QMessageBox

_real_run = subprocess.run
_real_popen = subprocess.Popen


def _is_claude_command(cmd) -> bool:
    """claude CLI の呼び出しかどうか"""
    if isinstance(cmd, (list, tuple)) and cmd:
        return str(cmd[0]).endswith("claude")
    if isinstance(cmd, str):
        return cmd.split(" ")[0].endswith("claude")
    return False


@pytest.fixture(autouse=True)
def block_real_claude_cli(monkeypatch):
    """テストから実際の claude CLI を呼ばせない

    課金枠の消費と、応答待ちによる長時間ハングを防ぐ。
    claude 以外のコマンド（open など）はそのまま通す。
    """

    def guarded_run(cmd, *args, **kwargs):
        if _is_claude_command(cmd):
            raise AssertionError(f"テスト中に実 claude CLI が呼ばれました: {cmd}")
        return _real_run(cmd, *args, **kwargs)

    def guarded_popen(cmd, *args, **kwargs):
        if _is_claude_command(cmd):
            raise AssertionError(f"テスト中に実 claude CLI が呼ばれました: {cmd}")
        return _real_popen(cmd, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", guarded_run)
    monkeypatch.setattr(subprocess, "Popen", guarded_popen)


@pytest.fixture(autouse=True)
def block_modal_dialogs(monkeypatch):
    """未パッチのモーダルダイアログでテストが止まらないようにする

    個別テストが monkeypatch し直せばそちらが優先される。
    """
    monkeypatch.setattr(QMessageBox, "critical", lambda *a, **kw: None)
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **kw: None)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **kw: None)
    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **kw: QMessageBox.StandardButton.No
    )
