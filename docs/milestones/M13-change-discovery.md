# M13 — Incremental change discovery and dependency invalidation

**Implements:** change discovery, invalidation, and [Affected Content](../spec/incremental.md#affected-content) in [Incremental Synchronization](../spec/incremental.md).

**Depends on:** M10 (shared-content dependency tracking), M11 (lifecycle and repair behavior), M12 (Phase 1 baselines).

**Decisions and deliverables:**

- Phase 2 performance target values and churn budgets for replacement-affected resources.
- A change matrix enumerating the change cases in Incremental Synchronization.
- A mapping from source-affected entities to dependency-affected and replacement-affected display resources.
- A decision on when local updates, partition rebuilds, or explicit full rebuilds are appropriate.
- Discovery of managed display damage, distinguished from legitimate external users.
- Scene-index observer notices (M1b adopted Hydra) as one discovery source, within the limits in the [incremental design note](../spec/incremental.md#change-discovery).
- What the bridge built and measured, as starting points to confirm (the bridge's `capture`, `scene_index_graph`, and source-info filter in [its sources](../../tools/feasibility/hydra_bridge/src/README.md)):
  - Incremental capture ([M1b plan](../plans/M01b-evaluation-gate.md#phase-c-log)): re-copy only the prims notices named since the previous capture (added and dirtied exactly, removed and renamed by subtree), sharing the others' retained containers, which never change, so earlier snapshots stay intact. On 23 edit steps it equaled full captures record by record, on one scene; that isn't proof notices are complete. `HdsiComputeSceneIndexDiffDelta` compares handles, not values, so its oracle is a full re-read.
  - The bridge's chain ends in `HdsiPrimTypeNoticeBatchingSceneIndex`, which the core's chain doesn't have: the scene is empty until its first `Flush()`, notices wait for each one, and capture flushes every time. One priority for every prim type suits re-reading; materials first might suit applying notices, untested ([M1b plan](../plans/M01b-evaluation-gate.md#phase-b-log)).
  - `SetTime` dirties exactly the locators flagged time-varying, and only on data sources already pulled; flags are never cleared, so dirties also arrive for removed paths and unchanged values ([M1b plan](../plans/M01b-evaluation-gate.md#change-tracking-and-time)). Hydra never flags mesh orientation, scheme, doubleSided, subdivision tags, or subset indices (M8).
  - The source-info filter rebuilds more than needed on a time change: 16 containers on the bridge's animation scene, where an ad hoc build that invalidated only for extents rebuilt 3 ([M1b plan](../plans/M01b-evaluation-gate.md#phase-d-log)).
  - Native-instance indices are positions in sorted `SdfPathSet` order, so adding or removing an instance shifts them and re-dirties every member's `instance` locator ([M1b research](../plans/M01b-research/02-usdimaging-chain.md), §5).
  - Mesh build reuse ([M4 plan](../plans/M04-prototypes.md), D9): a mesh prim's build is reused when its captured container and its subsets' are the ones it was built from, so Hydra's invalidation decides what is rebuilt. On ALab with its point instancers a batched transform update took 0.250 s against 0.493 s. What it leaves on every update is reading every prim's record and planning every object; reusing those needs a prim table that shares records with the previous plan's and dependency tracking for what an object takes from other prims (its frame, instance context, and materials).

**Tests:**

- Affected-resource sets for every change-matrix case, including changes that cross batching or shared-content boundaries.
- Old and new dependencies when structure or relationships change.
- Missed or coalesced change notifications.
- `F-TEXTURE-IN-PLACE` and `F-SAME-VALUES`.

**Exit condition:** correct affected-resource sets for every case in the change matrix, within the churn budgets.
