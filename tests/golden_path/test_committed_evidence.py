from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import jsonschema
import pytest

from quantengine_public.delivery.golden_path import GOLDEN_PATH_FILENAMES
from quantengine_public.delivery.identity import (
    ARTIFACT_PRODUCERS,
    content_digest,
    verify_artifact,
    verify_artifact_chain,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def test_public_inventory_matches_runtime_artifact_ownership():
    inventory = json.loads(
        (REPOSITORY_ROOT / "contracts" / "public_delivery" / "golden_path.v1.json").read_text(
            encoding="utf-8"
        )
    )

    assert inventory["artifacts"] == [
        artifact_type
        for artifact_type in ARTIFACT_PRODUCERS
        if artifact_type != "public_delivery.block_receipt"
    ]
    assert inventory["artifact_producers"] == {
        artifact_type: sorted(producers)
        for artifact_type, producers in ARTIFACT_PRODUCERS.items()
        if artifact_type != "public_delivery.block_receipt"
    }


def test_committed_artifacts_satisfy_public_json_schema():
    schema = json.loads(
        (REPOSITORY_ROOT / "contracts" / "public_delivery" / "artifact.v1.schema.json").read_text(
            encoding="utf-8"
        )
    )
    evidence = [
        path
        for path in (REPOSITORY_ROOT / "examples" / "golden_path").rglob("*.json")
        if json.loads(path.read_text(encoding="utf-8")).get("schema_version")
        == "quantengine_public.delivery_artifact.v1"
    ]

    assert evidence
    for path in evidence:
        jsonschema.validate(json.loads(path.read_text(encoding="utf-8")), schema)

    invalid = deepcopy(
        json.loads(
            (
                REPOSITORY_ROOT
                / "examples"
                / "golden_path"
                / "negative"
                / "missing-acceptance"
                / "block_receipt.json"
            ).read_text(encoding="utf-8")
        )
    )
    invalid["authority"]["paper_allowed"] = True
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(invalid, schema)


def test_committed_golden_path_evidence_is_complete_and_connected():
    evidence_dir = REPOSITORY_ROOT / "examples" / "golden_path" / "evidence"
    artifacts = [
        json.loads((evidence_dir / filename).read_text(encoding="utf-8"))
        for filename in GOLDEN_PATH_FILENAMES
    ]

    known_digests: set[str] = set()
    for artifact in artifacts:
        assert verify_artifact(artifact) == []
        assert all(edge["artifact_digest"] in known_digests for edge in artifact["upstream"])
        known_digests.add(artifact["artifact_digest"])

    assert verify_artifact_chain(artifacts) == []

    assert artifacts[-2]["artifact_type"] == "public_delivery.release_verdict"
    assert artifacts[-2]["status"] == "PASS"
    assert artifacts[-1]["artifact_type"] == "public_delivery.aar"
    assert artifacts[-1]["payload"]["negative_evidence_retained"] is True


def test_committed_negative_receipts_remain_valid_and_fail_closed():
    negative_dir = REPOSITORY_ROOT / "examples" / "golden_path" / "negative"
    receipts = sorted(negative_dir.glob("*/block_receipt.json"))

    assert len(receipts) == 9
    for path in receipts:
        artifact = json.loads(path.read_text(encoding="utf-8"))
        assert verify_artifact(artifact) == []
        assert artifact["status"] in {"BLOCKED", "EVIDENCE_GAP", "FAIL_CLOSED"}
        assert artifact["authority"] == {
            "deployment_allowed": False,
            "paper_allowed": False,
            "real_allowed": False,
        }
        prefix = [
            json.loads((path.parent / filename).read_text(encoding="utf-8"))
            for filename in GOLDEN_PATH_FILENAMES
            if (path.parent / filename).exists()
        ]
        assert verify_artifact_chain([*prefix, artifact]) == []
        if artifact["payload"]["stage"] not in {"objective_gate", "architecture_gate"}:
            assert artifact["upstream"]
        request = json.loads((path.parent / "request.json").read_text(encoding="utf-8"))
        assert artifact["payload"]["request_digest"] == content_digest(request)
