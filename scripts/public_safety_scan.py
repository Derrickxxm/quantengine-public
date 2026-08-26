#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path


RULES: dict[str, re.Pattern[str]] = {
    "credential_like": re.compile(r"(?i)(api[_-]?key|secret|password|token)\s*[:=]\s*['\"]?[A-Za-z0-9_\-]{12,}"),
    "private_key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "database_url": re.compile(r"(?i)\b(?:mongodb|postgres(?:ql)?|mysql|redis)://"),
    "absolute_user_path": re.compile("/" + "Users" + r"/[A-Za-z0-9_.-]+/"),
    "private_repository_locator": re.compile(
        r"(?i)(?:git@github\.com:|https://github\.com/)Derrickxxm/(?:"
        + "|".join(["Quant" + "Lab", "Quant" + "Strategies"])
        + r")(?:\.git|/|\b)"
    ),
    "local_model_runtime": re.compile(r"\b(?:" + "|".join(["Q" + "wen", "Stu" + "dio"]) + r")\b"),
    "real_exchange_symbol": re.compile(r"\b(?:" + "|".join(["BTC" + "USDT", "ETH" + "USDT", "BNB" + "USDT"]) + r")\b"),
    "private_network": re.compile(r"\b(?:10|192\.168|172\.(?:1[6-9]|2[0-9]|3[0-1]))\.\d{1,3}\.\d{1,3}\b"),
}

SKIP_PATH_PARTS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "artifacts",
    "build",
    "dist",
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Scan tracked public files for disallowed content classes.")
    parser.add_argument("--history", action="store_true", help="Scan all reachable git commits as well as current files.")
    args = parser.parse_args(argv)

    failures = scan_current_tree(Path.cwd())
    if args.history:
        failures.extend(scan_history())

    if failures:
        for failure in failures:
            print(f"{failure.scope}\t{failure.location}\t{failure.rule_id}")
        return 1
    print("public safety scan passed")
    return 0


class Failure:
    def __init__(self, scope: str, location: str, rule_id: str) -> None:
        self.scope = scope
        self.location = location
        self.rule_id = rule_id


def scan_current_tree(root: Path) -> list[Failure]:
    failures: list[Failure] = []
    for relative_path in tracked_files(root):
        if should_skip(relative_path):
            continue
        path = root / relative_path
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for rule_id, pattern in RULES.items():
            if pattern.search(text):
                failures.append(Failure("current", relative_path, rule_id))
    return failures


def scan_history() -> list[Failure]:
    failures: list[Failure] = []
    commits = run_git(["rev-list", "--all"]).splitlines()
    for commit in commits:
        files = run_git(["ls-tree", "-r", "--name-only", commit]).splitlines()
        for relative_path in files:
            if should_skip(relative_path):
                continue
            blob = run_git(["show", f"{commit}:{relative_path}"], check=False)
            if not blob:
                continue
            for rule_id, pattern in RULES.items():
                if pattern.search(blob):
                    failures.append(Failure("history", f"{commit[:12]}:{relative_path}", rule_id))
    return failures


def tracked_files(root: Path) -> list[str]:
    output = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=root,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return output.stdout.splitlines()


def should_skip(relative_path: str) -> bool:
    return any(part in SKIP_PATH_PARTS for part in Path(relative_path).parts)


def run_git(args: list[str], *, check: bool = True) -> str:
    result = subprocess.run(
        ["git", *args],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    if check and result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed")
    return result.stdout if result.returncode == 0 else ""


if __name__ == "__main__":
    raise SystemExit(main())
