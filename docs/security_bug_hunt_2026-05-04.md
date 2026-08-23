# Security And P0 Bug Hunt

Date: 2026-05-04

Scope: public repository source, tests, examples, docs, CI, CLI behavior, release gate behavior, and leak surface.

Target: search aggressively for P0 bugs and leakage/security issues. Do not invent fake P0 findings; only record issues with concrete evidence.

## Summary

No credential, private path, host, exchange adapter, real order, account data, or private strategy leak was found in tracked source files.

The audit did find several release-gate correctness and public-project hygiene issues. They were fixed in this pass.

## Severity Rules

- P0: public leak, secret exposure, misleading public evidence, gate false-pass, CI false confidence, or core verification failure.
- P1: important correctness, public quality, or maintainability issue that does not directly create a false trusted result.
- P2: polish, documentation, or roadmap issue.

## Round 1: Repository Hygiene And Leak Surface

Checks:

- tracked files
- ignored generated files
- private path and credential search
- public docs wording

Findings:

| ID | Severity | Finding | Status |
|---|---|---|---|
| R1-01 | P1 | Generated `.egg-info` and cache files existed locally but were not tracked. Confirmed no public leak. | Verified |
| R1-02 | P0 | Search for private paths, credentials, hostnames, and real trading identifiers found no tracked source leak. | Verified |

## Round 2: Replay, Lifecycle, And Risk Correctness

Checks:

- invalid event handling
- duplicate order handling
- malformed order id handling
- risk config validation
- boolean numeric handling

Findings:

| ID | Severity | Finding | Status |
|---|---|---|---|
| R2-01 | P0 | Risk-rejected `order_created` with missing `order_id` could create a synthetic `"None"` order instead of failing closed. | Fixed |
| R2-02 | P0 | Duplicate `order_created` events were silently ignored, which could hide conflicting input and still pass replay. | Fixed |
| R2-03 | P1 | Boolean values could be accepted as numeric amounts because `bool` is an `int` subclass in Python. | Fixed |
| R2-04 | P1 | Negative or empty risk policy values were not rejected during config loading. | Fixed |

## Round 3: Release Gate Integrity

Checks:

- empty artifact contract
- manifest structure
- gate command behavior
- artifact tampering after manifest generation

Findings:

| ID | Severity | Finding | Status |
|---|---|---|---|
| R3-01 | P0 | A manifest with empty `expected_outputs` could pass artifact hash checks. | Fixed |
| R3-02 | P0 | `gate` trusted manifest hashes without recomputing artifact hashes from disk. Tampered artifacts could pass. | Fixed |
| R3-03 | P1 | Manifest structural checks did not require `status`, `expected_outputs`, or `artifact_hashes`. | Fixed |

## Round 4: CI And Documentation Consistency

Checks:

- CI behavior
- README CLI examples
- gate example outputs
- architecture contract wording

Findings:

| ID | Severity | Finding | Status |
|---|---|---|---|
| R4-01 | P1 | CI ran `demo` but did not run `validate`, so artifact integrity validation was not exercised in CI. | Fixed |
| R4-02 | P1 | Release gate examples did not show the new `artifact_integrity` check. | Fixed |
| R4-03 | P2 | Architecture doc did not state that gate/validate recompute artifact hashes from disk. | Fixed |

## Round 5: Public Evidence Review

Checks:

- public resume-readiness
- explanatory leak-scan hits
- documented out-of-scope boundaries
- final test and demo run

Findings:

| ID | Severity | Finding | Status |
|---|---|---|---|
| R5-01 | P0 | No tracked credential, private absolute path, private hostname, real trading identifier, or account data was found. | Verified |
| R5-02 | P1 | The repository needed an audit note explaining the bug-hunt result and not overstating “100 P0” findings. | Fixed |

## Verification Commands

```bash
.venv/bin/python -m pytest
.venv/bin/quantengine-public demo --artifact-dir /tmp/qe_public_audit_demo
.venv/bin/quantengine-public validate --artifact-dir /tmp/qe_public_audit_demo
python scripts/public_safety_scan.py
```

Expected leak-scan interpretation:

- Source, tests, and examples should not match private paths, real trading identifiers, private project names, or credential-like strings.
- README, SECURITY, CONTRIBUTING, ROADMAP, and docs may mention prohibited terms only as explicit out-of-scope or security guidance.

## Remaining Risk

- This is a public synthetic project, not a production trading system.
- The CLI assumes examples are available from the repository checkout.
- Artifact manifests are local evidence records, not signed attestations.
- Dirty-worktree enforcement is intentionally out of scope for this public edition and belongs in a separate agent workflow control-plane project.
