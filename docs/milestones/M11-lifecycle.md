# M11 — Ownership reconciliation, detach, and lifecycle operations

**Implements:** [Ownership and Lifecycle](../spec/lifecycle.md#ownership-and-lifecycle), including [Detach As-Is](../spec/lifecycle.md#detach-as-is) and [Lifecycle Failure Safety](../spec/lifecycle.md#lifecycle-failure-safety), except stale-content retirement and external-usage protection (M7); [Copied Bindings](../spec/source-access.md#copied-bindings) repair, and the lifecycle undo/redo requirements in [Undo and Runtime State](../spec/lifecycle.md#undo-and-runtime-state).

**Depends on:** M5 (representation roles and pending-cleanup tracking), M7 (basic reconciliation), M10 (complete instancing and sharing).

**Scope limits:** optimized repair of individual partitions without a full rebuild is Phase 2 work (M13/M14). M11 repairs damage correctly through full refresh.

**Decisions and deliverables:**

- The Cleanup, Detach, and Remove binding operations, as specified in Ownership and Lifecycle. Detach releases surviving content as-is and removes binding-specific metadata and controls without requiring baking or reconstruction.
- A lifecycle failure-safety decision record and implementation: staging/rollback, logical commit points, resumable disposal, outcome reporting, and retention of unresolved ownership information during binding removal. Evaluate retaining configuration until cleanup completes and retaining cleanup information independently after removal, using M5's chosen tracking mechanism.
- Duplicate-representation detection and removal, and handling of content with copied or missing ownership evidence, as specified in Ownership and Lifecycle.
- User-facing repair of bindings disabled pending repair: make a new binding, or detach.
- Undo/redo of every lifecycle operation.

**Tests:**

- The M3 index rebuilding stays correct after detach, cleanup, and removal, including their undo/redo.
- `F-OWNERSHIP-AMBIGUITY`, `F-DETACH-SHARED`, `F-DETACH-AS-IS`, `F-LIFECYCLE-FAILURE`, and `F-UNDO-AFTER-DAMAGE`.
- Detach with edited or deleted content, an unavailable USD source, shared instances, and binding-specific controls. Assert preservation of surviving ordinary Blender data, removal of binding associations, resolution of this binding's pending disposal tracking, and safe later refresh.
- Inject failures before detach commit and during cleanup and removal. Assert the specified outcome, consistent ownership and correspondence, retained retry information after save/reopen, and undo/redo of committed partial progress.

**Exit condition:** cleanup, detach, and binding removal pass `F-OWNERSHIP-AMBIGUITY`, `F-DETACH-SHARED`, `F-DETACH-AS-IS`, `F-LIFECYCLE-FAILURE`, and `F-UNDO-AFTER-DAMAGE` with the specified failure outcomes and correct undo/redo, even when Blender objects do not correspond individually to USD prims.
