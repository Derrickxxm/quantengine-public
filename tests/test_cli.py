from __future__ import annotations

from quantengine_public.cli import main


def test_version_prints_success(capsys):
    assert main(["--version"]) == 0
    captured = capsys.readouterr()
    assert captured.out.strip() == "0.5.2"


def test_help_without_command_succeeds(capsys):
    assert main([]) == 0
    captured = capsys.readouterr()
    assert "Evidence-controlled AI software delivery" in captured.out
    assert "Synthetic backend verification toolkit" not in captured.out
