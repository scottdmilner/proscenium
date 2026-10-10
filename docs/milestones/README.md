# Implementation Milestones

These files detail the implementation milestones for the requirements in [PROJECT.md](../PROJECT.md), [spec/](../spec/invariants.md), and [testing/](../testing/strategy.md). Each milestone lists the spec sections it implements and adds only milestone-specific scope, deliverables, tests, and exit conditions. Where a milestone conflicts with the requirement files, the requirement files take precedence.

Before working on any milestone, read [PROJECT.md](../PROJECT.md), [spec/invariants.md](../spec/invariants.md), and the milestone's file, then the spec files its **Implements** line links to.

## Milestones

| Milestone | Depends on |
|---|---|
| [M1 — Runtime feasibility, workspace, and test infrastructure](M01-runtime.md) | — |
| [M1b — Evaluation front end and core language gate](M01b-evaluation-gate.md) | M1 |
| [M2 — Display, inspection, and interaction contracts](M02-contracts.md) | M1 |
| [M3 — Binding model, source access, identity, and persistence schemas](M03-bindings.md) | M1, M1b, M2 |
| [M4 — Display representation and interaction feasibility prototypes](M04-prototypes.md) | M2, M3 |
| [M5 — Synchronization architecture, diagnostics, and failure safety](M05-architecture.md) | M3, M4 |
| [M6 — Snapshot evaluation and representation planning](M06-evaluation.md) | M3, M5 |
| [M7 — Blender application and source inspection UI](M07-application.md) | M4, M5, M6 |
| [M8 — Validated mesh and primvar translation](M08-geometry.md) | M6, M7 |
| [M9 — Material translation and binding resolution](M09-materials.md) | M4, M8 |
| [M10 — Complete native instancing](M10-instancing.md) | M4, M8, M9 |
| [M11 — Ownership reconciliation, detach, and lifecycle operations](M11-lifecycle.md) | M5, M7, M10 |
| [M12 — Complete and qualify Phase 1](M12-phase-1.md) | M1–M11, including M1b |
| [M13 — Incremental change discovery and dependency invalidation](M13-change-discovery.md) | M10, M11, M12 |
| [M14 — Incremental application and Phase 2 qualification](M14-phase-2.md) | M13 |

## Ordering Constraints

- M1b decides the evaluation front end and the core's language (Python, or C++ with Hydra) before M3 defines the identifier schemes and inspection snapshot format that the core implements.
- The interaction contract is settled and display representations are prototyped before a display backend is committed.
- Evaluation/planning (M6) and application (M7) are deliberately separate milestones, and every later feature milestone extends both sides explicitly (see [Why the Boundary Is Enforced](../spec/pipeline.md#why-the-boundary-is-enforced)).
- M4 freezes the primvar and material cases needed for backend feasibility before selecting a representation. M8 and M9 complete their support matrix and grammar before implementation; additions or changes affecting backend feasibility, sharing, or partitioning require rerunning the relevant M4 prototypes and updating the decision record and affected milestones.
- Phase ordering follows [Delivery Phases](../PROJECT.md#delivery-phases).

## Milestone Structure

Each milestone uses this structure:

- **Implements:** the spec sections whose requirements this milestone delivers.
  - An unqualified link puts every requirement in that section in scope, unless a scope limit says otherwise.
  - A qualified link puts only the named part in scope: "the X in [Section]", "[Section] schemas", or "[Section], except Y". A parenthetical names the milestone that owns the rest.
  - Each requirement is delivered by one milestone. M2 defines contracts that later milestones implement, and M12 and M14 qualify work delivered earlier; their Implements lines overlap with others by design.
  - The requirement-to-test matrix (M1) covers every in-scope requirement, records its authoritative spec section, delivering milestone, fixture and test or oracle, and qualifying milestone, and takes precedence over Implements lines. M4 marks the high-risk entries, from its risk matrix. Invariant summaries reference the authoritative requirement ID; contract decisions update the matrix before implementation.
- **Depends on:** earlier milestones and what they provide.
- **Scope limits:** what this milestone deliberately leaves out.
- **Decisions and deliverables:** artifacts produced and decisions recorded. Settled decisions update the [Decision Register](../DECISIONS.md).
- **Tests:** milestone-specific tests only. General test expectations are in [Testing Strategy](../testing/strategy.md). Fixture IDs such as `F-DIRTY-LAYER` refer to the [Named Contract Fixtures](../testing/strategy.md#named-contract-fixtures).
- **Exit condition:** one measurable statement.
