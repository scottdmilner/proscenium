# M6 — Snapshot evaluation and representation planning

**Implements:** [Evaluated Source Snapshot](../spec/pipeline.md#evaluated-source-snapshot), [Display Plan](../spec/pipeline.md#display-plan), [Transforms and Time Codes](../spec/support/transforms.md#transforms-and-time-codes), except time-varying topology (M8); the planning side of [Coordinate Conversion](../spec/support/transforms.md#coordinate-conversion) (M7 covers the application side); [Visibility and Purpose](../spec/support/visibility.md#visibility-and-purpose), and [Models and Unsupported Content](../spec/support/visibility.md#models-and-unsupported-content), except exposing model kind and asset metadata (M7).

**Depends on:** M3 (identifier schemes), M5 (layer interfaces and diagnostics).

**Scope limits:**

- Initial scope is hierarchy, transforms, bounds, and placeholders. Native instances, shared contents, and instance-context identities are identified here, but their descriptions are provisional. Meshes come in M8, materials in M9, and complete instancing in M10.
- The snapshot and the plan may be implemented in the same milestone, but remain distinct outputs.

**Decisions and deliverables:**

- Extensions to the M5 plan envelope that carry evaluated content, with provisional instance and geometry descriptions labeled as such. Each read of one of the plan's tuple properties converts every element ([M5 plan](../plans/M05-architecture.md), F3), so large content crosses as read-only buffers, as the core's boundary rules say, and a consumer reads a tuple once per plan.
- Capture and planning replace M5's minimal path in `synchronization/evaluation.py`, which the transaction and `cache` share inside `changed_layers()`, so a layer changed during either discards the attempt (CONS-03). The minimal path's capture took 0.71 to 0.84 s of a synchronization on ALab ([M5 plan](../plans/M05-architecture.md), F3).
- Objects created so their names land at the end of Blender's sorted ID lists, whatever names users see: prim-derived names cost 6.68 s against 1.06 s in creation order at 30,001 objects ([M4 plan](../plans/M04-prototypes.md), C3). This applies to batches' objects too.
- Batch groups in the plan: copies alike but for placement, at least 5 to a group (DECISIONS.md "Display representation"), grouped in the core ([M4 plan](../plans/M04-prototypes.md), D8).
- What depends on time, from Hydra's dirtying, for `cache` to add: each object's dirtied aspects after the capture dirties its time dependencies, which predicted every varying copy on ALab ([M4 plan](../plans/M04-prototypes.md), E3). A suggestion; the frames confirm what varies.
- Snapshot capture from the scene-index chain (M1b adopted Hydra), following the [Hydra design note](../spec/pipeline.md#evaluated-source-snapshot). Imaging adapters and filters replace much custom display-semantic evaluation; source inspection and project validation remain.

**Tests:**

- Snapshot and plan assertions for the initial scope, including sharing, correspondence, and diagnostics.
- Transforms on `F-TRANSFORMS` and `F-NESTED-STRESS`, and unsupported content and its descendants on `F-UNSUPPORTED-CONTENT`.
- Time-code and settings changes, including the USD default time code and coordinate conversion with different supplied unit scales and up-axis settings (`F-UNITS-UP-AXIS`).
- Visibility and purpose for both destinations from one snapshot on `F-VISIBILITY-PURPOSE` and `F-NESTED-STRESS`, and a guide made explicitly visible on `F-UNIVERSE-MEMBERSHIP`.
- Determinism: identical snapshot, settings, and planning context yield identical plans.
- Each binding's own conversion and purpose settings on `F-MULTI-BINDING`: setting one binding's leaves the others' (BIND-06). M6 adds them to binding configuration version 1, with no migration, since no release has written one (DECISIONS.md "Conversion and purpose settings").
- Per-behavior dispatch: an unsupported behavior on a prim does not suppress its supported behaviors.
- Expected transforms, visibility, and bounds come from the spec or from how the fixture is built (for example, UsdGeom computations), never from Hydra's own output. An untranslated Hydra prim type yields a placeholder and diagnostic.

**Exit condition:** a supported initial snapshot can be evaluated and planned deterministically, yielding an inspectable source hierarchy and a spatially meaningful plan, with no Blender objects or datablocks created.
