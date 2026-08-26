---
name: public-ops-delivery-review
description: Prepare CI, artifact identity, runtime readback, and rollback requirements for one public Golden Path change. Do not use it to deploy or convert a merged change into runtime evidence.
---

# Public Ops Delivery Review

Define the delivery evidence required to distinguish source completion from an
accepted runtime result.

## Required inputs

- admitted patch and source identities;
- declared test results and independent quality requirements;
- build and artifact contract;
- target public-demo runtime and explicit authority boundary.

Require CI results, content-addressed artifacts, environment or runner identity,
post-run readback, and a rollback condition. A skipped required check, missing
artifact digest, stale build, or absent readback remains blocked.

Treat commit, merge, image build, runtime start, runtime health, and release
authority as different facts.

## Output boundary

Emit an Ops delivery plan and required receipt inventory. This Skill cannot
deploy, mutate Paper or Real, invent runtime health, sign Quality Shield
evidence, or grant release authority.
