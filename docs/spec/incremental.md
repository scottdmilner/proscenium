# Incremental Synchronization

Phase 1 requirements, but for the churn and performance budgets, which are Phase 2's. Phase goals are in [Delivery Phases](../PROJECT.md#delivery-phases); cross-cutting guarantees are summarized in [invariants.md](invariants.md).

## Change Discovery

Discover changes from:

- Manual refresh of an attached source, including after an explicit reload of its contributing layers.
- Edits to an attached stage.
- Evaluation time-code changes.
- Binding-setting changes.
- Managed display damage.

Handle changes to:

- Prim existence, activation, type, hierarchy, and variants.
- Transforms, geometry, topology, normals, and primvars.
- Visibility and purpose.
- Materials, networks, bindings, and dependencies, including external assets changed without any USD edit.
- Payload state.
- Instanced/non-instanced representation and shared contents.
- Evaluation time code and binding settings, including time changes that do not alter evaluated values.
- Target-scene unit scale and representation version.
- Managed Blender content requiring repair, distinguished from legitimate external users of managed resources.

Separate change discovery from dependency invalidation. Account for inherited/shared state, display partitions, and both old and new dependencies when structure or relationships change. Recover correctly from missed or coalesced change notifications.

Editor-provided change descriptions may be hints, but are not the sole correctness mechanism. Full traversal or snapshot comparison is acceptable for discovery if performance targets are met and unaffected Blender content is not unnecessarily rewritten.

Design note (settled by M7; see [DECISIONS.md](../DECISIONS.md) "Change discovery"): Hydra scene-index observer notices (added, removed, renamed, dirtied) on a binding's kept imaging pipeline, with the stage edits it listens for itself where Hydra doesn't dirty what it adds, name what a refresh re-reads. A dirty notice names data to re-read, not proof that its value changed, so the comparison rule below still decides writes. Notices do not cover external assets changed without USD edits, managed display damage, binding-setting or target-unit changes, display state restored by Blender undo, or differences after the imaging pipeline is rebuilt or lost. A change the pipeline misses leaves its own cached values stale, so re-reading from it can't recover one; a requested full rebuild rereads through a new pipeline ([Synchronization API](source-access.md#synchronization-api)). Under an opt-in verification mode, set by the `PROSCENIUM_VERIFY_CAPTURE` environment variable, each capture from a kept pipeline is also made through a new one, and where their plans differ, the new one's is used and the drawn copies that differ are reported as verification diagnostics ([Diagnostics](pipeline.md#diagnostics)).

## Affected Content

Distinguish three levels:

1. **Source-affected entities:** source state actually changed.
2. **Dependency-affected resources:** depend on changed state.
3. **Replacement-affected resources:** replaced only because they share an approved partition with affected content.

"Unaffected" means outside levels 1 and 2. Level 3 is permitted but bounded by churn and performance budgets, so partition choice cannot make the unaffected requirement meaningless. Untouched resources keep stable identities, and a no-op refresh performs no unnecessary Blender writes. A refresh after reopening a `.blend`, or after an undo or redo restores a generation the session no longer holds what it compares against (DECISIONS.md "Incremental refresh comparison"), may instead replace every display resource, with the result of a clean full rebuild. The [Change Matrix](change-matrix.md) lists what each change affects and what a refresh does about it.

> **Change discovery proposes work; comparing evaluated content decides whether a resource actually requires replacement or mutation.**

This allows conservative discovery without unnecessary Blender writes.
