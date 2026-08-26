# Public Architecture Three-Pass Review

Date: 2026-08-26

Scope: README, target architecture, system context, Golden Path contracts, and
committed evidence

Decision: `PASS_WITH_REVISIONS` before implementation; revisions accepted into
the current local branch

## Pass 1: Reader Clarity

### Findings

The previous README mixed three valid but different stories:

1. the AI collaboration and anti-drift method;
2. the software-delivery control architecture; and
3. the QuantEngine financial-runtime example.

The first collaboration diagram was understandable, but the document then
shifted from software delivery into Paper, Replay, and PnL without first
explaining that QuantEngine was a reference implementation. The expanded
architecture also introduced Agent roles, control systems, third-party tools,
and domain providers in one diagram.

### Revisions

- Rename the public identity to Evidence-Controlled AI Software Delivery.
- Position QuantEngine as the first reference implementation.
- Present the architecture in layers: control thesis, Agent runtime, evidence
  and evaluation, then the domain reference.
- Define external reader terms before internal component names.
- Move the provider catalogue out of the first-reading path.

### Result

A new reader can follow one causal line from objective to bounded authority
before encountering the full module plan.

## Pass 2: Architectural Closure

### Findings

The architecture correctly separated Agent judgment, Skills, deterministic
tools, authoritative state, fingerprints, and fail-closed evidence. Four gaps
remained:

1. collaboration did not distinguish Agent-as-tool, handoff, and independent
   review;
2. no finite task state and invalidation model was documented;
3. trace, evidence, eval, and authority were not explicitly separated; and
4. Quality Shield issued PASS before consuming QuantEngine runtime evidence,
   while QuantEngine produced the final release verdict.

The fourth gap violated the intended producer/certifier separation.

### Revisions

- Define the three collaboration modes and ownership semantics.
- Add state transitions, idempotency, next-owner, retry, and source-drift rules.
- Separate observability, factual proof, behavioral evaluation, and permission.
- Insert a zero-authority runtime evidence artifact before QCS and Quality.
- Make Quality Shield consume the exact runtime evidence.
- Move final authority derivation to a deterministic Release Controller.

### Result

The public Golden Path now follows:

```text
Ops plan
  -> runtime evidence with zero authority
  -> QCS risk evidence
  -> independent Quality Shield with zero authority
  -> deterministic Release Controller
  -> bounded authority
```

## Pass 3: Future AI-System Fit

### Findings

The strongest architectural idea is not Multi-Agent by itself. It is preserving
model reasoning while external systems control goals, current facts,
permissions, validation, and evidence.

The previous version still risked implying that every professional role should
become an Agent and that an AAR alone completed the learning loop.

### Revisions

- State the one-Agent-first rule and require a real ownership, context, tool,
  permission, or evaluation reason before splitting a specialist.
- Define dynamic context assembly from current task, source, graph, evidence,
  and directly related regressions rather than a static knowledge dump.
- Extend the learning loop from AAR into eval creation, repair-layer
  classification, historical replay, independent review, and baseline
  promotion.
- Add role-specific eval targets including tool selection, handoff quality,
  scope adherence, stale-context detection, false PASS, cost, and rework.

### Result

The architecture now presents Multi-Agent collaboration as a consequence of
responsibility boundaries, not as the product objective.

## Truthfulness Corrections

- Replace the unsupported phrase `signed verdict` with sealed or bounded
  verdict; the current public artifacts are content-addressed, not digitally
  signed.
- Update the Golden Path from 13 to 14 artifacts.
- Replace stale planned filenames with the implemented `identity.py` and
  `golden_path.py` structure.
- Remove the stale `local and uncommitted` statement while retaining the fact
  that no public GitHub release has been verified.

## Final Acceptance Conditions

The revision is accepted only when:

1. README and deep architecture preserve every required content-contract theme;
2. target, implemented, planned, synthetic, and withheld capabilities remain
   distinguishable;
3. runtime evidence precedes independent Quality and final authority;
4. only a passing Release Controller artifact can carry non-zero authority;
5. all positive and negative evidence is regenerated against the same contract;
6. tests, schema validation, links, Skill validation, and public safety scan pass.
