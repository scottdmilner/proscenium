# Implementation Sequence

This document details the implementation milestones for [PROJECT.md](PROJECT.md). PROJECT.md defines the requirements; each milestone lists the PROJECT.md sections it implements and adds only milestone-specific scope, deliverables, tests, and exit conditions. Where the two documents conflict, PROJECT.md takes precedence.

Each milestone uses this structure:

- **Implements:** the PROJECT.md sections whose requirements this milestone delivers. Every requirement in a listed section is in scope unless a scope limit says otherwise. For high-risk guarantees, the requirement-to-test matrix (P1) records the delivering milestone, test, and qualifying milestone more precisely.
- **Depends on:** earlier milestones and what they provide.
- **Scope limits:** what this milestone deliberately leaves out.
- **Decisions and deliverables:** artifacts produced and decisions recorded. Settled decisions update the PROJECT.md [Decision Register](PROJECT.md#decision-register).
- **Tests:** milestone-specific tests only. General test expectations are in PROJECT.md's [Testing Strategy](PROJECT.md#testing-strategy). "Fixture N" refers to the named contract fixtures listed there.
- **Exit condition:** one measurable statement.

## P1 — Runtime feasibility, workspace, and test infrastructure

**Implements:** [Compatibility and Development](PROJECT.md#compatibility-and-development), [Testing Strategy](PROJECT.md#testing-strategy) infrastructure, [Acceptance Criteria](PROJECT.md#acceptance-criteria) specification.

**Depends on:** nothing.

**Scope limits:** P1 is a stop/go gate. Runtime feasibility is verified before investing in tooling polish; if it fails, the implementation strategy is revisited before P2.

**Decisions and deliverables:**

- A runtime feasibility record for each platform:
  - Exact Blender build and version, embedded Python version, USD version, and available USD modules.
  - Runtime module paths and relevant USD plugin discovery.
  - Whether a supported distribution can exchange stage objects with caller code.
  - Extension packaging results.
- Verified runtime behaviors that later milestones depend on:
  - Post-load, post-undo, and post-redo handlers fire reliably, including in the test runner.
  - A synchronization invoked from the Python API can push its own undo step, and undo behavior with global undo disabled and in background mode.
  - Candidate approaches from the [In-Memory Sources](PROJECT.md#in-memory-sources) design note behave as expected.
  - Contributing layers with unsaved edits can be detected, and a fresh stage can be opened without reusing a cached one.
  - Whether a private disk view can be built without touching shared layers (see [File-Backed Refresh](PROJECT.md#file-backed-refresh)).
- The extension layout, development environment, build script, lint/type-check hooks, and `AGENTS.md`.
- A minimal register/unregister extension.
- Test infrastructure:
  - Pure unit tests where possible.
  - Blender integration tests.
  - Temporary USD fixture generation.
  - Save/reopen and undo/redo test support.
  - Cross-platform smoke tests.
  - Reused Blender test processes with explicit state reset, retaining isolated processes where necessary.
- The acceptance specification (checksums, sampled time-code set, bounds comparison contract, reference-hardware configuration), the ALab inventory for each payload policy, and the smaller generated CI fixture, all as described in Acceptance Criteria.
- A requirement-to-test matrix for high-risk guarantees: requirement → delivery milestone → test or oracle → qualification milestone.

**Exit condition:** the runtime feasibility record shows the required Blender/USD combination works on all three platforms (or the strategy has been revised), and a reproducible development/test/package workflow and the acceptance specification exist.

## P2 — Display, inspection, and interaction contracts

**Implements:** [Core Architecture](PROJECT.md#core-architecture), [Source Inspection and Interaction](PROJECT.md#source-inspection-and-interaction), and [Interaction Testing](PROJECT.md#interaction-testing).

**Depends on:** P1 (headless test infrastructure).

**Scope limits:**

- Produces a **draft** contract. P4 answers its feasibility questions and finalizes it.
- The contract defines what the display layer must provide without prescribing its Blender structure.

**Decisions and deliverables:**

- A draft interaction contract covering everything Source Inspection and Interaction says the contract must settle, expressed as headless-testable functions. This includes the browsing universe, the supported inspection metadata set, and the identity of persistent selection state.
- A list of feasibility questions that depend on what Blender can actually do, such as whether individual instances inside a batched representation can be resolved from pick data.

**Exit condition:** a draft contract of testable inspection and interaction requirements that can be evaluated against different display implementations, plus a list of open feasibility questions for P4.

## P3 — Binding model, source access, identity, and persistence schemas

**Implements:** [Bindings and Source Access](PROJECT.md#bindings-and-source-access) (including [Source Consistency](PROJECT.md#source-consistency), [Source Identity](PROJECT.md#source-identity), [Copied Bindings](PROJECT.md#copied-bindings), [In-Memory Sources](PROJECT.md#in-memory-sources), and [File-Backed Refresh](PROJECT.md#file-backed-refresh)), [Persistence](PROJECT.md#persistence) schemas, and the runtime-index rules in [Undo and Runtime State](PROJECT.md#undo-and-runtime-state).

**Depends on:** P1 (verified undo handlers, in-memory isolation candidates, and dirty-layer detection).

**Scope limits:**

- Delivers persistence schemas and tested source access. Persisted display behavior is completed by P5 (publication) and P7 (display correspondence).
- The undo test of the index rules runs in P5, once the stub application layer can create managed content.

**Decisions and deliverables:**

- The synchronization API signature.
- Settled designs for file-backed refresh and in-memory sources, replacing the PROJECT.md design notes, including the stage-level state reproduced for in-memory sources and the dirty-layer conflict check.
- The in-memory source key contract.
- Identifier schemes for bindings and source entities. Display-resource identifiers are defined in P5, once the representation is chosen.
- A representation-independent ownership metadata format that keeps resource identity, ownership, source coverage (possibly many entities), representation role, and usage separate. P5 defines the representation roles.
- Schemas for the [Binding State](PROJECT.md#binding-state) model: binding configuration with requested settings, published generation, and last attempt.
- Schema versioning and migration behavior.
- The source-side inspection snapshot format.
- Defined behavior for unavailable sources and deleted destinations.
- Detection of copied bindings and ownership metadata, the disabled-pending-repair state, and the canonical-candidate rule. What counts as a duplicate representation is defined in P11.

**Tests:**

- Isolation between a file-backed binding and an in-memory stage on the same file.
- Fixtures 1, 2, and 3.
- Copied-binding detection from Fixture 8.
- Loading older, failed-migration, and newer-schema records.

**Exit condition:** independent bindings whose source access passes Fixtures 1–3, with versioned persistence schemas and indexes that survive reopening.

## P4 — Display representation and interaction feasibility prototypes

**Implements:** the representation options in [Core Architecture](PROJECT.md#core-architecture) and the prototyping constraint in [Implementation Sequence](PROJECT.md#implementation-sequence).

**Depends on:** P2 (draft contract and feasibility questions), P3 (source-entity identity).

**Scope limits:**

- Prototypes are not production code.
- Interaction feasibility is established through the headless interaction functions only (see [Interaction Testing](PROJECT.md#interaction-testing)).
- Not every approach needs an equally complete prototype.

**Decisions and deliverables:**

- A simple object/collection baseline, tested against a risk matrix of the highest-risk requirements.
- Targeted prototypes of batching (such as Geometry Nodes) or a hybrid partitioned by assets or independently updated subtrees, only where the baseline fails a requirement or its measured costs justify the alternative.
- A stress fixture combining shear, negative-determinant transforms, nonuniform scale, reset transform stacks inside instances, nested instances with differing appearance, and separate viewport/render purposes. The question is whether the representation supports these in combination while preserving geometry sharing.
- Each evaluated representation also exercises:
  - Multi-mesh, multi-material assets.
  - Required per-instance shading variation.
  - Source lookup from pick data.
  - Highlighting and framing source selections.
  - Small updates within larger scenes.
  - Detaching a whole binding, including any materialization the representation requires.
- Provisional performance budgets, and measurements of initial construction, refresh, interaction, and resource costs against them. Interaction costs are defined in [Interaction Testing](PROJECT.md#interaction-testing).
- Answers to every P2 feasibility question and the finalized interaction contract.
- For the chosen representation, a record of what a real viewport pick is assumed to supply, as an accepted risk.
- A partitioning decision record:
  - The partition unit, such as one per model or per prototype.
  - What a partition owns.
  - How a partition is replaced as a whole.
- Recorded limitations and fallbacks.

Later milestones build on the partitioning decision. Changing it requires revising the record and listing the affected milestones.

**Exit condition:** a display design that passes the risk matrix and stress fixture, validated against the finalized interaction contract at the level of the headless interaction functions, and a recorded partitioning decision—not merely a fast static-scene prototype.

## P5 — Synchronization architecture, diagnostics, and failure safety

**Implements:** [Synchronization Layer Boundaries](PROJECT.md#synchronization-layer-boundaries), [Diagnostics](PROJECT.md#diagnostics), [Synchronization Transaction](PROJECT.md#synchronization-transaction), the synchronization undo policy in [Undo and Runtime State](PROJECT.md#undo-and-runtime-state), and publication of the [Binding State](PROJECT.md#binding-state) model.

**Depends on:** P3 (ownership metadata, binding-state schemas, and index rules), P4 (partitioning decision).

**Decisions and deliverables:**

- Interfaces between evaluation, representation planning, and application, including the planning context.
- Display-resource identifiers and representation roles, based on the P4 partitioning decision.
- A minimal display-plan envelope covering partitions, ownership entries, correspondence entries, and placeholder content.
- Schema/behavior dispatch and dependency resolution.
- The transaction implementation: the commit point, what publication switches, how prepared work is discarded, and the copy-on-write or rollback discipline that keeps published resources unchanged during preparation.
- Requested, published, and last-attempt state recorded separately.
- Retirement with pending-cleanup diagnostics for resources that could not be removed.
- A stub application layer that consumes the plan envelope and creates trivial placeholder content, so failure safety can be tested before P7 exists.
- Ownership-aware resource accounting.
- A measurement of the synchronization undo step's memory cost.

**Tests:**

- Failure-injection tests at each transaction boundary, run against the stub application layer and rerun unchanged against the real application layer in P7. They assert that the whole published generation is unchanged.
- Fixtures 4, 6, and 7.
- Undo: delete stub-created managed content, undo, and verify the P3 indexes are consistent again.
- Undo step count: one per published synchronization, none for a failed one, none doubled when an operator calls the API.

**Exit condition:** using the stub application layer, a failure at any boundary before publication leaves the entire published generation unchanged, and a retirement failure after publication leaves the new generation active with leftovers tracked.

## P6 — Snapshot evaluation and representation planning

**Implements:** [Evaluated Source Snapshot](PROJECT.md#evaluated-source-snapshot), [Display Plan](PROJECT.md#display-plan), [Transforms and Time Codes](PROJECT.md#transforms-and-time-codes), [Coordinate Conversion](PROJECT.md#coordinate-conversion), [Visibility and Purpose](PROJECT.md#visibility-and-purpose), and [Models and Unsupported Content](PROJECT.md#models-and-unsupported-content).

**Depends on:** P3 (identifier schemes), P5 (layer interfaces and diagnostics).

**Scope limits:**

- Initial scope is hierarchy, transforms, bounds, and placeholders. Native instances, shared contents, and instance-context identities are identified here, but their descriptions are provisional. Meshes come in P8, materials in P9, and complete instancing in P10.
- The snapshot and the plan may be implemented in the same milestone, but remain distinct outputs.

**Decisions and deliverables:** extensions to the P5 plan envelope that carry evaluated content, with provisional instance and geometry descriptions labeled as such.

**Tests:**

- Snapshot and plan assertions for the initial scope, including sharing, correspondence, and diagnostics.
- Time-code and settings changes, including the USD default time code and coordinate conversion with different supplied unit scales and up-axis settings.
- Determinism: identical snapshot, settings, and planning context yield identical plans.
- Per-behavior dispatch: an unsupported behavior on a prim does not suppress its supported behaviors.

**Exit condition:** a supported initial snapshot can be evaluated and planned deterministically, yielding an inspectable source hierarchy and a spatially meaningful plan, with no Blender objects or datablocks created.

## P7 — Blender application and source inspection UI

**Implements:** [Blender Application](PROJECT.md#blender-application), the inspection requirements in [Source Inspection and Interaction](PROJECT.md#source-inspection-and-interaction), the application side of [Coordinate Conversion](PROJECT.md#coordinate-conversion), display-correspondence persistence in [Persistence](PROJECT.md#persistence), and stale-content retirement and external-usage protection in [Ownership and Lifecycle](PROJECT.md#ownership-and-lifecycle).

**Depends on:** P4 (partitioning decision and finalized interaction contract), P5 (application-layer interface, transaction, and stub tests), P6 (display plans).

**Scope limits:** repair of user-modified content is P11 work.

**Decisions and deliverables:**

- The real application layer for the chosen representation, connected to P5's ownership tracking, transaction, and publishing.
- Partition-level replacement from the start, following the P4 partitioning decision, even though Phase 1A rebuilds everything.
- Basic reconciliation: each synchronization builds a fresh set of partitions, publishes it, and retires the previous result, deleting only obsolete resources that are safe to remove under the ownership and external-usage rules. Managed resources with unmanaged users are released intact, not deleted or mutated.
- The source inspector, and the agreed browsing, selection, highlighting, and framing behavior from the finalized interaction contract.

**Tests:**

- Resulting Blender content and source correspondence for hand-constructed plans.
- Repeated application: several unchanged synchronizations leave datablock counts unchanged.
- The P5 failure-injection tests, rerun unchanged against the real application layer.
- Application-time resource failures abort the transaction unless the plan authorized a fallback.
- Fixture 9.
- End-to-end tests using P6-generated plans.

**Exit condition:** the application layer displays and inspects plans, passes the P5 failure-injection suite and Fixture 9, and meets the boundary rule in Blender Application.

## P8 — Validated mesh and primvar translation

**Implements:** [Geometry and Primvars](PROJECT.md#geometry-and-primvars), time-varying topology in [Transforms and Time Codes](PROJECT.md#transforms-and-time-codes), and correspondence through batching in [Source Inspection and Interaction](PROJECT.md#source-inspection-and-interaction).

**Depends on:** P6 (snapshot and planning), P7 (application layer).

**Decisions and deliverables:**

- First, before implementation: the primvar support matrix and mesh classification rules required by Geometry and Primvars.
- Evaluation/planning: validated geometry and primvar data in the snapshot and plan.
- Application: mesh data, attributes, and modifiers created from the plan.

**Tests:**

- Focused invalid-data and edge-case fixtures, one per support-matrix row and classification case.
- The P5 failure-injection tests, rerun with geometry writes.

**Exit condition:** safe supported geometry at any supplied time code, matching the support matrix, with source correspondence intact.

## P9 — Material translation and binding resolution

**Implements:** [Materials](PROJECT.md#materials), and texture handling in [Reopening](PROJECT.md#reopening).

**Depends on:** P4 (per-instance variation approach), P8 (UVs and primvars).

**Scope limits:** per-instance material variation is completed and tested in P10. P9 designs material inputs to accept per-instance data, following the P4 variation approach.

**Decisions and deliverables:**

- First, before implementation: the bounded connection grammar and `displayColor`/`displayOpacity` interaction rules required by Materials.
- Evaluation/planning: effective material bindings, translated networks, and material inputs that accept per-instance data.
- Application: materials, nodes, images (as external file references), and assignments.
- Ownership and reuse rules for translated materials, images, node groups, and dependencies.

**Tests:**

- Display batching does not collapse distinct material assignments or attribute meanings.
- Material inputs accept per-instance data supplied through hand-constructed plans.
- Headless render assertions on controlled material fixtures.
- Fixtures 5 and 11.

**Exit condition:** the material grammar works within the chosen display representation, and material and image failures leave the published generation unchanged.

## P10 — Complete native instancing

**Implements:** [Native Instancing](PROJECT.md#native-instancing).

**Depends on:** P4 (prototypes and partitioning scheme), P8 (meshes), P9 (materials).

**Scope limits:** works within the P4 partitioning scheme.

**Decisions and deliverables:**

- Evaluation/planning: complete instancing, shared contents, instance context, and per-instance variation in the snapshot and plan, replacing P6's provisional descriptions.
- Application: shared and per-instance display behavior, and instance-root selection.
- Dependency tracking between shared contents and their displayed uses.

**Tests:**

- Per-instance material variation, including per-instance `displayColor` and named primvars driving material inputs.
- Nested combinations, not just isolated instancing features: Fixture 12.
- Sharing assertions: expected uses share geometry, required distinct geometry stays distinct.
- Multiple bindings and shared-content changes.
- Benchmarks of representative scenes.

**Exit condition:** complete instancing behavior within the P4 partitioning scheme, passing Fixture 12, with shared-content dependency tracking that P13 can use for invalidation.

## P11 — Ownership reconciliation, detach, and lifecycle operations

**Implements:** [Ownership and Lifecycle](PROJECT.md#ownership-and-lifecycle), [Copied Bindings](PROJECT.md#copied-bindings) repair, and the lifecycle undo/redo requirements in [Undo and Runtime State](PROJECT.md#undo-and-runtime-state).

**Depends on:** P5 (representation roles and pending-cleanup tracking), P7 (basic reconciliation), P10 (complete instancing and sharing).

**Scope limits:** optimized repair of individual partitions without a full rebuild is Phase 1B work (P13/P14). P11 repairs damage correctly through full refresh.

**Decisions and deliverables:**

- **Cleanup:** remove duplicate or obsolete managed content and unused exclusively owned resources, and retry pending retirements.
- **Detach:** whole-binding detach, materializing whatever the representation requires so the detached result has no dependency on managed resources or extension runtime state.
- **Remove binding:** remove configuration and managed content, preserving detached and unrelated content.
- Duplicate representations defined by source coverage and representation role, and removed, such as content a user duplicated.
- Conservative handling of content with copied or missing ownership evidence: report ambiguous candidates; never claim or delete them automatically.
- User-facing repair of bindings disabled pending repair: make a new binding, or detach.
- Undo/redo of every lifecycle operation.

**Tests:**

- The P3 index rebuilding stays correct after detach, cleanup, and removal, including their undo/redo.
- Fixtures 8, 10, and 15.

**Exit condition:** cleanup, detach, and binding removal pass Fixtures 8, 10, and 15 with correct undo/redo, even when Blender objects do not correspond individually to USD prims.

## P12 — Complete and qualify Phase 1A

**Implements:** [Phase 1A](PROJECT.md#delivery-phases) and [Acceptance Criteria](PROJECT.md#acceptance-criteria).

**Depends on:** P1–P11.

**Decisions and deliverables:**

- Completed binding settings, manual-sync controls, inspection UI, and diagnostics UI, including requested/published/last-attempt display.
- Completed support matrices and deployment documentation.
- Phase 1A baselines, as defined in Acceptance Criteria.

**Tests:**

- The full acceptance suite, including the ALab criteria, the bounds comparison contract, and the interior-correctness fixtures.
- Agreed picking, highlighting, and framing behavior, exercised through the headless interaction functions.
- Correspondence after rebuilding or repartitioning.
- Inspection of saved displays with unavailable sources.
- Failures injected at every transaction boundary.
- Fixtures 11 and 16, and every fixture assigned to earlier milestones.

**Exit condition:** every Phase 1A entry in the requirement-to-test matrix passes, including the full ALab acceptance suite.

## P13 — Incremental change discovery and dependency invalidation

**Implements:** change discovery, invalidation, and [Affected Content](PROJECT.md#affected-content) in [Incremental Synchronization](PROJECT.md#incremental-synchronization).

**Depends on:** P10 (shared-content dependency tracking), P11 (lifecycle and repair behavior), P12 (Phase 1A baselines).

**Decisions and deliverables:**

- Phase 1B performance target values and churn budgets for replacement-affected resources.
- A change matrix enumerating the change cases in Incremental Synchronization.
- A mapping from source-affected entities to dependency-affected and replacement-affected display resources.
- A decision on when local updates, partition rebuilds, or explicit full rebuilds are appropriate.
- Discovery of managed display damage, distinguished from legitimate external users.

**Tests:**

- Affected-resource sets for every change-matrix case, including changes that cross batching or shared-content boundaries.
- Old and new dependencies when structure or relationships change.
- Missed or coalesced change notifications.
- Fixtures 13 and 14.

**Exit condition:** correct affected-resource sets for every case in the change matrix, within the churn budgets.

## P14 — Incremental application and Phase 1B qualification

**Implements:** [Phase 1B](PROJECT.md#delivery-phases), incremental application in [Incremental Synchronization](PROJECT.md#incremental-synchronization), incremental guarantees in [Synchronization Transaction](PROJECT.md#synchronization-transaction), and the incremental tests in [Testing Strategy](PROJECT.md#testing-strategy).

**Depends on:** P13 (affected-resource sets, targets, and budgets).

**Decisions and deliverables:**

- A validated in-memory-stage integration interface.
- Incremental application, including repair of damaged content in individual partitions without a full rebuild.

**Tests:**

- Repeated edits, topology changes, inherited changes, and repartitioning.
- Incremental results compared against clean rebuilds for every change-matrix case.
- Failure injection during incremental mutation.
- Resource growth over long edit sequences.
- Fixture 16 with zero unnecessary writes.

**Exit condition:** for the change matrix, incremental results are semantically equivalent to clean rebuilds, preserve identities and avoid writes outside approved affected resources, survive failure injection, show no unbounded resource growth, and meet the recorded synchronization and interaction targets.
