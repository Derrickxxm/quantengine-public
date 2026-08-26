# Public Showcase Content Contract

Status: frozen baseline

Owner direction: 2026-08-26

Applies to: README, architecture documents, public modules, release notes, and
resume-to-repository reader path

## Objective

The public project must let a reviewer understand and verify how the system
combines specialist Native Agents into an evidence-backed software delivery
organization. It must preserve both the collaboration model and the control
mechanisms that prevent drift.

## Non-Deletion Rule

The following themes are required content. They may be clarified, reordered,
or moved into a linked deep-dive document, but they must not be silently
removed, collapsed into a generic phrase, or replaced by a tool list.

Deletion or material demotion requires an explicit Owner decision.

## Required Themes

| Theme | Question the public project must answer | Minimum public proof |
| --- | --- | --- |
| Specialist Agent collaboration | How do Architecture, Test, Development, and Ops work together? | role contracts, handoff flow, one end-to-end example |
| Test-first validation space | How is correctness defined before implementation? | failing case, negative case, process-validation plan |
| Graph-based architecture impact | How are affected modules and contracts identified? | revision-bound graph and architect packet |
| Ops from the beginning | How are CI/CD, artifacts, readback, and rollback prepared before release? | pipeline plan, package identity, rollback/readback receipt |
| Fingerprints and lineage | How can every downstream result prove its upstream dependencies? | producer-recorded identity edges and digest checks |
| Fail-closed gates | What happens when evidence is missing, stale, or inconsistent? | explicit blocked/failed negative paths |
| Inspectable evidence | Can a reviewer verify what actually ran after the Agent session ends? | manifests, receipts, CI results, replay and verdict artifacts |
| Learning flywheel | How do failures and decisions improve the next cycle? | problem-reflection-decision-code-evidence-result AAR |
| Native Agent operating model | Which work requires current-context reasoning? | bounded Agent role and current-state readback |
| Skill-led workflow | How is the operating procedure preserved without hard-coding all branches? | readable Skill with role, evidence, stop, and approval rules |
| Small deterministic CLI / Tool | Which facts and gates must be mechanically repeatable? | narrow commands with closed inputs and explicit outputs |
| Skill / Native Agent / CLI boundary | Which layer owns judgment, variable execution, and deterministic mechanics? | explicit responsibility boundary and narrow runnable tools |
| Goal and task control | How are objective and acceptance drift prevented? | OGSM, Plane, Git, and Owner-decision bindings |
| Quality campaign and independent verdict | How are risk surfaces selected without creating a second truth owner? | QCS advisory evidence plus Quality Shield verdict |
| Complete domain-provider chain | Which module owns research, strategy, data, causality, execution, and deployment facts? | explicit module ownership and one synthetic golden path |
| Public/private boundary | What is real, synthetic, implemented, planned, or withheld? | status labels, security scan, explicit non-authority statements |

## Content Placement

### Resume

The resume compresses the architecture into a small causal narrative:

1. why the single-Agent / heavy-CLI approach failed;
2. how specialist Agents and test-first validation changed delivery;
3. how fingerprints, gates, evidence, and independent verification prevent
   drift;
4. how Skills, small tools, and the learning flywheel preserve improvement.

The resume links to the repository; it does not carry the full module manual.

### README

The README must name every required architectural theme, show the intended
system effect, state the current implementation boundary, and provide a short
review path. It does not carry the historical problem narrative.

### Deep-Dive Documents

Deep-dive documents own detailed role contracts, identity schemas, gates,
evidence structures, flywheel decisions, module boundaries, and implementation
status. Moving detail out of the README is allowed only when the README retains
the concept and a working link.

### Runnable Public Code

Every important architectural claim eventually requires a positive path, a
negative path, inspectable evidence, and a statement of what the module cannot
authorize. A document alone marks a module as `PLANNED`, not `IMPLEMENTED`.

## Change-Control Check

Before accepting a future README or architecture rewrite:

1. compare the change against the required-theme table;
2. identify every deleted or materially shortened theme;
3. confirm the replacement location and link;
4. reject the change if a theme loses its reader question or minimum proof;
5. record explicit Owner approval for any intentional removal.
