---
name: public-architecture-review
description: Review one public Golden Path task against its exact source identity and current code graph, then produce a bounded architecture packet before implementation. Do not use it to implement code or approve release.
---

# Public Architecture Review

Produce an architecture packet that another role can implement and test without
reinterpreting the requirement.

## Required inputs

- frozen objective, measures, non-goals, and acceptance criteria;
- exact task identity;
- repository, branch, full commit, and source-tree identity;
- revision-bound code graph;
- declared change class and repository scope.

## Review

Identify affected components, public contracts, upstream and downstream
consumers, risk surfaces, allowed paths, forbidden scope, and the validation
questions that must be answered before acceptance.

Stop with a named blocker when the task, source, graph revision, repository
scope, or acceptance criteria are missing or inconsistent. Do not infer current
architecture from chat memory.

## Output boundary

Emit one identity-bound architecture packet for one repository. The packet may
recommend task decomposition or an upgraded change class. It cannot modify
code, dispatch a Worker, approve quality, merge, or deploy.

Use the artifact envelope in
[`contracts/public_delivery/artifact.v1.schema.json`](../../contracts/public_delivery/artifact.v1.schema.json).
