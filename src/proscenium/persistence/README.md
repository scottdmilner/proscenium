# `proscenium.persistence`

Everything the extension saves in the `.blend`: versioned records in Blender ID properties ([Persistence](../../../docs/spec/lifecycle.md#persistence)). The bottom tier of the Blender-facing code: it may import `proscenium.core` only.

| File | Holds | Records, and where they are |
|---|---|---|
| `__init__.py` | The package. | |
| `records.py` | The versioned-record framework: `Schema`, loading with migration, `Loaded` and `RefusedRecord`, and reading and writing records. | |
| `binding_records.py` | `BindingConfig`, `DestinationTag`, and `BindingIndex`, with binding creation and the reads that find every binding's records. | A binding's configuration on its target scene, the tag on its destination collection, and the binding index on its own Text. |
| `manifests.py` | Ownership metadata: `Manifest` and `ManifestEntry`, written whole or by entry ([Ownership and Lifecycle](../../../docs/spec/lifecycle.md#ownership-and-lifecycle)). | A binding's manifest on its destination collection. |
| `binding_state.py` | `Generation`, what the published display was produced with, and `LastAttempt`, the most recent synchronization attempt ([Binding State](../../../docs/spec/lifecycle.md#binding-state)). | The generation on the destination collection, beside the manifest; the last attempt on the target scene. |
| `selection.py` | `PersistentSelection` and its `SelectionEntry`s ([Persistent Selection](../../../docs/spec/interaction-contract.md#persistent-selection)). | On the scene. |

## How records work

- **Where they are:** each ID that carries records holds them in one ID-property group, `id_["proscenium"]`, one record per key. `addon.py` registers that group's name as a property group, so Blender's Custom Properties panel hides it, but the records are plain ID properties, readable with the extension disabled.
- **Versions:** every record stores its schema version, and every schema is at version 1. Reading migrates an older record in memory, and the next write stores it at the current version.
- **Refusals:** a record that can't be read, being newer, damaged, or failed in migration, loads as a `RefusedRecord` value, never an exception, so its binding keeps its display and reports why. Writers read before writing and refuse on any refusal, and writing itself refuses to replace an unreadable or newer record ([Schema Versions](../../../docs/spec/lifecycle.md#schema-versions)).
- **Pointers:** a record names datablocks by ID pointer, not by name. Blender clears a pointer when its datablock is removed, and a full-copy scene or an append rewrites the copies' pointers to each other, while `Collection.copy()` keeps them naming the originals ([copy routes](../../../docs/feasibility/runtime-record.md#copy-routes-m3)).

The binding index is on a Text rather than a scene or collection, so no copy route copies it ([Canonical Candidate](../../../docs/spec/source-access.md#canonical-candidate)). Pending-cleanup records are M5's.
