from __future__ import annotations

from copy import deepcopy

import pytest

from quantengine_public.delivery.identity import (
    ArtifactContractError,
    artifact_ref,
    verify_artifact_chain,
    seal_artifact,
    verify_artifact,
)


def _runtime_artifact():
    return seal_artifact(
        artifact_type="public_delivery.runtime_evidence",
        producer="quantengine_public",
        status="PASS",
        upstream=[],
        payload={"run": "runtime-001"},
    )


def _quality_artifact(runtime, *, consume_runtime=True):
    return seal_artifact(
        artifact_type="public_delivery.quality_verdict",
        producer="public_quality_shield",
        status="PASS",
        upstream=[artifact_ref(runtime)] if consume_runtime else [],
        payload={"independent": True},
    )


def _release_artifact(quality, runtime, *, producer="public_release_controller", upstream=None, authority=None):
    return seal_artifact(
        artifact_type="public_delivery.release_verdict",
        producer=producer,
        status="PASS",
        upstream=upstream if upstream is not None else [artifact_ref(quality), artifact_ref(runtime)],
        payload={"decision_basis": ["public_delivery.quality_verdict", "public_delivery.runtime_evidence"]},
        authority=authority
        or {"deployment_allowed": False, "paper_allowed": True, "real_allowed": False},
    )


def test_release_topology_rejects_empty_upstream_in_both_verifiers():
    runtime = _runtime_artifact()
    quality = _quality_artifact(runtime)
    release = _release_artifact(quality, runtime, upstream=[])

    assert verify_artifact(release)
    assert verify_artifact_chain([runtime, quality, release])


def test_release_topology_rejects_missing_runtime_in_both_verifiers():
    runtime = _runtime_artifact()
    quality = _quality_artifact(runtime)
    release = _release_artifact(quality, runtime, upstream=[artifact_ref(quality)])

    assert verify_artifact(release)
    assert verify_artifact_chain([runtime, quality, release])


def test_release_topology_rejects_missing_independent_quality_in_both_verifiers():
    runtime = _runtime_artifact()
    release = _release_artifact(
        _quality_artifact(runtime),
        runtime,
        upstream=[artifact_ref(runtime)],
    )

    assert verify_artifact(release)
    assert verify_artifact_chain([runtime, release])


def test_release_topology_rejects_wrong_release_producer_in_both_verifiers():
    runtime = _runtime_artifact()
    quality = _quality_artifact(runtime)
    release = _release_artifact(quality, runtime, producer="quantengine_public")

    assert verify_artifact(release)
    assert verify_artifact_chain([runtime, quality, release])


def test_quality_topology_rejects_quality_without_runtime_in_both_verifiers():
    runtime = _runtime_artifact()
    quality = _quality_artifact(runtime, consume_runtime=False)
    release = _release_artifact(
        quality,
        runtime,
        upstream=[
            {"artifact_type": quality["artifact_type"], "artifact_digest": quality["artifact_digest"]},
            artifact_ref(runtime),
        ],
    )

    assert verify_artifact(quality)
    assert verify_artifact_chain([runtime, quality, release])


def test_release_chain_rejects_right_digest_with_wrong_upstream_type():
    runtime = _runtime_artifact()
    quality = _quality_artifact(runtime)
    release = _release_artifact(
        quality,
        runtime,
        upstream=[
            {"artifact_type": "public_delivery.quality_verdict", "artifact_digest": runtime["artifact_digest"]},
            artifact_ref(runtime),
        ],
    )

    assert verify_artifact(release) == []
    assert verify_artifact_chain([runtime, quality, release])


def test_nonzero_authority_requires_complete_release_topology():
    runtime = _runtime_artifact()
    quality = _quality_artifact(runtime, consume_runtime=False)
    release = _release_artifact(
        quality,
        runtime,
        upstream=[
            {"artifact_type": quality["artifact_type"], "artifact_digest": quality["artifact_digest"]},
            artifact_ref(runtime),
        ],
    )

    assert verify_artifact_chain([runtime, quality, release])


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
    assert verify_artifact(release)

    with pytest.raises(ArtifactContractError, match="invalid_upstream"):
        seal_artifact(
            artifact_type="public_delivery.architecture_packet",
            producer="public_architecture_agent",
            status="READY",
            upstream=[{"artifact_type": "public_delivery.plane_task"}],
            payload={},
        )
