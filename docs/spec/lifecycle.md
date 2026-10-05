# Lifecycle

Ownership, lifecycle operations, undo and runtime state, and persistence. Cross-cutting guarantees are summarized in [invariants.md](invariants.md).

## Ownership and Lifecycle

Generated content is USD-authoritative. Blender-side edits to managed content are not guaranteed to survive synchronization.

Keep these concepts separate in ownership records:

| Concept | Meaning |
|---|---|
| Resource identity | Which managed resource this is |
| Ownership | Which binding may replace or retire it |
| Source coverage | Which source entities it represents (possibly many) |
| Representation role | Why it exists |
| Usage and dependencies | Which other resources depend on it, managed or not |

A resource has one owning binding but may cover many source entities and have many users.

Use durable identifiers and ownership metadata, not Blender display names or object hierarchy. Keep binding identity, source identity, and display-resource identity distinct.

Required behavior:

- Renaming does not detach content.
- Deleting managed content does not delete its source; refresh restores required display content.
- Additional collection links do not detach managed content.
- Unrelated unmanaged content must not be modified or deleted.
- Refresh does not mutate a managed resource that unmanaged content uses. It creates a replacement, and the old resource is left intact and released from management.
- Content without sufficient ownership evidence is treated as unmanaged. Ambiguous candidates are reported, not automatically claimed or deleted.
- Successful refresh removes stale content and accidental duplicate canonical representations.
- Duplicates are defined by source coverage and representation role, not by assuming one Blender object per prim.
- Repeated unchanged refreshes keep active display resource counts and source/display diagnostics stable under [Resource Stability](#resource-stability).

Required lifecycle operations:

- **Cleanup:** remove duplicate or obsolete managed content and unused exclusively owned resources, and retry disposal of prepared or obsolete resources left pending by earlier synchronizations.
- **Detach:** release a whole binding's surviving managed content as-is into unmanaged Blender content, removing binding-specific metadata and controls under [Detach As-Is](#detach-as-is). Detaching individual source prims or subtrees is deferred. The binding configuration remains, its published generation is cleared, and its next refresh behaves like a first synchronization, creating new managed content alongside the detached result.
- **Remove binding:** remove configuration and managed content while preserving detached and unrelated content.

Lifecycle operations must preserve resources still required by other owners, and must remain correct even when Blender objects do not correspond individually to USD prims.

### Resource Stability

Count active display resources and inactive pending-cleanup resources separately. Repeated unchanged refreshes must not accumulate active resources or duplicate source/display diagnostics. When disposal succeeds, total managed-resource counts do not grow.

Disposal failures may retain additional resources only as inactive, persistently tracked pending cleanup with ownership evidence. Current cleanup diagnostics reflect unresolved work, are deduplicated by operation and resource, and may change as work is added or resolved. This exception permits neither untracked leftovers nor growth in the active display. Once the failures are removed, explicit cleanup retry must restore managed-resource counts to the clean baseline for the preserved or published generation and remove resolved tracking and cleanup diagnostics. Resources that must be released intact to protect detached or external users are accounted for separately; never delete them to satisfy a count.

### Detach As-Is

Detach operates on the surviving Blender content at the time of the operation, including Blender-side edits and existing damage. It does not access USD, restore deleted content, or reconstruct the last published appearance. It does not require baking or materializing instances, modifiers, or Geometry Nodes.

Remove the binding's ownership tags, source correspondence and selection associations, and binding-specific runtime controls, callbacks, and display helpers. Keep ordinary geometry, transforms, materials, collection links, and Blender dependencies that can function without those binding-specific mechanisms. Remove only metadata and controls belonging to this binding. Changes in appearance caused by removing binding-specific mechanisms are permitted and reported; restoring the synchronized appearance is not part of the contract.

Shared resources may remain shared. Resources still owned by another binding remain protected as resources used by unmanaged content under the ownership rules above. Later refresh or removal must not mutate or delete the detached result. Release this binding's surviving pending-cleanup resources intact as well, retaining their current inactive state and resolving their disposal tracking so a later retry cannot delete them.

### Lifecycle Failure Safety

Lifecycle operations do not access USD and report success, completed with issues, or failure, distinguishing committed changes from work still pending.

- **Detach:** release ownership, remove binding-specific controls and associations, and clear the published generation as one logical commit. A failure before that commit preserves the surviving content and binding state from the start of the operation. Diagnostic and preparation-cleanup bookkeeping may change. Report success only after the full binding has been detached; do not leave a partially detached result.
- **Cleanup:** completed disposals may remain committed if a later disposal fails. Preserve consistent ownership and active correspondence after each committed change, and retain unresolved work with ownership evidence and retry diagnostics. Report completed with issues when progress was committed, or failure when no progress was committed. A retry must safely resume after save/reopen without deleting detached or externally required resources.
- **Remove binding:** preserve detached and unrelated content. Remove configuration only when remaining disposal obligations are resolved or persistently recoverable without that configuration. Before any logical commit, a failure preserves the starting content and binding state apart from diagnostic and preparation-cleanup bookkeeping. If disposals or configuration removal have committed, report completed with issues on a later failure, recording exactly what remains and how to retry. Never report full success while disposal work remains unresolved.

M11 settles staging and rollback mechanisms, commit points, and how removal retains unresolved ownership information: keeping the configuration until cleanup completes, or retaining sufficient cleanup information independently after removal. The implementation must satisfy these outcomes with the pending-cleanup mechanism selected in M5; neither retention option requires a separate ledger.

Failure safety for synchronization is defined separately by the [Synchronization Transaction](pipeline.md#synchronization-transaction).

## Undo and Runtime State

All persistent state (see [Binding State](#binding-state)) lives in Blender data, so undo restores previously published display state and its metadata together. It does not undo external USD changes or guarantee that the restored display matches the current source.

- Each synchronization that publishes is exactly one undo step. Synchronizations invoked through the Python API push the step explicitly; an operator that calls the API does not push a second one.
- A failed synchronization pushes no undo step. It may update the last-attempt record and pending-cleanup tracking, but leaves binding configuration and the published generation unchanged.
- With global undo disabled or in background mode, synchronization behaves the same but pushes no step.
- When undo/redo restores an earlier display, mark the binding as possibly out of date relative to its source.
- In-memory stage attachments are runtime associations keyed by binding identity. Undo neither restores nor removes them; a binding that still exists after undo stays attached.
- Runtime code must not hold Blender datablock references across operator calls. This covers indexes, UI caches, callbacks, queued work, and retained plans. Runtime indexes are disposable caches keyed by persistent identifiers, rebuilt after file load, deletion, undo, and redo, and guarded by a generation counter so stale lookups fail loudly instead of returning dead references.

Detach, cleanup, and binding removal **must support undo/redo**, including consistent ownership, binding state, and pending-cleanup tracking. With global undo enabled outside background mode, each invocation that commits lifecycle changes adds exactly one undo step, including partial cleanup or removal reported as completed with issues. A failure before any logical commit adds no undo step. Undo/redo restores the actual pre-operation or committed state, including pre-existing Blender edits or damage; detach does not reconstruct a historical synchronized state.

## Persistence

### Binding State

Keep these distinct:

| State | Contents | Persisted |
|---|---|---|
| Binding configuration | Binding identity, source information, destination, target scene, and requested settings (time code, payload policy, conversion, purpose) | Yes |
| Published generation | Display resources, inspection snapshot, correspondence, ownership manifest, the settings and time code it was produced with, source revision information, its diagnostics, and persistent selection-resolution state | Yes |
| Last attempt | Settings attempted, result state, and diagnostics | Yes |
| Pending cleanup | Unresolved prepared or obsolete resources, ownership evidence, originating operation/binding identities, retry status, and cleanup diagnostics; logically distinct from the published generation and last attempt | Yes |
| Runtime source attachment | The caller's stage for an in-memory binding | No |
| Runtime indexes | Disposable caches keyed by persistent identifiers | No; rebuilt |

A binding can therefore report, for example: requested time 20 with load-none, displayed time 10 with load-all, last attempt failed. This applies equally to changed source paths, changed conversion settings, and undo restoring an older display.

Source information is the file path for file-backed bindings, or the reattachment information for in-memory bindings (see [Source Identity](source-access.md#source-identity)).

### Pending Cleanup

Persist sufficient ownership information to retry disposal of newly prepared or obsolete resources safely. Tracking survives save/reopen and later attempts without modifying the published generation; it does not rely on retained runtime datablock references. Retries revalidate ownership and current users, preserving active, reused, detached, ambiguously owned, and externally required resources. Resolve work by safe disposal or by releasing resources intact under the ownership protection rules. Remove resolved tracking and current cleanup diagnostics rather than accumulating history. Unresolved work remains inactive; retries are explicit and do not require USD access. Undo/redo restores cleanup tracking consistently with resource ownership.

**Design note:** two candidate mechanisms are a separate persistent cleanup ledger, or a pending-cleanup state in the existing ownership records. M3 defines the persistence contract; M5 chooses and validates the mechanism during transaction planning, refining the schemas as needed. Neither mechanism is required by this spec. M11 settles how unresolved tracking is retained during binding removal; removing configuration must not orphan pending work.

### Reopening

On reopening a `.blend`:

- Restore metadata, pending-cleanup tracking, and indexes. Do not automatically retry cleanup.
- Do not automatically synchronize. The extension does not access USD sources or external assets on its own initiative; Blender may still read image files referenced by translated materials.
- Refresh is explicit.
- An unavailable source must not erase the saved representation.
- Source unavailability must not automatically detach the binding.
- Detached content remains detached.

The saved display remains usable without its USD source: geometry, transforms, translated materials, inspection, and correspondence persist in the `.blend`. Image textures remain references to external files, so texture appearance requires those files to be reachable. Packing assets into the `.blend` is not guaranteed in Phases 1 or 2.

Serialization of arbitrary unsaved in-memory USD edits is not guaranteed in Phases 1 or 2.

### Schema Versions

Binding records, ownership manifests, inspection snapshots, correspondence, and any separate pending-cleanup records carry schema versions.

- Older supported schemas migrate on load.
- If migration fails or the schema is newer than the extension supports, preserve the display, disable refresh and lifecycle operations for that binding, and report why.
- Unreadable or unsupported pending-cleanup records are preserved and never authorize disposal. Disable operations that require interpreting those records and report why.
- Without the extension installed, the saved display remains ordinary Blender content.
