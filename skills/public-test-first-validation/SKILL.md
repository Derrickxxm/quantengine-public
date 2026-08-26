---
name: public-test-first-validation
description: Establish the public Golden Path validation space before implementation by converting accepted requirements and architecture risks into positive, negative, and process tests. Do not use it to approve its own test results.
---

# Public Test-First Validation

Define how correctness and failure will be distinguished before implementation
evidence is accepted.

## Required inputs

- frozen acceptance criteria;
- identity-bound architecture packet;
- affected contracts and risk surfaces;
- current repository-owned test entry points.

## Validation space

Include at least one expected-success path, one expected-failure path, and any
process or provenance check needed to distinguish a real result from missing,
stale, or mismatched evidence. Name the owner of every expected fact.

Write a failing regression test when the requirement describes a defect and a
safe executable oracle exists. Preserve negative cases after the implementation
turns green.

Stop when the expected result is ambiguous, the test would define another
module's business truth, or the required evidence cannot be observed.

## Output boundary

Emit a validation plan and declared test identities. This Skill cannot weaken
acceptance criteria, suppress failures, certify the implementation, or grant
release authority.
