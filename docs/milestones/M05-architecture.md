# M5 — Synchronization architecture, diagnostics, and failure safety

**Implements:** the interfaces and boundary rules in [Synchronization Layer Boundaries](../spec/pipeline.md#synchronization-layer-boundaries) (M6 and M7 implement the layers themselves), [Diagnostics](../spec/pipeline.md#diagnostics), [Synchronization Transaction](../spec/pipeline.md#synchronization-transaction) for full rebuilds (M14 covers incremental mutation), the synchronization undo policy in [Undo and Runtime State](../spec/lifecycle.md#undo-and-runtime-state), and publication of the [Binding State](../spec/lifecycle.md#binding-state) model.

**Depends on:** M3 (ownership metadata, binding-state schemas, and index rules), M4 (partitioning decision).

**Decisions and deliverables:**

- Interfaces between evaluation, representation planning, and application, including the planning context.
- Display-resource identifiers and representation roles, based on the M4 partitioning decision.
- A minimal display-plan envelope covering partitions, ownership entries, correspondence entries, and placeholder content.
- Schema/behavior dispatch and dependency resolution.
- The transaction implementation: the commit point, what publication switches, how prepared work is discarded, and the copy-on-write or rollback discipline that keeps published resources unchanged during preparation.
- Recording of the Binding State model during synchronization.
- Retirement with pending-cleanup diagnostics for resources that could not be removed.
- A decision and implementation for persistent cleanup tracking: evaluate a separate ledger and pending-cleanup state in existing ownership records, then record the chosen mechanism. Cover newly prepared and obsolete resources, failed pre-publication disposal, and safe explicit retry, preserving reused published resources.
- A stub application layer that consumes the plan envelope and creates trivial placeholder content, so failure safety can be tested before M7 exists.
- Ownership-aware resource accounting.
- A measurement of the synchronization undo step's memory cost.

**Tests:**

- Failure-injection tests at each transaction boundary, run against the stub application layer and rerun unchanged against the real application layer in M7.
- `F-FAILED-SETTINGS`, `F-PUBLICATION-FAILURE`, `F-PREPARATION-CLEANUP-FAILURE`, and `F-RETIREMENT-FAILURE`.
- Abort preparation, then fail disposal: assert the old generation is unchanged, prepared leftovers are inactive and persistently tracked, save/reopen preserves them, and explicit cleanup retry succeeds without USD access.
- Undo: delete stub-created managed content, undo, and verify the M3 indexes are consistent again.
- Undo step count: one per published synchronization, none for a failed one, none doubled when an operator calls the API.

**Exit condition:** using the stub application layer, a failure at any boundary before publication leaves the entire published generation unchanged, failed preparation disposal leaves only inactive tracked retryable work, and a retirement failure after publication leaves the new generation active with leftovers tracked.
