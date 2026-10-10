# M13 — Incremental change discovery and dependency invalidation

**Implements:** change discovery, invalidation, and [Affected Content](../spec/incremental.md#affected-content) in [Incremental Synchronization](../spec/incremental.md).

**Depends on:** M10 (shared-content dependency tracking), M11 (lifecycle and repair behavior), M12 (Phase 1 baselines).

**Decisions and deliverables:**

- Phase 2 performance target values and churn budgets for replacement-affected resources.
- A change matrix enumerating the change cases in Incremental Synchronization.
- A mapping from source-affected entities to dependency-affected and replacement-affected display resources.
- A decision on when local updates, partition rebuilds, or explicit full rebuilds are appropriate.
- Discovery of managed display damage, distinguished from legitimate external users.
- If M1b adopts Hydra: scene-index observer notices as one discovery source, within the limits in the [incremental design note](../spec/incremental.md#change-discovery).

**Tests:**

- Affected-resource sets for every change-matrix case, including changes that cross batching or shared-content boundaries.
- Old and new dependencies when structure or relationships change.
- Missed or coalesced change notifications.
- `F-TEXTURE-IN-PLACE` and `F-SAME-VALUES`.

**Exit condition:** correct affected-resource sets for every case in the change matrix, within the churn budgets.
