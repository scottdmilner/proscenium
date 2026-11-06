# M7 — Blender application and source inspection UI

**Implements:** [Blender Application](../spec/pipeline.md#blender-application), the inspection and interaction behavior in [Source Inspection and Interaction](../spec/interaction.md#source-inspection-and-interaction), except correspondence through batching (M8) and instance-root selection (M10), the application side of [Coordinate Conversion](../spec/support/transforms.md#coordinate-conversion), display-correspondence persistence in [Persistence](../spec/lifecycle.md#persistence), stale-content retirement and external-usage protection in [Ownership and Lifecycle](../spec/lifecycle.md#ownership-and-lifecycle), and the display of cached time codes in [Cached Time Codes](../spec/pipeline.md#cached-time-codes) and [Transforms and Time Codes](../spec/support/transforms.md#transforms-and-time-codes), as M4's decision represents them (row "Time-sampled data representation"), except time-varying topology (M8).

**Depends on:** M4 (partitioning decision and finalized interaction contract), M5 (application-layer interface, transaction, and stub tests), M6 (display plans).

**Scope limits:** repair of user-modified content is M11 work.

**Decisions and deliverables:**

- The real application layer for the chosen representation, connected to M5's ownership tracking, transaction, and publishing.
- Partition-level replacement from the start, following the M4 partitioning decision, even though Phase 1 rebuilds everything.
- Basic reconciliation: each synchronization builds a fresh set of partitions, publishes it, and retires the previous result, deleting only obsolete resources that are safe to remove under the ownership and external-usage rules.
- The source inspector, and the agreed browsing, selection, and highlighting behavior from the finalized interaction contract.
- A binding panel that lists a scene's bindings once per draw, measured against M4's interaction budgets: a listing reads every collection's binding records, 13 µs with one binding (DECISIONS.md "Binding records read when called").
- From M4's selection tool ([M4 plan](../plans/M04-prototypes.md), F2, F3): whatever owns the destination's display, not a selection tool, decides when managed content is selectable (the destination collection's `hide_select`, 44 ms on ALab against 0.95 s per object) and which overlays the 3D views hide, as later tools may need it selectable; the active tool's changes come from message-bus subscriptions to `WorkSpace.tools` and `Window.workspace`. A file saved while Source Select is active keeps those settings, so loading restores or ignores them. Blender's own outlines stay the default; outlines of the extension's own would need a C-level draw engine to reuse Blender's GPU geometry and dim what is hidden. A box selects elements by their world bounds' centers, since many copies hold their placement in their points.
- Cached time codes for every variation (CACHE-10), with mechanisms suggested and not probed ([M4 plan](../plans/M04-prototypes.md), F5): a copy's materials chosen by a keyed index (a Geometry Nodes Set Material fed by an Index Switch), or an object per material state with keyed visibility; a placeholder's bounds box and empty marker both made, each with keyed visibility; and a property keyed, where its primvar is blocked, with its reader's fallback (M9). A batch has an object per selection state its instances hold (D14).
- The inspection layer of the [interaction contract](../spec/interaction-contract.md#two-layers-and-the-live-stage): a C++ library that maps picked prims to selection targets by kind on the live stage, independent of the compiled core and of Blender, which the core calls and exposes through its bindings. It reads the live stage M3 defines for each binding.

**Tests:**

- Resulting Blender content and source correspondence for hand-constructed plans.
- Repeated application: several unchanged synchronizations follow [Resource Stability](../spec/lifecycle.md#resource-stability), with stable active counts, stable total managed counts when disposal succeeds, separately tracked leftovers during disposal failure, and count recovery after explicit cleanup.
- The M5 failure-injection tests, rerun unchanged against the real application layer.
- Application-time resource failures abort the transaction unless the plan authorized a fallback.
- `F-UNMANAGED-USER`.
- `F-OFFLINE`: correspondence records unchanged through reopening with the source unavailable (REOPEN-07).
- The M4 interaction checks against the real display: `F-KIND-HIERARCHY`, `F-NESTED-SELECTION`, `F-UNIVERSE-MEMBERSHIP`.
- End-to-end tests using M6-generated plans.
- Cached time codes: synchronized at one sampled time code and cached at the others in more than one order, each frame displays what a clean synchronization at its time code does, whether they were cached in one call or several, and a frame between them the latest before it, with interaction answering for that time code; the display caches nothing on its own (CACHE-01, CACHE-08, CACHE-09, CACHE-10, XFORM-11, XFORM-13, XFORM-14).

**Exit condition:** the application layer displays and inspects plans, passes the M5 failure-injection suite and `F-UNMANAGED-USER`, and meets the boundary rule in Blender Application.
