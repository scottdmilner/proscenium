# M5 — Synchronization architecture, diagnostics, and failure safety

**Implements:** the interfaces and boundary rules in [Synchronization Layer Boundaries](../spec/pipeline.md#synchronization-layer-boundaries) (M6 and M7 implement the layers themselves), [Diagnostics](../spec/pipeline.md#diagnostics), [Synchronization Transaction](../spec/pipeline.md#synchronization-transaction) for full rebuilds (M14 covers incremental mutation), the synchronization undo policy in [Undo and Runtime State](../spec/lifecycle.md#undo-and-runtime-state), and publication of the [Binding State](../spec/lifecycle.md#binding-state) model.

**Depends on:** M3 (ownership metadata, binding-state schemas, and index rules), M4 (partitioning decision).

**Decisions and deliverables:**

- Interfaces between evaluation, representation planning, and application, including the planning context. With M1b's C++ core, the display plan interface is the language boundary: the plan's types as seen from Python, large arrays exposed without copying, and conversion of C++ errors into Python exceptions and diagnostics before any Blender mutation.
- Display-resource identifiers and representation roles, based on the M4 partitioning decision. The manifest entry's role (M3's ownership format) becomes a `StrEnum` of these roles; it is stored as the same string, so no schema migration is needed, and an unknown role becomes a refusal.
- A minimal display-plan envelope covering partitions, ownership entries, correspondence entries, and placeholder content.
- Schema/behavior dispatch and dependency resolution. Display dispatch is over Hydra prim types, while source inspection still reads the USD stage.
- The transaction implementation: the commit point, what publication switches, how prepared work is discarded, and the copy-on-write or rollback discipline that keeps published resources unchanged during preparation.
- Recording of the Binding State model during synchronization.
- Retirement with pending-cleanup diagnostics for resources that could not be removed.
- A decision and implementation for persistent cleanup tracking: evaluate a separate ledger and pending-cleanup state in existing ownership records, then record the chosen mechanism and its schema, following M3's pending-cleanup persistence contract (DECISIONS.md), and add its unreadable and unsupported records to `F-SCHEMA-VERSIONS`. Cover newly prepared and obsolete resources, failed pre-publication disposal, and safe explicit retry, preserving reused published resources.
- A stub application layer that consumes the plan envelope and creates trivial placeholder content, so failure safety can be tested before M7 exists.
- Ownership-aware resource accounting.
- A measurement of the synchronization undo step's memory cost.
- Publication and cleanup through M3's bindings' state ([M3 plan](../plans/M03-bindings.md), D8): a publication writes its manifest whole, and cleanup removes content through the state, or publishes the manifest without a datablock before removing it, so a removal costs what it removes rather than a reread of its manifest. A new entry point that uses a binding's source compares the runtime sources with the bindings after a rebuild of the state, as `proscenium/api/synchronization.py` describes.
- A measurement of the cached manifests' memory with M4's representation and realistic source coverage, against its budget: about 5 MB per 10,000 entries covering three paths each in M3. The M3 plan's Phase E lists ways to hold less.
- Whether a publication may give a binding whose destination was removed a new destination ([Removed Destination](../spec/lifecycle.md#removed-destination)), decided with M11.

**Tests:**

- Failure-injection tests at each transaction boundary, run against the stub application layer and rerun unchanged against the real application layer in M7.
- `F-FAILED-SETTINGS`, `F-PUBLICATION-FAILURE`, `F-PREPARATION-CLEANUP-FAILURE`, and `F-RETIREMENT-FAILURE`.
- `F-SOURCE-CHANGE`: a contributing layer changed while the binding evaluates discards the attempt before publication (CONS-03).
- `F-MULTI-BINDING`: synchronizing at the default time code and at numeric ones, a non-integer included, is attempted at exactly that time code, as the last attempt records (BIND-05).
- `F-SCHEMA-VERSIONS`' unreadable and unsupported pending-cleanup records: cleanup and the other operations that interpret them refuse, report why, and dispose of nothing (SCHEMA-06).
- Abort preparation, then fail disposal: assert the old generation is unchanged, prepared leftovers are inactive and persistently tracked, save/reopen preserves them without retrying cleanup (REOPEN-01), and explicit cleanup retry succeeds without USD access.
- Undo: delete stub-created managed content, undo, and verify the M3 indexes are consistent again.
- Undo step count: one per published synchronization, none for a failed one, none doubled when an operator calls the API.

**Exit condition:** using the stub application layer, a failure at any boundary before publication leaves the entire published generation unchanged, failed preparation disposal leaves only inactive tracked retryable work, and a retirement failure after publication leaves the new generation active with leftovers tracked.
