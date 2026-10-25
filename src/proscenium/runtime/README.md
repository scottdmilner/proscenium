# `proscenium.runtime`

The bindings' in-memory state: a disposable write-through cache of their records, and the runtime indexes into it ([Undo and Runtime State](../../../docs/spec/lifecycle.md#undo-and-runtime-state)). The middle tier: it may import `proscenium.persistence` and `proscenium.core`, never `proscenium.api`.

Callers use what `__init__.py` exports, not the modules below it (checked by `tests/bpy_free/test_import_tiers.py`).

| File | Holds |
|---|---|
| `__init__.py` | The public lookups and writes, re-exported from the modules below. |
| `state.py` | The state itself. It holds the records, decoded, each once and held as stored, by the datablock holding them: each scene's `SceneRecords` (its binding records), each destination collection's `DestinationRecords` (its tag, and its manifest once read), and each Text's `IndexRecords` (its binding index). It also holds what's computed from them: each identity's candidates and decision, and the ownership index. Also tracking (`start`, `stop`), dropping and rebuilding (`invalidate`, `rebuild_count`, `refresh_if_tags_changed`), and the checks of held datablock references. |
| `binding_configs.py` | Lookups by binding identity (`find_binding`, `find_bindings`), which reach the canonical candidate's binding record and return a `FoundBinding` whose `status` says whether it's usable, unreadable, or disabled; binding creation; configuration writes; and restoring a missing index entry after a write. |
| `ownership_index.py` | Ownership: `ownership(datablock)`, an `Ownership` whose `status` says whether the datablock is unmanaged, managed, or ambiguous, from the `Claim`s on it in the ownership index, built from every destination's manifest. Also a binding's manifest, and manifest writes, each replacing only its destination's claims. |
| `current_stages.py` | `CurrentStages`: every binding's stages, in core's `StageRegistry`, compared with the bindings before any use once the bindings' state was rebuilt (`rebuild_count`). |
| `copy_detection.py` | Copied-binding detection ([Copied Bindings](../../../docs/spec/source-access.md#copied-bindings)): `identities()`, which finds each identity's `Candidate`s in the state's records and returns them (`IdentityCandidates`) with the decision of the rule in `proscenium.core.canonical_candidate`; and `report()`'s `CopiedBinding`. |

## How the state stays current

- **Writes go through it**, writing the stored record and holding what the write stored, since the records are what's saved and what undo steps capture. A write that changes what the canonical-candidate rule reads decides that identity again.
- **Blender changes the records behind it** only by a file load, undo, or redo. The handlers in `addon.py` drop the state before and after each, and the next use rebuilds it from the records, so the state needs the extension registered (`NotRegisteredError`).
- **Changes no handler announces** are caught where they're used: a change of scenes rebuilds the state at its next use, a removed datablock is found when a lookup checks it, and a collection duplicated on its own is found when a synchronization first compares the tagged collections (`refresh_if_tags_changed`).
- **Only datablock references are held,** each checked before it's returned, never the structs inside a datablock, which Blender can free under a held reference.
