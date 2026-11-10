# M10 — Complete native instancing

**Implements:** [Native Instancing](../spec/support/instancing.md).

**Depends on:** M4 (prototypes and partitioning scheme), M8 (meshes), M9 (materials).

**Scope limits:** works within the M4 partitioning scheme.

**Decisions and deliverables:**

- Evaluation/planning: complete instancing, shared contents, instance context, and per-instance variation in the snapshot and plan, replacing M6's provisional descriptions. Since M1b adopted Hydra, verify that Hydra's native-instance aggregation, which regroups instances by inherited state, is compatible with M4's sharing criteria, and map Hydra instancers and instance indices back to instance context.
- M6's provisional instance descriptions ([M6 plan](../plans/M06-evaluation.md), C1, C8, C11): a correspondence entry's `instance_context` lists the native-instance roots its source lies in, outermost first, with a point-instanced copy's instancer and point, and nothing else of an instance is planned, neither its shared contents nor its per-instance variation. A mesh's copies share a geometry description only within one Hydra prototype, which Hydra's aggregation splits by inherited state. Batch groups are keyed by the geometry description and the destinations; material slots (M9), and object color and constant primvars' attribute types (M10), join the key. On Pixar's Kitchen set every one of its 1,788 copies is in a native instance, under 425 instance contexts, with 7 groups at a minimum of 5, the largest 174 ([record](../feasibility/runtime-record.md#capture-and-planning-m6-phase-f)).
- M6's point instancers, planned a copy per point through the copy table: ALab's 8,141 point-instanced copies took planning from 0.022 s to 0.046 s, linear in the copies; a record per copy doesn't scale to Moana Island's point instancers, as M4 found (below).
- Application: shared and per-instance display behavior, and instance-root selection.
- From M1b's bridge ([M1b plan](../plans/M01b-evaluation-gate.md#phase-c-log); the bridge's `instancing` and `batch_groups` in [its sources](../../tools/feasibility/hydra_bridge/src/README.md)):
  - Hydra splits instances into separate instancers by differing flattened material bindings, purpose, draw mode, assetInfo, skel binding, or set of constant-primvar names, so one USD prototype's copies can come from several Hydra prototypes. Instances differing only in primvar values share an instancer ([M1b plan](../plans/M01b-evaluation-gate.md#data-the-chain-exposes-and-where-it-differs-from-direct-usd)).
  - Hydra's instance aggregation keeps only an array primvar's first element and takes names and types from the first instance (`[7, 8]` reached copies as `[7]`), so per-instance primvars come from each instance root's own record. M10 files the upstream issue, so the workaround is labeled with it and gets a known-gap check.
  - `HdxPrimOriginInfo` is quadratic in the instance count in v26.03 and fixed in OpenUSD `dev` (5bc38c9); it maps point-instanced copies too, to M6's point-instance paths, with a switch to it once Blender's USD has the fix, after rerunning the bridge's agreement and linearity checks ([M1b plan](../plans/M01b-evaluation-gate.md#phase-b-log)).
  - Point instancers (DECISIONS.md "Point instancers"): M6 ports the bridge's ([M4 plan](../plans/M04-prototypes.md), D6), copies and point-instance paths by index or authored id, inside native instances too. In the bridge, each point's frame is its scale, then rotation, then translation, then the instancer's world transform; the mask folds in `invisibleIds`; each per-point primvar becomes the copy's primvar, as an instance root's does, which M10 delivers (INST-09); Hydra copies each prototype as `ForInstancer<hash>` with the prototype root's transform included; and no gprim under a point instancer gets an object except as its prototypes' copies (ALab has 239 untargeted ones). M10 checks point instancers nested in point instancers and time-sampled points; velocities and accelerations stay deferred.
  - A stronger layer can't deactivate prims inside native-instance prototypes, since opinions on instance proxies are ignored ([M1b plan](../plans/M01b-evaluation-gate.md#phase-e-log)).
- Dependency tracking between shared contents and their displayed uses, which instancing's incremental refresh uses on M7's framework, including transitions between instanced and non-instanced representations. Native-instance indices are positions in sorted `SdfPathSet` order, so adding or removing an instance shifts them and re-dirties every member's `instance` locator ([M1b research](../plans/M01b-research/02-usdimaging-chain.md), §5).
- From M4 ([M4 plan](../plans/M04-prototypes.md), F2, F5): point instancers at scale can't be planned a record per instance (Moana Island's ~31 million at about 13 KB a planned copy), so their batches would come from an instancer's arrays, keeping M6's point-instance paths as the copies' identities. A point instance's time-sampled `protoIndices` can change its prototype, and its materials with it, which cached time codes display (CACHE-10).

**Tests:**

- Per-instance material variation, including per-instance `displayColor` and named primvars driving material inputs.
- Nested combinations, not just isolated instancing features: `F-NESTED-STRESS`.
- Per-point primvars on point instancers' copies: `F-POINT-INSTANCERS`.
- Instance-root selection floors through the M4 interaction checks: `F-NESTED-SELECTION`.
- Sharing assertions against M4's criteria: equivalent uses share geometry, required distinct geometry and appearance data remains correct, and equivalent variants remain deduplicated. Attribute/render assertions verify per-instance appearance, not mesh counts alone.
- Multiple bindings and shared-content changes, refreshed incrementally, including changes that cross batching or shared-content boundaries, each equal to a clean rebuild.
- Benchmarks of representative scenes.

**Exit condition:** complete instancing behavior within the M4 partitioning scheme, passing `F-NESTED-STRESS`, refreshing incrementally through shared-content dependency tracking.
