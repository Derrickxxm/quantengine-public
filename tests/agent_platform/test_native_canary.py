from __future__ import annotations

import json
import shutil
from pathlib import Path

import jsonschema
import pytest

from quantengine_public.agent_platform.native_canary import (
    MANIFEST_FILE,
    NativeCanaryError,
    canonical_manifest_digest,
    validate_native_canary_manifest,
    verify_native_canary_bundle,
)


ROOT = Path(__file__).resolve().parents[2]
BUNDLE = ROOT / "examples" / "native_role_canary_v1"
SCHEMA = (
    ROOT
    / "contracts"
    / "public_delivery"
    / "native_role_canary_manifest.v1.schema.json"
)


def _manifest(path: Path = BUNDLE) -> dict:
    return json.loads((path / MANIFEST_FILE).read_text())


def _refresh_manifest_digest(value: dict) -> None:
    body = {key: item for key, item in value.items() if key != "manifest_digest"}
    value["manifest_digest"] = canonical_manifest_digest(body)


def test_published_owner_attested_bundle_verifies_offline() -> None:
    result = verify_native_canary_bundle(BUNDLE)

    assert result["status"] == "PASS"
    assert result["owner_attested"] is True
    assert result["provider_signed"] is False
    assert result["continuous_native_run"] is False
    assert result["independently_replayable_provider_execution"] is False
    assert result["authority"] == {
        "deployment_allowed": False,
        "paper_allowed": False,
        "real_allowed": False,
    }


def test_published_manifest_satisfies_public_json_schema() -> None:
    jsonschema.validate(_manifest(), json.loads(SCHEMA.read_text()))


def test_changed_evidence_bytes_fail_closed(tmp_path: Path) -> None:
    copied = tmp_path / "bundle"
    shutil.copytree(BUNDLE, copied)
    output = copied / "evidence" / "outputs" / "03_development.json"
    output.write_text(output.read_text() + "\n")

    with pytest.raises(NativeCanaryError, match="artifact digest mismatch"):
        verify_native_canary_bundle(copied)


def test_changed_manifest_without_owner_resign_fails_signature(tmp_path: Path) -> None:
    copied = tmp_path / "bundle"
    shutil.copytree(BUNDLE, copied)
    path = copied / MANIFEST_FILE
    value = json.loads(path.read_text())
    value["trust"]["provider_signed"] = True
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")

    with pytest.raises(NativeCanaryError, match="signature verification failed"):
        verify_native_canary_bundle(copied)


def test_changed_owner_trust_root_fails_before_signature(tmp_path: Path) -> None:
    copied = tmp_path / "bundle"
    shutil.copytree(BUNDLE, copied)
    signers = copied / "owner_allowed_signers"
    signers.write_text(signers.read_text() + "\n")

    with pytest.raises(NativeCanaryError, match="owner trust root mismatch"):
        verify_native_canary_bundle(copied)


def test_semantic_validator_rejects_provider_signature_claim() -> None:
    value = _manifest()
    value["trust"]["provider_signed"] = True
    _refresh_manifest_digest(value)

    with pytest.raises(NativeCanaryError, match="trust boundary mismatch"):
        validate_native_canary_manifest(value, bundle_dir=BUNDLE)


def test_semantic_validation_does_not_claim_owner_authentication() -> None:
    result = validate_native_canary_manifest(_manifest(), bundle_dir=BUNDLE)

    assert result["status"] == "SEMANTIC_PASS"
    assert result["owner_attested"] is False


def test_semantic_validator_rejects_authority_injection() -> None:
    value = _manifest()
    value["authority"]["deployment_allowed"] = True
    _refresh_manifest_digest(value)

    with pytest.raises(NativeCanaryError, match="authority must remain zero"):
        validate_native_canary_manifest(value, bundle_dir=BUNDLE)


def test_semantic_validator_rejects_unlisted_or_escaping_artifact() -> None:
    value = _manifest()
    value["artifacts"][0]["path"] = "../source_identity.json"
    _refresh_manifest_digest(value)

    with pytest.raises(NativeCanaryError, match="artifact path escapes bundle"):
        validate_native_canary_manifest(value, bundle_dir=BUNDLE)


def test_six_valid_looking_receipts_without_signature_are_not_attested(
    tmp_path: Path,
) -> None:
    copied = tmp_path / "bundle"
    shutil.copytree(BUNDLE, copied)
    (copied / f"{MANIFEST_FILE}.sig").unlink()

    with pytest.raises(NativeCanaryError, match="file unavailable or unsafe"):
        verify_native_canary_bundle(copied)


def test_missing_ssh_keygen_fails_closed() -> None:
    with pytest.raises(NativeCanaryError, match="ssh-keygen is required"):
        verify_native_canary_bundle(BUNDLE, ssh_keygen="missing-ssh-keygen")
