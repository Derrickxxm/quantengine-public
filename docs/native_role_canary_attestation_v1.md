# Native Role Canary Attestation v1

## Problem

`validate_native_role_topology()` answers whether six receipts obey the
accepted task, source, context, model, path, handoff, order, and authority
contract. It intentionally accepts plain data. Therefore it cannot answer who
produced or published those receipts: anyone can construct six structurally
valid records in memory.

This design adds source authentication without pretending that the model
providers signed their stage outputs.

## Evidence class

`public_delivery.native_role_canary_manifest.v1` is a
`retrospective_operator_attestation`. It records public-safe summaries of the
separate DEC-0031 provider canaries at their historical source revisions. The
repository owner signs the canonical manifest after every referenced byte has
been hashed.

The bundle contains:

- accepted source identity and request artifacts;
- six stage-context and six stage-output summaries;
- six receipts bound in the accepted Architecture-to-Quality order;
- exact runtime, model, execution HEAD, changed paths, and handoff digests;
- a zero-authority object;
- a pinned public signer file and detached SSH signature.

The signature namespace is `evidence-controlled-ai-delivery`. The verifier
pins the expected signer-file hash and owner-key fingerprint in code, so an
attacker cannot replace the manifest, signature, and embedded public key as a
self-consistent set.

## Offline verification

```bash
quantengine-public verify-native-canary \
  --bundle-dir examples/native_role_canary_v1
```

The command fails closed unless all of these checks pass:

1. fixed manifest, signature, and signer files exist and are regular files;
2. the signer file matches the pinned trust-root hash;
3. OpenSSH verifies the manifest signature for the pinned owner identity and
   namespace;
4. the manifest has the exact v1 shape and canonical digest;
5. all fourteen referenced evidence files match their SHA-256 identities;
6. request, source, stage context, stage output, and handoff dependencies close;
7. the existing six-stage topology validator accepts the receipts;
8. deployment, Paper, and Real authority remain false.

## Claim boundary

| Claim | Result | Reason |
| --- | --- | --- |
| The repository owner published these exact bytes | Proven | Pinned owner identity and SSH signature |
| Evidence bytes and six-stage contract can be checked offline | Proven | Content digests plus deterministic topology validation |
| The listed providers signed their stage records | Not claimed | Provider signatures were not captured |
| All six stages ran as one continuous native execution | Not claimed | DEC-0031 retained separate bounded canaries |
| A reviewer can independently replay provider execution | Not claimed | Private prompts, endpoints, and raw provider traces are outside the public bundle |
| The bundle authorizes deployment, Replay, Paper, or Real | Rejected | Every authority bit is fixed to false |

The distinction is deliberate: operator publication authenticity strengthens
the public evidence without silently converting retrospective records into
provider-origin proof.

## Retained negative cases

Tests reject modified evidence bytes, a modified unsigned manifest, signer-file
replacement, missing signatures, path escape, provider-signature overclaim,
and non-zero runtime authority. CI runs the same public command a reviewer can
run locally.
