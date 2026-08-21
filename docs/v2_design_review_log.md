# QuantEngine Public v2 Design Review Log

This log records the three required review-and-revision passes for
`v2_public_architecture_design.md`.

## Review 1: Architecture Fidelity

### Findings

1. Design v1 showed the correct lifecycle but did not state which component owns
   each decision. Without ownership, the diagram could be read as a generic
   pipeline rather than a set of fail-closed authority boundaries.
2. The package manifest was described, but the current architecture's stronger
   end-to-end identity chain was not explicit.
3. The decision-to-order-to-accounting action identity was implicit in the
   runtime list and needed to become a load-bearing public contract.
4. The design needed to say that QuantLab, private strategies, external quality
   systems and production operations are outside this repository rather than
   presenting the public slice as the complete private ecosystem.
5. Compatibility runtime and historical migration machinery should not become
   part of the clean public architecture.

### Revision 1

- Added an architecture ownership boundary for research, admission, packaging,
  Paper, replay, reconciliation and release judgment.
- Added an explicit identity chain from candidate through release verdict.
- Required stable decision/action identity through retries and recovery.
- Marked private ecosystem components as external contract boundaries.
- Kept compatibility debt outside the public target structure.

### Verdict

`PASS_WITH_REVISIONS`: the v2 design now reflects the current architectural
principles without copying the size or historical debt of the private system.

## Review 2: Security and Truthfulness

### Findings

1. "Synthetic" was stated as a boundary but not defined strongly enough;
   anonymized real data could still have entered under that label.
2. Artifact manifests could leak local paths and workstation identity even when
   the business data was synthetic.
3. Digest binding needed explicit defenses against omission, cross-run
   substitution, shortened hashes and path traversal.
4. Paper/replay reconciliation would be meaningless if replay were allowed to
   consume Paper's produced state.
5. A public fixture or configuration field must not be able to turn a documented
   Real prohibition into executable authority.
6. Source scanning alone was insufficient; new branch history, dependencies and
   generated example artifacts also require review.

### Revision 2

- Defined synthetic fixtures as newly generated rather than anonymized or
  transformed production material.
- Required logical repository-relative artifact paths.
- Added a public threat model covering omission, substitution, mutation,
  truncation, path escape, self-judgment, evidence reuse, authority injection and
  masked nondeterminism.
- Required byte-level digest recomputation by the judging side.
- Added a clean-checkout, offline, license and branch-history publication
  checklist.
- Added security attacks and offline execution to the v2 acceptance criteria.

### Verdict

`PASS_WITH_REVISIONS`: the public boundary is now testable rather than a prose
disclaimer. Implementation must make every listed attack load-bearing in CI.

## Review 3: Reader Experience and Buildability

### Findings

1. The design described a broad system but did not freeze a small reference
   scenario, leaving implementation at risk of becoming another large platform.
2. "One narrow entry point" needed an exact invocation and explicit input
   restrictions to prevent a new workflow CLI from emerging.
3. A reader could see the architecture diagram without knowing which source,
   artifact and test proved each node.
4. Portable CI cannot support a credible production throughput claim; stress
   evidence must separate correctness from machine-dependent measurements.
5. The new system story needed a deliberate README reading order before deeper
   contracts and threat-model documents.

### Revision 3

- Froze a small `QEP-USD` reference scenario with inspectable inputs and
  independently calculable economics.
- Defined the stable module invocation and prohibited programmable workflow
  inputs.
- Required a README mapping table from every architecture node to code,
  artifacts and tests.
- Scoped stress gating to deterministic correctness while reporting, but not
  marketing, machine-dependent performance.
- Added a reader path and kept future ideas outside the shipped architecture.

### Verdict

`PASS`: the approved design is small enough to build, strong enough to represent
the new architecture, and explicit enough for an external engineer to verify.
