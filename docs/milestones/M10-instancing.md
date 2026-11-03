# M10 — Complete native instancing

**Implements:** [Native Instancing](../spec/support/instancing.md).

**Depends on:** M4 (prototypes and partitioning scheme), M8 (meshes), M9 (materials).

**Scope limits:** works within the M4 partitioning scheme.

**Decisions and deliverables:**

- Evaluation/planning: complete instancing, shared contents, instance context, and per-instance variation in the snapshot and plan, replacing M6's provisional descriptions. Since M1b adopted Hydra, verify that Hydra's native-instance aggregation, which regroups instances by inherited state, is compatible with M4's sharing criteria, and map Hydra instancers and instance indices back to instance context.
- Application: shared and per-instance display behavior, and instance-root selection.
- Dependency tracking between shared contents and their displayed uses.
- From M4 ([M4 plan](../plans/M04-prototypes.md), F2, F5): point instancers at scale can't be planned a record per instance (Moana Island's ~31 million at about 13 KB a planned copy), so their batches would come from an instancer's arrays; a point instance's identity, deferred until then, has its instancer as its floor. A point instance's time-sampled `protoIndices` can change its prototype, and its materials with it, which cached time codes display (CACHE-10).

**Tests:**

- Per-instance material variation, including per-instance `displayColor` and named primvars driving material inputs.
- Nested combinations, not just isolated instancing features: `F-NESTED-STRESS`.
- Instance-root selection floors through the M4 interaction checks: `F-NESTED-SELECTION`.
- Sharing assertions against M4's criteria: equivalent uses share geometry, required distinct geometry and appearance data remains correct, and equivalent variants remain deduplicated. Attribute/render assertions verify per-instance appearance, not mesh counts alone.
- Multiple bindings and shared-content changes.
- Benchmarks of representative scenes.

**Exit condition:** complete instancing behavior within the M4 partitioning scheme, passing `F-NESTED-STRESS`, with shared-content dependency tracking that M13 can use for invalidation.
