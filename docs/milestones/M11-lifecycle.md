# M11 — Ownership reconciliation, detach, and lifecycle operations

**Implements:** [Ownership and Lifecycle](../spec/lifecycle.md#ownership-and-lifecycle), including [Detach As-Is](../spec/lifecycle.md#detach-as-is) and [Lifecycle Failure Safety](../spec/lifecycle.md#lifecycle-failure-safety), except stale-content retirement and external-usage protection (M7); [Copied Bindings](../spec/source-access.md#copied-bindings) repair, and the lifecycle undo/redo requirements in [Undo and Runtime State](../spec/lifecycle.md#undo-and-runtime-state).

**Depends on:** M5 (representation roles and pending-cleanup tracking), M7 (incremental reconciliation), M10 (complete instancing and sharing).

**Scope limits:** none beyond the spec sections it implements.

**Decisions and deliverables:**

- The Cleanup, Detach, and Remove binding operations, as specified in Ownership and Lifecycle. Detach releases surviving content as-is and removes binding-specific metadata and controls without requiring baking or reconstruction.
- Cleanup builds on M5's `retry_cleanup` and its shared removal (`synchronization/datablock_removal.py`), which reads users once, removes a level at a time, users first, releases intact what anything else uses, and halves a failing `batch_remove` call to find what fails. The ledger holds only removals that failed, a ledger write that fails raises as a defect, and a retry that commits pushes one undo step ([M5 plan](../plans/M05-architecture.md), S2 to S4, D12, F2).
- Remove binding's call is delivered ahead of M11 by the [Stage Output bindings plan](../plans/stage-output-bindings.md): `handle.remove()` and `Bindings.remove_binding`, which run alone, push one undo step when they commit, and refuse while a record they would remove or the ledger can't be read. It removes the managed content through `datablock_removal.remove_unused`, the binding's leftovers in the ledger included, and then the destination, or only the binding's records on it when unmanaged content is linked into it. A disposal that fails stays in the ledger with a `removal-failed` diagnostic, and the configuration is removed anyway, so the removal completes with issues. The temporary UI's binding panel has a Remove button that calls it. M11 keeps the rest of Remove binding: the decision record below on retaining unresolved ownership information, cleanup that reaches the ledger entries of a binding that no longer exists, fault injection at each commit point, and `F-LIFECYCLE-FAILURE`.
- A lifecycle failure-safety decision record and implementation: staging/rollback, logical commit points, resumable disposal, outcome reporting, and retention of unresolved ownership information during binding removal. Evaluate retaining configuration until cleanup completes and retaining cleanup information independently after removal, using M5's chosen tracking mechanism.
- Duplicate-representation detection and removal, and handling of content with copied or missing ownership evidence, as specified in Ownership and Lifecycle.
- User-facing repair of bindings disabled pending repair: make a new binding, or detach.
- Discovery of managed display damage, distinguished from legitimate external users (DISC-05), and its repair in the damaged partitions alone, on M7's incremental framework.
  - Repair starts from M3's report of copied bindings (`Bindings.copied()`): each identity that isn't unique, its candidates by scene and destination, and which one is canonical, if any ([M3 plan](../plans/M03-bindings.md), D10).
  - A repair that moves a binding to another collection moves its records and its index entry with it; otherwise the old collection remains a copy ([Copied Bindings](../spec/source-access.md#copied-bindings)).
  - Cleanup reaches the pending work of a binding removed with its destination or target scene, which stays in the ledger ([Removed Destination](../spec/lifecycle.md#removed-destination), DEST-10).
  - Detection runs at every lookup, so a binding record or index changed by a script is found by the next call. Lifecycle operations that act on copies look for them first, as synchronization does.
- Undo/redo of every lifecycle operation.
- From M7 ([M7 plan](../plans/M07-application.md), G7), a noted cost: removing objects costs about 60 ns for each removed object and each other object in the file, whatever API removes them ([record](../feasibility/runtime-record.md#removing-objects-beside-others-m7-phase-g)). Retirement removes the old display beside its replacement, so a full rebuild, and every synchronization without a held plan (after reopening, or an undo past the held plans), took 98 s at 30,001 objects, 3.7 s on ALab; cleanup and binding removal share the same removal (`datablock_removal.remove_unused`). Suggested, not probed: when a partition with a published counterpart of the same identity is prepared again without a held plan, reuse the published object, giving it the new state and retiring only its replaced data, while a requested full rebuild keeps building fresh objects to recover from damage; or remove obsolete objects from a timer after the call returns, which moves the cost but doesn't lower it. Removing a mesh before its objects crashed Blender once; the removal removes users first.

**Tests:**

- The M3 index rebuilding stays correct after detach, cleanup, and removal, including their undo/redo.
- `F-OWNERSHIP-AMBIGUITY`, `F-DETACH-SHARED`, `F-DETACH-AS-IS`, `F-LIFECYCLE-FAILURE`, and `F-UNDO-AFTER-DAMAGE`, and `F-UNMANAGED-USER`'s binding removal.
- `F-BINDING-STATE`: after a binding is removed, every method of a handle to it raises (API-08).
- Detach with edited or deleted content, an unavailable USD source, shared instances, and binding-specific controls. Assert preservation of surviving ordinary Blender data, removal of binding associations, resolution of this binding's pending disposal tracking, and safe later refresh.
- Failure injection during incremental mutation and disposal of its newly prepared resources, including persistent cleanup tracking and safe retry.
- Inject failures before detach commit and during cleanup and removal. Assert the specified outcome, consistent ownership and correspondence, retained retry information after save/reopen, and undo/redo of committed partial progress.

**Exit condition:** cleanup, detach, and binding removal pass `F-OWNERSHIP-AMBIGUITY`, `F-DETACH-SHARED`, `F-DETACH-AS-IS`, `F-LIFECYCLE-FAILURE`, and `F-UNDO-AFTER-DAMAGE` with the specified failure outcomes and correct undo/redo, even when Blender objects do not correspond individually to USD prims.
