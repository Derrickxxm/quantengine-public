# Interviewer Review Backlog

Date: 2026-08-26

Scope: public repository content, runnable code, contracts, tests, CI, release,
and GitHub presentation

Review mode: read-only findings captured before remediation

Alignment status: Owner approved OpenAI Agents SDK Python as the single MVP
Agent runtime dependency. Development is paused by Owner and resumes only on
later explicit direction. No M0-M6 implementation is complete.

Current release reviewed: `v0.4.0` at
`f5e64e5c96d7aad7da1a9203c73eebec37dcd916`

## 1. Review Decision

The repository is strong evidence of architecture judgment, risk awareness, and
an evidence-first engineering method. It is not yet sufficient proof of a
production multi-Agent delivery system.

The immediate priority is not to publish every planned module. The immediate
priority is to make the existing public trust boundary true under adversarial
validation, then replace self-declared proof with derived proof, and only then
add one real Native-Agent collaboration slice.

```text
contract correctness
  -> release reproducibility
  -> derived evidence
  -> one real Agent collaboration slice
  -> observability and evals
  -> broader public modules
```

## 2. Confirmed Correctness Bugs

### P0-01: Release authority can bypass the evidence topology

#### Problem

`verify_artifact()` constrains non-zero authority to a passing
`public_delivery.release_verdict`, but it does not bind that artifact type to
its owning producer or required upstream evidence. `verify_artifact_chain()`
checks that declared upstream artifacts exist, but does not require a Release
verdict to consume both runtime evidence and an independent Quality verdict.

The following artifact is currently accepted by both validators:

```text
artifact_type = public_delivery.release_verdict
producer = public_release_controller
status = PASS
upstream = []
deployment_allowed = true
paper_allowed = true
real_allowed = true
```

Observed probe result:

```text
verify_artifact()       -> []
verify_artifact_chain() -> []
```

#### Impact

The generated Golden Path is correct, but the public verifier does not prove
that an invalid authority path cannot pass. This contradicts the core
fail-closed and independent-release-control claims.

#### Required decision

Treat artifact shape, producer ownership, required upstream topology, status,
and authority semantics as one public validation contract. A caller must not
need to know which combination of partial validators is safe.

#### Acceptance criteria

- A Release verdict with an empty upstream set fails.
- A Release verdict without exact runtime evidence fails.
- A Release verdict without an independent Quality verdict fails.
- A Release verdict produced by any identity other than
  `public_release_controller` fails.
- A Quality verdict that does not consume runtime evidence fails.
- An upstream artifact with the right digest but wrong type fails.
- Non-zero authority is rejected unless the complete required causal topology
  is present and passing.
- The JSON contract and Python verifier enforce compatible semantics.
- Committed red tests preserve every bypass above.

### P1-01: Release version and installed CLI version disagree

#### Problem

The `v0.4.0` tag contains `project.version = 0.4.0`, while
`quantengine_public.__version__` remains `0.3.0`. The installed command reports:

```text
quantengine-public --version -> 0.3.0
```

#### Impact

The public release identity is internally inconsistent, and the green CI did
not detect the inconsistency. This weakens a project whose central subject is
release identity and evidence.

#### Required decision

Use one version source or mechanically verify every exposed version against the
release tag.

#### Acceptance criteria

- Package metadata, module version, CLI output, tag, and Release title agree.
- CI builds the distribution, installs it into a clean environment, and checks
  the installed CLI version.
- A mismatched tag or source version fails before Release publication.

## 3. Evidence And Implementation Gaps

### P1-02: The runnable slice is a deterministic contract harness, not an Agent runtime

#### Current truth

The repository implements a 14-artifact deterministic Golden Path and a
synthetic QuantEngine runtime. It does not dispatch Architecture, Test,
Development, or Ops Agents.

The following remain target architecture or planned public equivalents:

- Agent runtime and Agent SDK;
- real Agent-as-tool and handoff execution;
- Plane state integration;
- revision-bound code graph integration;
- dynamic context assembly;
- persistent task recovery and invalidation;
- Agent traces and tool-call correlation;
- role-specific behavioral evals;
- independent Quality Shield runtime.

The approved implementation route is now narrower:

- reuse OpenAI Agents SDK `Agent`, `Runner`, `SQLiteSession`, serializable
  `RunState`, handoffs, approvals, and tracing;
- keep only task/source/context identity, deterministic role transitions,
  cross-run handoff receipts, evidence admission, independent Quality, and
  Release authority in repository-owned code;
- do not add a second Agent orchestration framework.

#### Impact

The repository can support the claim that the control contracts and reference
runtime were built. It cannot yet support the claim that a production
multi-Agent software delivery platform was publicly implemented.

#### Acceptance criteria for the next public slice

- Implement one real collaboration mode, not all planned Agents at once.
- Use one current source revision and one bounded public task.
- Invoke at least one Skill-led specialist through OpenAI Agents SDK Python.
- Record the request, context snapshot, tool use, result, stop reason, and
  handoff or review receipt.
- Keep final authority deterministic and outside the Agent.
- Preserve a negative case for stale source or invalid handoff identity.

### P1-03: Important evidence is still self-declared

#### Problem

The Golden Path accepts booleans and labels such as:

```text
package_integrity = true
provenance_matches = true
historical_regressions_replayed = true
promotion_status = PROMOTED
```

Some QuantEngine runtime facts are independently recomputed, but the delivery
Quality and learning claims above are not all derived from inspectable runs.

#### Impact

The current artifacts prove workflow shape and identity wiring. They do not yet
prove that provenance, historical replay, independent review, and promotion
actually happened.

#### Acceptance criteria

- Replace caller-provided provenance booleans with recomputed digest and
  producer checks.
- Bind every required owner-evidence name to an existing typed artifact.
- Record the exact regression run identities used by an AAR.
- Derive promotion status from admitted eval and review receipts.
- Preserve `UNKNOWN` or `EVIDENCE_GAP` when a required fact is not observable.

### P1-04: The learning flywheel is represented but not yet executed

#### Problem

The AAR correctly names problem, reflection, decision, eval case, repair layer,
historical replay, and promotion. In the current reference path those values are
fixed output rather than the result of an executed failure-to-promotion cycle.

#### Acceptance criteria

- Retain one real failed receipt as the start of the public learning case.
- Add the red regression that reproduces the failure.
- Bind the repair to exactly one layer: Skill, Tool, Contract, Model, Data, or
  Process.
- Replay the retained failure and selected historical regressions.
- Require an independent review receipt before promotion.
- Make the final AAR an index of those artifacts rather than a narrative claim.

## 4. Repository And Release-Control Gaps

### P1-05: The repository can bypass its own review process

#### Current observation

At review time, GitHub reported no branch protection and no repository ruleset
for `main`.

#### Impact

A direct push can bypass the PR and CI path. That is especially visible for a
repository presenting release-control engineering.

#### Acceptance criteria

- Protect `main` against direct pushes.
- Require the public CI check before merge.
- Prevent force pushes and branch deletion.
- Define the owner exception explicitly if a solo-maintainer recovery path is
  required.

### P1-06: CI is green but does not yet prove a reproducible release

#### Current gaps

- no package build and clean-install smoke test;
- no version-to-tag check;
- no lint or static type check;
- no declared coverage threshold;
- no Python-version matrix despite `requires-python >= 3.11`;
- dependencies use lower bounds without a committed lock or constraints file;
- GitHub Actions use floating major tags rather than immutable commit SHAs;
- no explicit least-privilege workflow permissions.

#### Acceptance criteria

- Add the smallest checks needed to prove the published package and CLI.
- Pin release-critical workflow dependencies immutably.
- Declare workflow permissions explicitly.
- Test at least the minimum and current supported Python versions, or narrow the
  declared support range.
- Do not add broad tooling unless it closes a named failure mode.

## 5. Public Reader And Positioning Gaps

### P2-01: New and legacy project identities remain mixed

#### Current observation

The README now presents Evidence-Controlled AI Software Delivery, while the CLI,
Roadmap, and older architecture documents still describe a synthetic backend or
QuantEngine verification toolkit.

#### Impact

A reviewer may be unsure whether the repository is primarily:

```text
a trading verification toolkit
or
an AI software-delivery control architecture
```

#### Acceptance criteria

- Define one current repository identity.
- Label legacy documents as historical or superseded without deleting useful
  engineering history.
- Make the README, CLI description, Roadmap, package metadata, and GitHub About
  description agree.
- Preserve QuantEngine as the first reference scenario, not the complete system
  identity.

### P2-02: GitHub discovery metadata is empty

#### Current observation

The public repository has no GitHub description, homepage, or topics.

#### Acceptance criteria

- Add a one-sentence repository description that states the problem and current
  runnable proof.
- Add a small set of accurate topics.
- Do not use topics that imply an implemented Agent runtime before it exists.

### P2-03: The first-reading path is accurate but still abstract

#### Problem

The README explains the control philosophy well, but a non-specialist reader
must pass several architecture concepts before reaching the concrete result of
14 artifacts and nine negative scenarios.

#### Acceptance criteria

- Preserve the architecture thesis.
- Add a short early statement of the concrete problem, runnable result, and
  current limitation.
- Keep the five-minute evidence review as the technical proof path.
- Do not turn the README into a historical narrative; the resume owns the
  problem-reflection-decision story.

## 6. Interview Positioning Boundary

### Claims the current repository can support

- Designed and implemented a deterministic, evidence-bound delivery-control
  reference path.
- Separated runtime evidence, independent Quality, and final authority in the
  generated Golden Path.
- Built content-addressed artifacts, positive and negative paths, synthetic
  Paper/Replay reconciliation, public CI, and safety scanning.
- Defined how Skills, small tools, Agent judgment, authoritative state, evals,
  and human approval should be separated.

### Claims the current repository cannot yet support

- A production multi-Agent platform is publicly running.
- Plane, code graph, dynamic context, Agent trace, or role eval integrations are
  publicly implemented.
- The public AAR proves a real historical promotion cycle.
- Release authority is currently impossible to forge through an alternate
  artifact topology.
- The public project alone proves production scale or team adoption.

## 7. Ordered Delivery Route

### Phase 0: Restore trust in the current release contract

1. Add red tests for authority without required upstream evidence.
2. Close the Release and Quality topology bypass.
3. Make producer ownership part of the safe validation entry point.
4. Fix version identity and add a release smoke test.
5. Publish a focused correctness release.

Exit condition: no artifact can acquire authority without the exact admitted
causal chain, and the installed release identifies itself correctly.

### Phase 1: Convert asserted proof into derived proof

1. Resolve owner evidence to typed artifacts.
2. Recompute provenance instead of accepting booleans.
3. Bind AAR replay and promotion fields to actual receipts.
4. Add negative cases for missing, stale, aliased, and reused evidence.

Exit condition: Quality and learning facts are calculated from inspectable
evidence rather than supplied as trusted labels.

### Phase 2: Add one real Native-Agent collaboration slice

1. Select one bounded public task.
2. Run one Architecture or Test specialist through OpenAI Agents SDK as an
   Agent-as-tool.
3. Record current source identity, context selection, tool use, result, and stop
   reason.
4. Pass its output through deterministic validation and independent review.
5. Preserve one stale-context or invalid-handoff failure.

Exit condition: the public repository proves one real Agent collaboration mode
without creating a workflow platform.

### Phase 3: Add task recovery, trace, and evals only where the slice needs them

1. Reuse SDK `SQLiteSession` and serialized `RunState`; add only the finite,
   deterministic task state and idempotent cross-run transition data that the
   SDK must not own.
2. Correlate task, source, context, Agent, Skill, tool, result, and evidence ids.
3. Implement the smallest role-specific eval set.
4. Track false PASS, missed blocker, rework, latency, and cost where observable.

Exit condition: a stopped or failed task can be explained and safely resumed
from authoritative state.

### Phase 4: Align repository governance and public presentation

1. Protect `main` and require CI.
2. Make release dependencies and permissions reproducible.
3. Align README, CLI, Roadmap, legacy-doc labels, package metadata, and GitHub
   About metadata.
4. Re-run the interviewer review against the public URL.

Exit condition: the repository itself follows the control principles it
describes, and a reviewer sees one coherent project identity.

### Phase 5: Expand public modules only from demonstrated need

Consider the code graph, evidence store, deeper QCS, additional specialists,
provider modules, or Komodo public runbook only after a previous phase produces
a concrete missing boundary. Do not implement the architecture catalogue as a
batch.

## 8. Anti-Overdesign Rules

- Do not build a large workflow CLI.
- Do not combine OpenAI Agents SDK with LangGraph, AutoGen, CrewAI, Microsoft
  Agent Framework, or another overlapping orchestration framework in the MVP.
- Do not introduce a service, queue, database, or repository without a proven
  runtime, scale, ownership, or trust boundary.
- Do not add all specialist Agents before one collaboration slice is proven.
- Do not treat documentation, a boolean, or a generated artifact as proof of an
  event that did not run.
- Do not weaken fail-closed semantics for compatibility.
- Do not present planned modules as implemented.
- Prefer one red regression, one bounded repair, and one inspectable receipt over
  a broad framework rewrite.

## 9. Re-Review Gate

Before this backlog is considered closed, repeat the review from three
perspectives:

1. **Hiring manager, 30 seconds:** is the problem, result, and current boundary
   obvious?
2. **Technical interviewer, 10 minutes:** do the code and tests prove the central
   claims under negative paths?
3. **Senior architect, deep review:** can authority, evidence, task state, and
   recovery survive adversarial and long-running use without relying on chat
   memory?

The final result must be recorded as `PASS`, `PASS_WITH_REVISIONS`, or `BLOCKED`,
with links to the exact tests, CI run, release, and public evidence.
