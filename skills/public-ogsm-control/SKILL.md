---
name: public-ogsm-control
description: Prepare, review, revise, or retrospectively assess a public software-delivery Objective using the OGSM V2 evidence boundary. Use it for Outcome Cards, Owner acceptance packets, objective changes, and evidence-bound AARs; do not use it to accept an Objective, implement code, or grant release or deployment authority.
---

# Public OGSM Control

Prepare an inspectable proposal that helps the Owner choose and control one
outcome. Producing an OGSM document is not success; stale work and inadmissible
evidence must be detectable before they influence delivery.

## Establish the authority baseline

Read the current task, accepted Objective Contract revision if one exists, and
the exact evidence inventory. Stop when the Owner identity, current accepted
revision, task lineage, or evidence provenance is ambiguous. Chat history and a
previous proposal are not accepted state.

This Skill performs judgment and prepares proposals. The deterministic
validator in `quantengine_public.agent_platform.ogsm_v2` checks shape, digest,
references, state, and revision continuity. Neither can decide that an
Objective is wise or accept it for the Owner.

## Prepare an Objective proposal

1. Write an Outcome Card with the problem, at least two materially different
   alternatives, the selected outcome, and the selection reason. Reject an
   implementation, document, task count, or platform completion proxy that can
   pass without the intended outcome.
2. Define Goals, Strategies, and Measures as an explicit support graph. Every
   Strategy references existing Goal IDs. Every Measure declares its kind,
   judgment or formula, evidence sources, sample and horizon, PASS/WARN/FAIL
   rules, decision consequence, and owner.
3. Classify evidence as `PRIMARY`, `SUPPORTING`, or `EXCLUDED`. Missing evidence
   produces `EVIDENCE_GAP`; it is never represented as zero or inferred PASS.
4. Run exactly these bounded review passes:
   - `outcome_fit`: can the proposal pass while the intended outcome fails?
   - `evidence_goodhart`: can a Measure be gamed, fabricated, or supported by
     excluded evidence?
   - `capacity_authority_minimalism`: does the proposal exceed WIP, scope, or
     Owner authority, or create an unnecessary platform?
5. Record findings, revisions, residual warnings, and a bounded verdict for
   each pass. Any `BLOCKED` pass keeps the packet blocked.

Start from
[`assets/owner-acceptance-packet.json`](assets/owner-acceptance-packet.json).
Keep the packet and Objective Contract `PROPOSED`, all acceptance fields empty,
and all authority flags false. Bind the exact task/source lineage, classify
each evidence inventory item, and list unresolved blockers without replacing
missing facts with placeholders that look observed. Recompute canonical digests
only after the packet is complete, then present the exact digest-bound packet
to the Owner. Do not convert it to `ACCEPTED` without a separate explicit Owner
decision.

## Revise an accepted Objective

Never mutate an accepted revision in place. Prepare the next revision with the
prior contract digest as `parent_digest`, and prepare an Objective Change
Receipt containing the changed fields, Owner rationale, causal evidence,
invalidated dependent tasks/runs/handoffs/evals/evidence, and explicitly
reusable evidence. Silence never means reusable. The new revision remains a
proposal until the Owner accepts it.

## Conduct an evidence-bound AAR

Compare expected and actual outcomes using admitted evidence and counter-
evidence. Identify affected assumptions and causal links, retain failed
receipts and regression references, and propose exactly one decision:
`ADOPT`, `ADJUST`, `ABANDON`, or `GATHER_MORE_EVIDENCE`. An `ADOPT` proposal
without retained failure and regression references is blocked. Record expiry
and the next contract or task identity; do not silently redefine the current
Objective.

## Output boundary

Return the proposal packet, unresolved blockers, evidence classifications,
review receipts, and the smallest Owner decision required next. This Skill
cannot accept or supersede an Objective, mutate task or control state,
invalidate evidence, dispatch work, implement code, approve Quality, grant
release authority, merge, publish, or deploy.
