# M10 — Complete native instancing

**Implements:** [Native Instancing](../spec/support/instancing.md).

**Depends on:** M4 (prototypes and partitioning scheme), M8 (meshes), M9 (materials).

**Scope limits:** works within the M4 partitioning scheme.

**Decisions and deliverables:**

- Evaluation/planning: complete instancing, shared contents, instance context, and per-instance variation in the snapshot and plan, replacing M6's provisional descriptions.
- Application: shared and per-instance display behavior, and instance-root selection.
- Dependency tracking between shared contents and their displayed uses.

**Tests:**

- Per-instance material variation, including per-instance `displayColor` and named primvars driving material inputs.
- Nested combinations, not just isolated instancing features: `F-NESTED-STRESS`.
- Sharing assertions against M4's criteria: equivalent uses share geometry, required distinct geometry and appearance data remains correct, and equivalent variants remain deduplicated. Attribute/render assertions verify per-instance appearance, not mesh counts alone.
- Multiple bindings and shared-content changes.
- Benchmarks of representative scenes.

**Exit condition:** complete instancing behavior within the M4 partitioning scheme, passing `F-NESTED-STRESS`, with shared-content dependency tracking that M13 can use for invalidation.
