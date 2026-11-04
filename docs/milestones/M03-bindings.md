# M3 — Binding model, source access, identity, and persistence schemas

**Implements:** [Source Access](../spec/source-access.md), except copied-binding repair (M11); the schemas, [Reopening](../spec/lifecycle.md#reopening) behavior, and [Schema Versions](../spec/lifecycle.md#schema-versions) in [Persistence](../spec/lifecycle.md#persistence), except texture handling (M9) and display correspondence (M7); and the runtime-state rules (runtime indexes and in-memory stage attachments) in [Undo and Runtime State](../spec/lifecycle.md#undo-and-runtime-state).

**Depends on:** M1 (verified undo handlers, in-memory isolation candidates, and dirty-layer detection), M1b (evaluation front end and core language: a C++ core reading Hydra, so the identifier schemes are implemented in C++), M2 (draft browsing, live inspection, and persistent selection contract).

**Scope limits:**

- Delivers persistence schemas and tested source access. Persisted display behavior is completed by M5 (publication) and M7 (display correspondence).
- The undo test of the index rules runs in M5, once the stub application layer can create managed content.

**Decisions and deliverables:**

- The synchronization API signature.
- Caller-supplied source stages attached through their handles, with a distinct reused evaluation stage per binding, reproduced source-stage settings, dirty-layer handling, and explicit reloading.
- The per-binding attachment contract for attached sources.
- Identifier schemes for bindings and source entities that implement M2's draft browsing and persistent selection contract. Source-entity identifiers are USD paths plus instance context, never Hydra-generated paths or instancer indices. Display-resource identifiers are defined in M5, once the representation is chosen.
- A representation-independent ownership metadata format covering the concepts in [Ownership and Lifecycle](../spec/lifecycle.md#ownership-and-lifecycle). M5 defines the representation roles.
- Schemas for the persisted rows of the [Binding State](../spec/lifecycle.md#binding-state) model, including the pending-cleanup persistence contract. M5 settles the tracking mechanism and refines these schemas as needed.
- Schema versioning and migration behavior.
- The attached source stage is the binding's [live stage](../spec/interaction-contract.md#two-layers-and-the-live-stage) as soon as it is attached. Callers acquire sources and restore attachments after reopening; bindings never open source files or resolve file-opening paths.
- M4 reviews identifiers and schemas against the finalized interaction contract and updates them as needed before M5 begins.
- Defined behavior for unavailable sources and deleted destinations.
- Detection of copied bindings and ownership metadata, the disabled-pending-repair state, and the canonical-candidate rule. What counts as a duplicate representation is defined in M11.

**Tests:**

- Independent bindings sharing an attached stage, bindings on stages callers opened from `.usd`, `.usda`, and `.usdc` files, and an anonymous source with unsaved opinions and no file dependencies (`F-MULTI-BINDING`).
- With M1b's compiled core: releasing the caller's attached stage leaves the binding unattached. The core must not keep the stage alive: `UsdImagingStageSceneIndex` holds a strong reference until the chain is released (the feasibility bridge's explicit `release()`). Reattachment through the binding handle (`F-REATTACH`).
- `F-DIRTY-LAYER`, `F-PRIVATE-STAGE`, and `F-CACHED-STAGE`.
- Copied-binding detection from `F-OWNERSHIP-AMBIGUITY`.
- Loading older, failed-migration, and newer-schema records (`F-SCHEMA-VERSIONS`).
- Binding handles, configuration, the live stage, and persistent selection through save/reopen and undo (`F-BINDING-STATE`), and reopening with the source unavailable (`F-OFFLINE`).
- Compatibility tests for source-entity identifiers and persisted selection state against M2's draft contract.

**Exit condition:** independent bindings whose source access passes `F-DIRTY-LAYER`, `F-PRIVATE-STAGE`, and `F-CACHED-STAGE`, with versioned persistence schemas and indexes that survive reopening.
