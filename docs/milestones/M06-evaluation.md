# M6 — Snapshot evaluation and representation planning

**Implements:** [Evaluated Source Snapshot](../spec/pipeline.md#evaluated-source-snapshot), [Display Plan](../spec/pipeline.md#display-plan), [Transforms and Time Codes](../spec/support/transforms.md#transforms-and-time-codes), except time-varying topology (M8); the planning side of [Coordinate Conversion](../spec/support/transforms.md#coordinate-conversion) (M7 covers the application side); [Visibility and Purpose](../spec/support/visibility.md#visibility-and-purpose), and [Models and Unsupported Content](../spec/support/visibility.md#models-and-unsupported-content).

**Depends on:** M3 (identifier schemes), M5 (layer interfaces and diagnostics).

**Scope limits:**

- Initial scope is hierarchy, transforms, bounds, and placeholders. Native instances, shared contents, and instance-context identities are identified here, but their descriptions are provisional. Meshes come in M8, materials in M9, and complete instancing in M10.
- The snapshot and the plan may be implemented in the same milestone, but remain distinct outputs.

**Decisions and deliverables:**

- Extensions to the M5 plan envelope that carry evaluated content, with provisional instance and geometry descriptions labeled as such.
- If M1b adopts Hydra: snapshot capture from the scene-index chain, following the [Hydra design note](../spec/pipeline.md#evaluated-source-snapshot). Imaging adapters and filters replace much custom display-semantic evaluation; source inspection and project validation remain.

**Tests:**

- Snapshot and plan assertions for the initial scope, including sharing, correspondence, and diagnostics.
- Time-code and settings changes, including the USD default time code and coordinate conversion with different supplied unit scales and up-axis settings.
- Determinism: identical snapshot, settings, and planning context yield identical plans.
- Per-behavior dispatch: an unsupported behavior on a prim does not suppress its supported behaviors.
- With Hydra: expected transforms, visibility, and bounds come from the spec or from how the fixture is built (for example, UsdGeom computations), never from Hydra's own output. An untranslated Hydra prim type yields a placeholder and diagnostic.

**Exit condition:** a supported initial snapshot can be evaluated and planned deterministically, yielding an inspectable source hierarchy and a spatially meaningful plan, with no Blender objects or datablocks created.
