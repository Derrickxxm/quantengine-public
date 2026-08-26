# Public Showcase Three-Pass Review

Date: 2026-08-26

Scope: README and `docs/multi_agent_public_architecture.md`

Decision: retain all confirmed themes; improve hierarchy and implementation
truth without deleting content

## Pass 1: Reader And Objective Fit

### Finding

The new README now leads with the specialist-Agent delivery model, but the first
diagram alone does not show the fingerprints, gates, evidence store, provider
modules, or learning loop. A reader could still interpret those mechanisms as
secondary implementation details.

### Revision

- Retain the readable Agent-team diagram in the README.
- Add an expanded end-to-end architecture diagram in the linked architecture
  document.
- Freeze fingerprints, gates, evidence, flywheel, and Skill/CLI migration as
  required public themes.

### Result

The README explains the operating idea quickly; the architecture document must
show the full causal system without hiding control mechanisms.

## Pass 2: Evidence And Claim Safety

### Finding

The current repository implements the QuantEngine validation slice, not every
Agent and provider shown in the target architecture. Without explicit status,
the introduction could make a design target look like a completed public
implementation.

### Revision

- Keep `quantengine-public` labeled as the current runnable slice.
- Label every additional public module `PLANNED` until code, contracts, tests,
  example evidence, and a public boundary exist.
- Preserve the distinction between private-system evidence and public runnable
  evidence.

### Result

The repository may explain the complete system while remaining honest about
what a reviewer can execute today.

## Pass 3: Implementation Minimalism

### Finding

Creating a separate public repository, service, queue, database, dashboard, or
large CLI for every private module would reproduce the complexity the
architecture is intended to remove.

### Revision

- Build the first complete public version as one reviewable repository with
  multiple explicit logical modules.
- Use Skills for high-judgment workflows and small tools for deterministic
  state, identity, evidence, and gates.
- Implement one end-to-end synthetic Golden Path before expanding individual
  modules.
- Enforce module boundaries with contracts, tests, and import rules rather than
  creating infrastructure for appearance.

### Result

The next implementation milestone is one thin vertical path:

```text
synthetic requirement
  -> architecture packet
  -> validation space and failing test
  -> bounded implementation
  -> CI/CD artifact
  -> independent quality verdict
  -> immutable evidence
  -> AAR and next-cycle decision
```

## Review Conclusion

The direction passes all three reviews with two conditions:

1. the required-content contract remains enforced; and
2. target architecture and current implementation status remain visibly
   separate.

No existing important theme is approved for deletion.

## Release-Prep Correctness Addendum

The implementation review found four evidence-contract gaps after the content
review: late blockers lacked their valid causal prefix; upstream digest edges
did not confirm the declared upstream type; artifact types were not checked
against their owning producer; and a failed or non-release artifact could carry
non-zero authority.

The Golden Path now rejects each case. Negative receipts preserve the valid
prefix, bind the exact rejected request digest, and retain the public-safe input
beside the receipt. The JSON Schema and runtime verifier both require all
authority to remain false unless the artifact is a passing release verdict.
