from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ReconcileResult:
    ok: bool
    mismatches: list[dict[str, Any]]


def reconcile_states(expected: Any, actual: Any) -> ReconcileResult:
    mismatches: list[dict[str, Any]] = []
    _compare("$", expected, actual, mismatches)
    return ReconcileResult(ok=not mismatches, mismatches=mismatches)


def _compare(path: str, expected: Any, actual: Any, mismatches: list[dict[str, Any]]) -> None:
    if isinstance(expected, dict) and isinstance(actual, dict):
        keys = sorted(set(expected) | set(actual))
        for key in keys:
            if key not in expected:
                mismatches.append(
                    {"path": f"{path}.{key}", "expected": None, "actual": actual[key], "severity": "error"}
                )
            elif key not in actual:
                mismatches.append(
                    {"path": f"{path}.{key}", "expected": expected[key], "actual": None, "severity": "error"}
                )
            else:
                _compare(f"{path}.{key}", expected[key], actual[key], mismatches)
        return

    if isinstance(expected, list) and isinstance(actual, list):
        if expected != actual:
            mismatches.append(
                {"path": path, "expected": expected, "actual": actual, "severity": "error"}
            )
        return

    if expected != actual:
        mismatches.append(
            {"path": path, "expected": expected, "actual": actual, "severity": "error"}
        )
