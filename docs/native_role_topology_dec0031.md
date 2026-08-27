# DEC-0031 Native Role Topology

Plane: TASKSYS-1329

Status: implemented on isolated local branches; review-ready; not pushed

## Accepted flow

| Stage | Runtime | Exact model | Filesystem authority |
| --- | --- | --- | --- |
| Architecture | Codex CLI with ChatGPT subscription | `gpt-5.6-terra` | read-only |
| Test author | Codex CLI with ChatGPT subscription | `gpt-5.6-sol` | tests only |
| Development | official Qwen Code against an operator-local endpoint | `qwen3.8:27b-mxfp8` | declared implementation paths only; no tests |
| Test verify | Codex CLI with ChatGPT subscription | `gpt-5.6-sol` | read-only |
| Ops | deterministic local system | none | no repository changes |
| Quality | `quality_shield.observe_delivery` | none | advisory-only; no mutations |
| Release | deterministic local controller | none | verdict only; zero runtime authority |

Every native receipt uses
`public_delivery.native_role_receipt.v1` and binds the task, accepted source
identity, accepted per-stage context digest, exact execution HEAD before and
after, handoff input/output digests, runtime/model, changed paths, PASS status,
and an explicit zero-authority object. A role may not create a commit during
its turn. Public admission independently pins the operator-local model to
`qwen3.8:27b-mxfp8`, requires the accepted Development path allowlist, rejects
every changed path outside it, and includes both the model and allowlist in the
topology digest.

`validate_native_role_topology()` accepts exactly six receipts in the declared
order. `derive_native_role_release()` calls that validator and hashes the
admitted topology and receipt identities into
`public_delivery.native_role_release.v1`. It cannot grant deployment, Paper,
or Real authority.

## Executed evidence

- Terra Architecture first returned `BLOCKED` after detecting that receipts
  were not checked against an accepted per-stage context map. The contract was
  repaired, and the Terra recheck returned PASS without file changes.
- Sol authored adversarial context tests under `tests/` only. After the Qwen
  change, a separate Sol verification passed the focused suite without edits.
- Qwen Code 0.22.0 used the exact operator-local model `qwen3.8:27b-mxfp8`, changed only
  its declared implementation file, and passed its required check. The
  temporary loopback tunnel was stopped after the canary; no OpenAI API credit
  was used.
- Deterministic Ops and the existing Quality Shield observer produced
  mutation-free, zero-authority receipts. Quality Shield reported shadow,
  advisory-only PASS.
- Red-then-green tests now prove that deterministic Release rejects a forged
  stage and consumes the exact validated six-stage chain.

These executed role canaries occurred at their recorded stage HEADs. They prove
each provider lane and exposed two real contract defects. The retained
deterministic topology test is the single-chain regression oracle; this document
does not relabel separate canaries as one uninterrupted live run.

## Boundaries

This work authorizes isolated local implementation, tests, bounded canaries,
documentation, Plane/AI Memory alignment, and local commits. It does not
authorize push, PR, merge, publication, deployment, persistent services,
QuantEngine Replay/Paper/Real, or knowledge-graph rebuild.

TASKSYS-1327 remains the completed strict-schema Qwen slice. TASKSYS-1328
remains historical evidence of the superseded all-Qwen SDK handoff failure.
