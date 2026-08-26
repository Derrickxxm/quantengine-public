from __future__ import annotations

import asyncio

import pytest

from quantengine_public.agent_platform.contracts import ArtifactRef, GraphIdentity, SourceIdentity, TaskSnapshot
from quantengine_public.agent_platform.vertical_slice import (
    ReleaseTopologyError,
    SliceArtifact,
    VerticalSliceRunner,
    derive_release,
)


agents = pytest.importorskip("agents", reason="install openai-agents==0.22.0")


@pytest.fixture
def identities():
    source = SourceIdentity("quantengine-public", "codex/test", "a" * 40, "b" * 64)
    task = TaskSnapshot(
        task_id="TASKSYS-1262", task_revision="r1", objective="close release topology",
        measures=("zero false PASS",), acceptance_criteria=("exact topology",),
        non_goals=("deployment", "Paper", "Replay", "Real", "M7", "M8"),
        approved_scope=("src/quantengine_public/agent_platform",), required_approvals=(),
        source_reference=source.identity_digest,
    )
    return task, source, GraphIdentity("graph-r1", source.commit, "c" * 64)


@pytest.fixture
def vertical_result(tmp_path, identities):
    task, source, graph = identities
    runner = VerticalSliceRunner(tmp_path / "vertical.sqlite3", task=task, source=source, graph=graph)
    result = asyncio.run(runner.run())
    runner.close()
    return result


def test_vertical_slice_runs_all_roles_and_reopens(tmp_path, identities):
    task, source, graph = identities
    db = tmp_path / "vertical.sqlite3"
    first = VerticalSliceRunner(db, task=task, source=source, graph=graph)
    paused = asyncio.run(first.run(stop_after="ARCHITECTURE_READY"))
    assert paused.state.state == "ARCHITECTURE_READY"
    first.close()

    resumed = VerticalSliceRunner(db, task=task, source=source, graph=graph)
    result = asyncio.run(resumed.run())
    assert result.state.state == "RELEASE_DECIDED"
    assert [run.role for run in result.runs] == [
        "Architecture",
        "Test",
        "Development",
        "Test",
        "Ops",
        "Quality",
    ]
    assert result.release["status"] == "PASS"
    assert result.release["authority"] == {
        "deployment_allowed": False,
        "paper_allowed": False,
        "real_allowed": False,
    }
    assert all(h.graph_identity == graph.identity_digest for h in result.handoffs)
    resumed.close()


def test_release_rejects_forged_producer_type_or_digest(vertical_result):
    evidence = list(vertical_result.evidence)
    with pytest.raises(ReleaseTopologyError):
        derive_release(
            task_id=vertical_result.task.task_id,
            source_identity=vertical_result.source.identity_digest,
            evidence=evidence,
            quality_producer="attacker",
        )
    forged = [item for item in evidence if item.artifact_type.endswith("runtime_evidence")][0]
    assert ArtifactRef("public_delivery.test_result", forged.upstream[0].artifact_digest) in forged.upstream


def test_release_attack_suite_rejects_missing_edges_wrong_digest_and_authority(vertical_result):
    evidence = list(vertical_result.evidence)
    with pytest.raises(ReleaseTopologyError, match="(incomplete|requires_exactly_one|invalid_evidence_chain)"):
        derive_release(
            task_id=vertical_result.task.task_id,
            source_identity=vertical_result.source.identity_digest,
            evidence=evidence[:-1],
        )

    quality = next(item for item in evidence if item.artifact_type.endswith("quality_verdict"))
    forged_quality = SliceArtifact.create(
        task_id=quality.task_id,
        source_identity=quality.source_identity,
        context_digest=quality.context_digest,
        graph_identity=quality.graph_identity,
        artifact_type=quality.artifact_type,
        producer=quality.producer,
        status=quality.status,
        upstream=(ArtifactRef("runtime_evidence", "0" * 64),),
        payload=quality.payload,
    )
    with pytest.raises(ReleaseTopologyError, match="(quality_runtime|invalid_evidence_chain)"):
        derive_release(
            task_id=vertical_result.task.task_id,
            source_identity=vertical_result.source.identity_digest,
            evidence=[forged_quality if item is quality else item for item in evidence],
        )

    forged_authority = quality.to_dict()
    forged_authority["authority"] = {"deployment_allowed": True, "paper_allowed": False, "real_allowed": False}
    with pytest.raises(ReleaseTopologyError, match="invalid_artifact"):
        SliceArtifact.from_dict(forged_authority)
