from __future__ import annotations

from quantengine_public.cli import main


ROOT = __import__("pathlib").Path(__file__).resolve().parents[1]


def test_version_prints_success(capsys):
    assert main(["--version"]) == 0
    captured = capsys.readouterr()
    assert captured.out.strip() == "0.6.0"


def test_help_without_command_succeeds(capsys):
    assert main([]) == 0
    captured = capsys.readouterr()
    assert "Evidence-controlled AI software delivery" in captured.out
    assert "Synthetic backend verification toolkit" not in captured.out


def test_verify_native_canary_command_reports_bounded_pass(capsys):
    bundle = ROOT / "examples" / "native_role_canary_v1"

    assert main(["verify-native-canary", "--bundle-dir", str(bundle)]) == 0
    result = __import__("json").loads(capsys.readouterr().out)
    assert result["status"] == "PASS"
    assert result["owner_attested"] is True
    assert result["provider_signed"] is False


def test_verify_native_canary_command_fails_closed_for_missing_bundle(
    tmp_path, capsys
):
    assert main(["verify-native-canary", "--bundle-dir", str(tmp_path)]) == 1
    result = __import__("json").loads(capsys.readouterr().out)
    assert result["status"] == "FAIL_CLOSED"
