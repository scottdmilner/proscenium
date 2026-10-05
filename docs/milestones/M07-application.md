# M7 — Blender application and source inspection UI

**Implements:** [Blender Application](../spec/pipeline.md#blender-application), the inspection and interaction behavior in [Source Inspection and Interaction](../spec/interaction.md#source-inspection-and-interaction), except correspondence through batching (M8) and instance-root selection (M10), the application side of [Coordinate Conversion](../spec/support/transforms.md#coordinate-conversion), display-correspondence persistence in [Persistence](../spec/lifecycle.md#persistence), and stale-content retirement and external-usage protection in [Ownership and Lifecycle](../spec/lifecycle.md#ownership-and-lifecycle).

**Depends on:** M4 (partitioning decision and finalized interaction contract), M5 (application-layer interface, transaction, and stub tests), M6 (display plans).

**Scope limits:** repair of user-modified content is M11 work.

**Decisions and deliverables:**

- The real application layer for the chosen representation, connected to M5's ownership tracking, transaction, and publishing.
- Partition-level replacement from the start, following the M4 partitioning decision, even though Phase 1 rebuilds everything.
- Basic reconciliation: each synchronization builds a fresh set of partitions, publishes it, and retires the previous result, deleting only obsolete resources that are safe to remove under the ownership and external-usage rules.
- The source inspector, and the agreed browsing, selection, highlighting, and framing behavior from the finalized interaction contract.

**Tests:**

- Resulting Blender content and source correspondence for hand-constructed plans.
- Repeated application: several unchanged synchronizations follow [Resource Stability](../spec/lifecycle.md#resource-stability), with stable active counts, stable total managed counts when disposal succeeds, separately tracked leftovers during disposal failure, and count recovery after explicit cleanup.
- The M5 failure-injection tests, rerun unchanged against the real application layer.
- Application-time resource failures abort the transaction unless the plan authorized a fallback.
- `F-UNMANAGED-USER`.
- End-to-end tests using M6-generated plans.

**Exit condition:** the application layer displays and inspects plans, passes the M5 failure-injection suite and `F-UNMANAGED-USER`, and meets the boundary rule in Blender Application.
