from __future__ import annotations

from quantengine_public.cli import main


def test_version_prints_success(capsys):
    assert main(["--version"]) == 0
    captured = capsys.readouterr()
    assert captured.out.strip() == "0.5.0"


def test_help_without_command_succeeds(capsys):
    assert main([]) == 0
    captured = capsys.readouterr()
    assert "Synthetic backend verification toolkit" in captured.out
