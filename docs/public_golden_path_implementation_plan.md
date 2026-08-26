# Public Golden Path Implementation Plan

Status: first local implementation complete; public release pending

Principle: one thin end-to-end path before expanding module depth

Authority: public synthetic demonstration only; no production, Paper, Real,
deployment, credential, or external-system authority

## Objective

Let a reviewer clone one repository and follow one synthetic software change
from requirement through architecture, test-first validation, bounded
implementation evidence, Ops preparation, independent quality, release evidence,
and learning AAR.

## Demonstration Requirement

The first Golden Path reuses an existing public invariant:

> A release package containing changed, missing, or undeclared material must
> fail closed and must not acquire execution authority.

This requirement is intentionally small. The milestone proves the collaboration
and evidence chain, not a new trading feature.

## Required Artifact Chain

```text
01_ogsm.json
  -> 02_plane_task.json
  -> 03_architecture_packet.json
  -> 04_validation_plan.json
  -> 05_worker_handoff.json
  -> 06_patch_manifest.json
  -> 07_test_result.json
  -> 08_ops_delivery_plan.json
  -> 09_runtime_evidence.json
  -> 10_qcs_manifest.json
  -> 11_qcs_receipt.json
  -> 12_quality_verdict.json
  -> 13_release_verdict.json
  -> 14_aar.json
```

Every artifact records:

- schema version;
- producer module;
- exact upstream artifact identities;
- repository, branch, commit, and source-tree identity where applicable;
- status from a closed vocabulary;
- evidence references;
- authority explicitly granted and explicitly withheld;
- content digest.

Each negative receipt also records the canonical digest of the rejected request,
and the public-safe request is retained beside the receipt. Late-stage blockers
bind the last valid upstream artifact instead of detaching the failure from its
causal prefix.

The repository commits the full engine evidence once on the positive path.
Negative directories retain only the rejected request, valid delivery prefix,
and blocker; a package-digest mismatch also records the declared and actual
package identities in the blocker. This avoids duplicating identical runtime
evidence without weakening the failed decision trail.

## Module Responsibilities

| Step | Public module | Responsibility | Required negative case |
| --- | --- | --- | --- |
| 1 | Owner / OGSM fixture | freeze objective, measure, non-goal | missing acceptance measure blocks intake |
| 2 | `public-control-plane` | bind task and source identity | stale commit or task digest blocks routing |
| 3 | `public-architecture-agent` | identify package-verification impact and allowed scope | unexpected path or contract expansion blocks packet |
| 4 | `public-test-agent` | define tamper tests before implementation evidence | no failing/negative case blocks development handoff |
| 5 | `public-development-agent` | bind an allowed implementation result | changed file outside scope blocks result |
| 6 | `public-ops-agent` | bind CI, artifact, readback, and rollback expectations | missing artifact digest blocks delivery plan |
| 7 | `quantengine-public` | produce zero-authority runtime evidence | package-integrity failure blocks runtime evidence |
| 8 | `public-qcs` | select package-integrity risk and collect owner evidence | absent owner test evidence returns `EVIDENCE_GAP` |
| 9 | `public-quality-shield` | judge the complete set including runtime evidence | malformed or mismatched provenance returns `FAIL_CLOSED` |
| 10 | `public-release-controller` | derive bounded authority from runtime and quality | missing or failed upstream evidence grants no authority |
| 11 | learning flywheel | retain failure, create regression, and name next action | AAR cannot omit failed path or negative evidence |

## Skill And Tool Boundary

The public demonstration will include four readable Skills:

```text
skills/public-architecture-review/SKILL.md
skills/public-test-first-validation/SKILL.md
skills/public-bounded-development/SKILL.md
skills/public-ops-delivery-review/SKILL.md
```

Skills own workflow judgment, required evidence, stop conditions, and handoff
meaning. They do not contain private prompts, credentials, or production paths.

Small deterministic modules own only:

- canonical JSON and digest calculation;
- schema validation;
- source and artifact identity checks;
- declared test execution and result recording;
- gate evaluation;
- artifact writing.

The reviewer-facing demo runner may compose the synthetic fixtures in one
command, but it is explicitly a demonstration harness. It is not a production
workflow engine, Agent dispatcher, or replacement super-CLI.

## Minimal Repository Additions

```text
skills/
  public-architecture-review/SKILL.md
  public-test-first-validation/SKILL.md
  public-bounded-development/SKILL.md
  public-ops-delivery-review/SKILL.md
contracts/public_delivery/
  *.schema.json
src/quantengine_public/delivery/
  identity.py
  golden_path.py
examples/golden_path/
  reference_request.json
  evidence/
tests/golden_path/
  test_identity.py
  test_golden_path.py
  test_committed_evidence.py
```

No service, database, queue, browser bot, generic plugin system, dashboard, or
new standalone CLI is required for this milestone.

## Implementation Order

1. Freeze artifact schemas and closed status vocabularies.
2. Add canonical digest and upstream-binding verification.
3. Write negative tests for missing acceptance, stale source, scope escape,
   missing validation, missing artifact digest, evidence gap, and provenance
   mismatch.
4. Add the four public Skills.
5. Generate the positive Golden Path artifacts from the existing package-tamper
   invariant.
6. Generate and commit representative negative receipts.
7. Bind QuantEngine runtime evidence into independent quality, then derive
   authority through the deterministic Release Controller.
8. Run security and private-data scans.
9. Add the Golden Path to CI and the README reader path.

## Acceptance Criteria

The milestone is complete only when:

1. a clean checkout reproduces the complete 14-artifact chain;
2. every artifact digest and upstream edge can be independently recomputed;
   the edge type and producer must match the closed Golden Path inventory;
3. all declared positive and negative tests pass;
4. at least seven named failure branches stop at the correct owner boundary;
5. the final public verdict grants no Real, deployment, order, position, fund,
   or credential authority;
6. the AAR retains the failed path and names the next decision;
7. CI publishes the same inspectable evidence shown in the repository;
8. the public-content contract remains fully covered;
9. no private path, host, credential, strategy, account, or production config is
   present.

## Explicit Non-Goals

- implementing all provider depth in the first milestone;
- creating a universal Agent framework;
- rebuilding Plane, GitHub, Sonar, S3, or Komodo;
- automating production deployment;
- proving strategy profitability;
- adding a heavy workflow CLI under a new name.

## Local Implementation Result

The first local implementation produces:

- 14 connected positive-path artifacts;
- 9 negative receipts at the owning gate;
- 4 validated public Skills;
- a fixed single-purpose reproduction entry point;
- committed engine, quality, release, and AAR evidence;
- a passing full repository test suite at implementation time;
- a passing current-tree public safety scan.

This result is committed on the current local branch. It is not yet a GitHub
release or evidence of a completed full-provider public architecture.
