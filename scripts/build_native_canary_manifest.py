"""Owner-authorized builder for the fixed public DEC-0031 canary bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

from quantengine_public.agent_platform.native_canary import (
    ALLOWED_SIGNERS_FILE,
    EVIDENCE_CLASS,
    MANIFEST_FILE,
    MANIFEST_SCHEMA,
    OWNER_IDENTITY,
    OWNER_KEY_FINGERPRINT,
    SIGNATURE_FILE,
    SIGNATURE_NAMESPACE,
    canonical_manifest_digest,
    verify_native_canary_bundle,
)
from quantengine_public.agent_platform.role_topology import NativeRoleReceipt


STAGES = (
    "architecture",
    "test_author",
    "development",
    "test_verify",
    "ops",
    "quality",
)
STAGE_POLICY = {
    "architecture": (
        "Architecture",
        "codex-cli-chatgpt-subscription",
        "gpt-5.6-terra",
        (),
        "8602a5943f9b8b9af13432148300005b65da4209",
    ),
    "test_author": (
        "Test",
        "codex-cli-chatgpt-subscription",
        "gpt-5.6-sol",
        ("tests/agent_platform/test_role_topology.py",),
        "5f60abf00b720a115efdae3bcf136a822c814fee",
    ),
    "development": (
        "Development",
        "qwen-code-cli-studio-local",
        "qwen3.8:27b-mxfp8",
        ("src/quantengine_public/agent_platform/role_topology.py",),
        "f9ddb74697caf89e7f602109759c40ce97179cde",
    ),
    "test_verify": (
        "Test",
        "codex-cli-chatgpt-subscription",
        "gpt-5.6-sol",
        (),
        "8602a5943f9b8b9af13432148300005b65da4209",
    ),
    "ops": (
        "Ops",
        "deterministic-local",
        None,
        (),
        "53c25d40a686e83f46bd42a194272a60f53b3adf",
    ),
    "quality": (
        "Quality Shield",
        "quality-shield.observe_delivery",
        None,
        (),
        "53c25d40a686e83f46bd42a194272a60f53b3adf",
    ),
}
STAGE_ARTIFACTS = {
    stage: {
        "context": f"evidence/contexts/{index:02d}_{stage}.json",
        "output": f"evidence/outputs/{index:02d}_{stage}.json",
    }
    for index, stage in enumerate(STAGES, start=1)
}
ZERO_AUTHORITY = {
    "deployment_allowed": False,
    "paper_allowed": False,
    "real_allowed": False,
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle-dir", required=True, type=Path)
    parser.add_argument("--signing-key", required=True, type=Path)
    args = parser.parse_args(argv)
    bundle = args.bundle_dir.resolve()
    source_artifact = "evidence/source_identity.json"
    request_artifact = "evidence/00_request.json"
    artifact_paths = [source_artifact, request_artifact]
    for stage in STAGES:
        artifact_paths.extend(STAGE_ARTIFACTS[stage].values())
    artifact_hashes = {
        path: hashlib.sha256((bundle / path).read_bytes()).hexdigest()
        for path in artifact_paths
    }
    source_identity = artifact_hashes[source_artifact]
    initial_input_digest = artifact_hashes[request_artifact]
    contexts = {
        stage: artifact_hashes[STAGE_ARTIFACTS[stage]["context"]]
        for stage in STAGES
    }
    heads = {stage: STAGE_POLICY[stage][4] for stage in STAGES}

    receipts = []
    prior = initial_input_digest
    for stage in STAGES:
        role, runtime, model, changed_paths, head = STAGE_POLICY[stage]
        output_digest = artifact_hashes[STAGE_ARTIFACTS[stage]["output"]]
        receipt = NativeRoleReceipt(
            task_id="TASKSYS-1329",
            stage=stage,
            role=role,
            runtime=runtime,
            model=model,
            source_identity=source_identity,
            context_digest=contexts[stage],
            execution_head_before=head,
            execution_head_after=head,
            input_digest=prior,
            output_digest=output_digest,
            changed_paths=changed_paths,
            status="PASS",
            authority=ZERO_AUTHORITY,
        )
        receipts.append(receipt.to_dict())
        prior = output_digest

    manifest = {
        "schema_version": MANIFEST_SCHEMA,
        "evidence_class": EVIDENCE_CLASS,
        "task_id": "TASKSYS-1329",
        "source_artifact": source_artifact,
        "source_identity": source_identity,
        "request_artifact": request_artifact,
        "initial_input_digest": initial_input_digest,
        "expected_qwen_model": "qwen3.8:27b-mxfp8",
        "expected_development_paths": [
            "src/quantengine_public/agent_platform/role_topology.py"
        ],
        "expected_context_digests": contexts,
        "expected_execution_heads": heads,
        "stage_artifacts": STAGE_ARTIFACTS,
        "receipts": receipts,
        "artifacts": [
            {"path": path, "sha256": artifact_hashes[path]}
            for path in artifact_paths
        ],
        "trust": {
            "operator_attested": True,
            "provider_signed": False,
            "continuous_native_run": False,
            "independently_replayable_provider_execution": False,
            "owner_identity": OWNER_IDENTITY,
            "signer_key_fingerprint": OWNER_KEY_FINGERPRINT,
            "signature_namespace": SIGNATURE_NAMESPACE,
            "signature_file": SIGNATURE_FILE,
            "allowed_signers_file": ALLOWED_SIGNERS_FILE,
            "statement": (
                "The owner signature authenticates publication and byte integrity only; "
                "the providers did not sign these retrospective canary records."
            ),
        },
        "authority": ZERO_AUTHORITY,
    }
    manifest["manifest_digest"] = canonical_manifest_digest(manifest)
    manifest_path = bundle / MANIFEST_FILE
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    signature_path = bundle / SIGNATURE_FILE
    signature_path.unlink(missing_ok=True)
    subprocess.run(
        (
            "ssh-keygen",
            "-Y",
            "sign",
            "-f",
            str(args.signing_key.resolve()),
            "-n",
            SIGNATURE_NAMESPACE,
            str(manifest_path),
        ),
        check=True,
    )
    result = verify_native_canary_bundle(bundle)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
