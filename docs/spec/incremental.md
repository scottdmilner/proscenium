# Incremental Synchronization

Phase 2 requirements. Phase goals are in [Delivery Phases](../PROJECT.md#phase-2--incremental-synchronization); cross-cutting guarantees are summarized in [invariants.md](invariants.md).

## Change Discovery

Discover changes from:

- File-backed manual refresh.
- In-memory stage edits.
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

## Affected Content

Distinguish three levels:

1. **Source-affected entities:** source state actually changed.
2. **Dependency-affected resources:** depend on changed state.
3. **Replacement-affected resources:** replaced only because they share an approved partition with affected content.

"Unaffected" means outside levels 1 and 2. Level 3 is permitted but bounded by churn and performance budgets, so partition choice cannot make the unaffected requirement meaningless. Untouched resources keep stable identities, and a no-op refresh performs no unnecessary Blender writes.

> **Change discovery proposes work; comparing evaluated content decides whether a resource actually requires replacement or mutation.**

This allows conservative discovery without unnecessary Blender writes.
