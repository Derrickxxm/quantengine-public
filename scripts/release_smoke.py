"""Build, clean-install, and verify the public package version and CLI."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import venv
from pathlib import Path


def _run(*args: str) -> str:
    result = subprocess.run(args, check=True, capture_output=True, text=True)
    return result.stdout.strip()


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / "src"))
    from quantengine_public import __version__ as source_version

    with tempfile.TemporaryDirectory(prefix="quantengine-public-release-") as directory:
        work = Path(directory)
        wheel_dir = work / "wheel"
        wheel_dir.mkdir()
        _run(
            sys.executable,
            "-m",
            "pip",
            "wheel",
            "--no-deps",
            "--wheel-dir",
            str(wheel_dir),
            str(root),
        )
        wheels = sorted(wheel_dir.glob("quantengine_public-*.whl"))
        if len(wheels) != 1:
            raise RuntimeError(f"expected one wheel, found {wheels}")

        venv_dir = work / "venv"
        venv.EnvBuilder(with_pip=True, clear=True).create(venv_dir)
        venv_python = venv_dir / "bin" / "python"
        cli = venv_dir / "bin" / "quantengine-public"
        _run(str(venv_python), "-m", "pip", "install", "--no-deps", str(wheels[0]))
        installed_version = _run(
            str(venv_python),
            "-c",
            "from importlib.metadata import version; print(version('quantengine-public'))",
        )
        cli_version = _run(str(cli), "--version")

    if {source_version, installed_version, cli_version} != {source_version}:
        raise RuntimeError(
            "version mismatch: "
            f"source={source_version} installed={installed_version} cli={cli_version}"
        )
    print(f"release smoke PASS: quantengine-public {source_version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
