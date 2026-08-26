---
name: public-bounded-development
description: Produce one implementation proposal for an approved public Golden Path handoff, restricted to its exact source identity, allowed files, contracts, and validation plan. Do not use it for scope changes, merge, or deployment.
---

# Public Bounded Development

Implement the approved change without redefining the task or its proof.

## Required inputs

- exact Worker handoff and upstream artifact digests;
- repository, branch, full commit, and source-tree identity;
- allowed paths and forbidden scope;
- architecture packet and validation plan.

Re-read the current source before editing. Stop if identity has drifted, if the
required change escapes allowed paths, or if implementation requires changing
the accepted objective or test meaning.

Return the changed paths, deterministic patch identity, implementation notes,
and declared tests. Preserve failing evidence until the relevant code change is
made.

## Output boundary

This Skill proposes a bounded change. It cannot approve its own tests, change
task state, commit, push, merge, publish artifacts, or deploy.
