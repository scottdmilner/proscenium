# M3 — Binding model, source access, identity, and persistence schemas

**Implements:** [Source Access](../spec/source-access.md), except copied-binding repair (M11); the schemas, [Reopening](../spec/lifecycle.md#reopening) behavior, and [Schema Versions](../spec/lifecycle.md#schema-versions) in [Persistence](../spec/lifecycle.md#persistence), except texture handling (M9) and display correspondence (M7); and the runtime-state rules (runtime indexes and in-memory stage attachments) in [Undo and Runtime State](../spec/lifecycle.md#undo-and-runtime-state).

**Depends on:** M1 (verified undo handlers, in-memory isolation candidates, and dirty-layer detection), M1b (evaluation front end and core language, which decide where the identifier schemes and inspection snapshot format are implemented), M2 (draft browsing, inspection metadata, and persistent selection contract).

**Scope limits:**

- Delivers persistence schemas and tested source access. Persisted display behavior is completed by M5 (publication) and M7 (display correspondence).
- The undo test of the index rules runs in M5, once the stub application layer can create managed content.

**Decisions and deliverables:**

- The synchronization API signature.
- Settled designs for file-backed refresh and in-memory sources, replacing the spec design notes, including the stage-level state reproduced for in-memory sources and the dirty-layer conflict check.
- Before settling file-backed refresh, review whether the current contract (exact disk state, no cached-stage reuse, fail on dirty contributing layers) costs more USD performance than it is worth. Use the M1 [feasibility record](../feasibility/runtime-record.md) and the M1b decision as input; if Hydra is adopted, weigh retaining an imaging pipeline across refreshes, since a fresh stage per refresh resets it. Record the outcome in the [Decision Register](../DECISIONS.md) row "Strictness of the file-backed refresh contract".
- The in-memory source key contract.
- Identifier schemes for bindings and source entities that implement M2's draft browsing and persistent selection contract. Source-entity identifiers are USD paths plus instance context, never Hydra-generated paths or instancer indices. Display-resource identifiers are defined in M5, once the representation is chosen.
- A representation-independent ownership metadata format covering the concepts in [Ownership and Lifecycle](../spec/lifecycle.md#ownership-and-lifecycle). M5 defines the representation roles.
- Schemas for the persisted rows of the [Binding State](../spec/lifecycle.md#binding-state) model, including the pending-cleanup persistence contract. M5 settles the tracking mechanism and refines these schemas as needed.
- Schema versioning and migration behavior.
- The source-side inspection snapshot format that implements M2's draft browsing and inspection metadata contract. M4 reviews identifiers and schemas against the finalized interaction contract and updates them as needed before M5 begins.
- Defined behavior for unavailable sources and deleted destinations.
- Detection of copied bindings and ownership metadata, the disabled-pending-repair state, and the canonical-candidate rule. What counts as a duplicate representation is defined in M11.

**Tests:**

- Isolation between a file-backed binding and an in-memory stage on the same file.
- If M1b adopts a compiled core: releasing the caller's in-memory stage leaves the binding unattached. The core must not keep the stage alive (the feasibility bridge holds a strong reference).
- `F-DIRTY-LAYER`, `F-PRIVATE-STAGE`, and `F-CACHED-STAGE`.
- Copied-binding detection from `F-OWNERSHIP-AMBIGUITY`.
- Loading older, failed-migration, and newer-schema records.
- Compatibility tests for source-entity identifiers, inspection fields, and persisted selection state against M2's draft contract.

**Exit condition:** independent bindings whose source access passes `F-DIRTY-LAYER`, `F-PRIVATE-STAGE`, and `F-CACHED-STAGE`, with versioned persistence schemas and indexes that survive reopening.
