from __future__ import annotations

from copy import deepcopy

import pytest

from quantengine_public.delivery.identity import (
    ArtifactContractError,
    verify_artifact_chain,
    seal_artifact,
    verify_artifact,
)


def test_sealed_artifact_digest_is_recomputable_and_tamper_evident():
    artifact = seal_artifact(
        artifact_type="public_delivery.ogsm",
        producer="owner_fixture",
        status="READY",
        upstream=[],
        payload={"objective": "Prove one public delivery path"},
    )

    assert verify_artifact(artifact) == []

    tampered = deepcopy(artifact)
    tampered["payload"]["objective"] = "Changed after approval"

    assert verify_artifact(tampered) == ["artifact_digest_mismatch"]


def test_artifact_contract_rejects_open_status_and_unbound_upstream():
    with pytest.raises(ArtifactContractError, match="unsupported_status"):
        seal_artifact(
            artifact_type="public_delivery.ogsm",
            producer="owner_fixture",
            status="LOOKS_GOOD",
            upstream=[],
            payload={},
        )


def test_chain_verifier_rejects_missing_upstream_and_wrong_producer():
    root = seal_artifact(
        artifact_type="public_delivery.ogsm",
        producer="owner_fixture",
        status="READY",
        upstream=[],
        payload={},
    )
    wrong_producer = seal_artifact(
        artifact_type="public_delivery.plane_task",
        producer="public_test_agent",
        status="READY",
        upstream=[
            {
                "artifact_type": root["artifact_type"],
                "artifact_digest": "0" * 64,
            }
        ],
        payload={},
    )

    errors = verify_artifact_chain([root, wrong_producer])

    assert "unknown_upstream:public_delivery.plane_task:0000000000000000000000000000000000000000000000000000000000000000" in errors
    assert "producer_mismatch:public_delivery.plane_task:public_test_agent" in errors


def test_chain_verifier_rejects_upstream_type_aliasing():
    root = seal_artifact(
        artifact_type="public_delivery.ogsm",
        producer="owner_fixture",
        status="READY",
        upstream=[],
        payload={},
    )
    aliased_edge = seal_artifact(
        artifact_type="public_delivery.plane_task",
        producer="public_plane_fixture",
        status="READY",
        upstream=[
            {
                "artifact_type": "public_delivery.test_result",
                "artifact_digest": root["artifact_digest"],
            }
        ],
        payload={},
    )

    errors = verify_artifact_chain([root, aliased_edge])

    assert (
        "upstream_type_mismatch:public_delivery.plane_task:"
        f"public_delivery.test_result:public_delivery.ogsm:{root['artifact_digest']}"
    ) in errors


@pytest.mark.parametrize(
    ("artifact_type", "status"),
    [
        ("public_delivery.block_receipt", "BLOCKED"),
        ("public_delivery.qcs_receipt", "PASS"),
        ("public_delivery.release_verdict", "FAIL_CLOSED"),
    ],
)
def test_only_passing_release_verdict_can_carry_authority(artifact_type, status):
    with pytest.raises(ArtifactContractError, match="invalid_authority_semantics"):
        seal_artifact(
            artifact_type=artifact_type,
            producer="public_qcs",
            status=status,
            upstream=[],
            payload={},
            authority={
                "deployment_allowed": False,
                "paper_allowed": True,
                "real_allowed": False,
            },
        )

    release = seal_artifact(
        artifact_type="public_delivery.release_verdict",
        producer="quantengine_public",
        status="PASS",
        upstream=[],
        payload={},
        authority={
            "deployment_allowed": False,
            "paper_allowed": True,
            "real_allowed": False,
        },
    )
    assert verify_artifact(release) == []

    with pytest.raises(ArtifactContractError, match="invalid_upstream"):
        seal_artifact(
            artifact_type="public_delivery.architecture_packet",
            producer="public_architecture_agent",
            status="READY",
            upstream=[{"artifact_type": "public_delivery.plane_task"}],
            payload={},
        )
