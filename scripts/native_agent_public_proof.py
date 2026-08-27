"""Generate and verify the bounded M8 Native-Agent public proof."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from pathlib import Path

from quantengine_public.agent_platform.public_proof import generate_public_proof, verify_public_proof


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ("git", "-C", str(root), *args), check=True, capture_output=True, text=True
    ).stdout.strip()


def _index_digest(root: Path, *paths: str) -> str:
    listing = _git(root, "ls-files", "-s", "--", *paths)
    return hashlib.sha256((listing + "\n").encode("utf-8")).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-dir", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    commit = _git(root, "rev-parse", "HEAD")
    branch = (
        os.environ.get("GITHUB_HEAD_REF")
        or os.environ.get("GITHUB_REF_NAME")
        or _git(root, "rev-parse", "--abbrev-ref", "HEAD")
    )
    manifest = generate_public_proof(
        args.artifact_dir,
        repository="quantengine-public",
        branch=branch,
        commit=commit,
        tree_digest=_index_digest(root, "."),
        graph_revision="agent-platform-source-set-v1",
        graph_digest=_index_digest(
            root,
            "src/quantengine_public/agent_platform",
            "tests/agent_platform",
        ),
    )
    verify_public_proof(args.artifact_dir, expected_commit=commit)
    print(
        json.dumps(
            {
                "status": "PASS",
                "proof_digest": manifest["proof_digest"],
                "source_commit": commit,
                "authority": manifest["authority"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
