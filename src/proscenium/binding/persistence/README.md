# `proscenium.binding.persistence`

Everything the extension saves in the `.blend`: versioned records in Blender ID properties ([Persistence](../../../../docs/spec/lifecycle.md#persistence)). The bottom tier of the Blender-facing code: it may import only the bpy-free code below the tiers (`proscenium.core`, `proscenium.binding.source_access`, `proscenium.binding.results`).

| File | Holds | Records, and where they are |
|---|---|---|
| `__init__.py` | What code outside this package uses: the records `proscenium.binding.runtime`, `proscenium.api`, and `proscenium.addon` read and write, the functions that read and write them, and `NAMESPACE`, the records' ID-property group. Code outside the package reaches the modules below only through it (checked by `tests/bpy_free/test_import_tiers.py`), apart from `manifests.py`; tests reach into them. It imports `binding_records.py`, which needs `bpy`, so the package and every module in it import only with Blender; their tests are in `tests/blender/`. | |
| `records.py` | The versioned-record framework: `Schema`, loading with migration, `Loaded` and `RefusedRecord`, and reading and writing records. | |
| `binding_records.py` | `BindingConfig`, `DestinationTag`, and `BindingIndex`, with binding creation (`create_binding`), restoring an index entry (`restore_index_entry`), and the reads that find every binding's records. | A binding's configuration on its target scene, the tag on its destination collection, and the binding index on its own Text. |
| `manifests.py` | Ownership metadata: `Manifest` and `ManifestEntry`, which only the ownership index (`proscenium.binding.runtime.ownership_index`) uses until M5 synchronizes, so it imports this module itself, and the state holds them for it; they join the package's exports when M5 calls ownership. They're written whole (`write_manifest`) or by entry (`write_manifest_entries`) ([Ownership and Lifecycle](../../../../docs/spec/lifecycle.md#ownership-and-lifecycle)). | A binding's manifest on its destination collection. |
| `binding_state.py` | `Generation`, what the published display was produced with, and `LastAttempt`, the most recent synchronization attempt ([Binding State](../../../../docs/spec/lifecycle.md#binding-state)). | The generation on the destination collection, beside the manifest; the last attempt on the target scene. |
| `selection.py` | `PersistentSelection` and its `SelectionEntry`s ([Persistent Selection](../../../../docs/spec/interaction-contract.md#persistent-selection)). | On the scene. |

## How records work

- **Where they are:** each ID that carries records holds them in one ID-property group, `id_["proscenium"]`, one record per key. `addon.py` registers that group's name as a property group, so Blender's Custom Properties panel hides it, but the records are plain ID properties, readable with the extension disabled.
- **Versions:** every record stores its schema version, and every schema is at version 1. Reading migrates an older supported record in memory, and the next write stores it at the current version. Binding configuration stores the last attached root-layer identifier, destination, and settings.
- **Refusals:** a record that can't be read, being newer, damaged, or failed in migration, loads as a `RefusedRecord` value, never an exception, so its binding keeps its display and reports why. Writers read before writing and refuse on any refusal, and writing itself refuses to replace an unreadable or newer record ([Schema Versions](../../../../docs/spec/lifecycle.md#schema-versions)).
- **Pointers:** a record names datablocks by ID pointer, not by name. Blender clears a pointer when its datablock is removed, and a full-copy scene or an append rewrites the copies' pointers to each other, while `Collection.copy()` keeps them naming the originals ([copy routes](../../../../docs/feasibility/runtime-record.md#copy-routes-m3)).

The binding index is on a Text rather than a scene or collection, so no copy route copies it ([Canonical Candidate](../../../../docs/spec/source-access.md#canonical-candidate)). Pending-cleanup records are M5's.
