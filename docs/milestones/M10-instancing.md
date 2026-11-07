# M10 — Complete native instancing

**Implements:** [Native Instancing](../spec/support/instancing.md).

**Depends on:** M4 (prototypes and partitioning scheme), M8 (meshes), M9 (materials).

**Scope limits:** works within the M4 partitioning scheme.

**Decisions and deliverables:**

- Evaluation/planning: complete instancing, shared contents, instance context, and per-instance variation in the snapshot and plan, replacing M6's provisional descriptions. Since M1b adopted Hydra, verify that Hydra's native-instance aggregation, which regroups instances by inherited state, is compatible with M4's sharing criteria, and map Hydra instancers and instance indices back to instance context.
- Application: shared and per-instance display behavior, and instance-root selection.
- From M1b's bridge ([M1b plan](../plans/M01b-evaluation-gate.md#phase-c-log); the bridge's `instancing` and `batch_groups` in [its sources](../../tools/feasibility/hydra_bridge/src/README.md)):
  - Hydra splits instances into separate instancers by differing flattened material bindings, purpose, draw mode, assetInfo, skel binding, or set of constant-primvar names, so one USD prototype's copies can come from several Hydra prototypes. Instances differing only in primvar values share an instancer ([M1b plan](../plans/M01b-evaluation-gate.md#data-the-chain-exposes-and-where-it-differs-from-direct-usd)).
  - Hydra's instance aggregation keeps only an array primvar's first element and takes names and types from the first instance (`[7, 8]` reached copies as `[7]`), so per-instance primvars come from each instance root's own record. M10 files the upstream issue, so the workaround is labeled with it and gets a known-gap check.
  - `HdxPrimOriginInfo` is quadratic in the instance count in v26.03 and fixed in OpenUSD `dev` (5bc38c9); point-instancer identity, which it handles, would come with a switch to it once Blender's USD has the fix, after rerunning the bridge's agreement and linearity checks ([M1b plan](../plans/M01b-evaluation-gate.md#phase-b-log)).
  - Point instancers in the bridge ([M4 plan](../plans/M04-prototypes.md), D6): each point's frame is its scale, then rotation, then translation, then the instancer's world transform; the mask folds in `invisibleIds`; each per-point primvar becomes the copy's primvar, as an instance root's does; Hydra copies each prototype as `ForInstancer<hash>` with the prototype root's transform included; and no gprim under a point instancer gets an object except as its prototypes' copies (ALab has 239 untargeted ones). Not covered: nesting, `ids`, velocities, and time-sampled points.
  - A stronger layer can't deactivate prims inside native-instance prototypes, since opinions on instance proxies are ignored ([M1b plan](../plans/M01b-evaluation-gate.md#phase-e-log)).
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
