# `proscenium.binding.runtime`

The bindings' in-memory state: a disposable write-through cache of their records, and the runtime indexes into it ([Undo and Runtime State](../../../../docs/spec/lifecycle.md#undo-and-runtime-state)). Tier 3: it may import `proscenium.binding.persistence` and the lowest tier (`proscenium.core`, `proscenium.binding.source_access`, `proscenium.binding.results`).

Code in other units reaches it through the modules `__init__.py` exports ([import rules](../../README.md#import-rules)); tests reach into any module.

| File | Holds |
|---|---|
| `__init__.py` | The package's exports: its modules. |
| `state.py` | The state itself. It holds the records, decoded, each once and held as stored, by the datablock holding them: each scene's `SceneRecords` (its binding records), each destination collection's `DestinationRecords` (its tag, and its manifest once read), and each Text's `IndexRecords` (its binding index, and its pending-cleanup ledger once read). It also holds what's computed from them: each identity's candidates and decision, and the ownership index. Also tracking (`start_tracking`, `stop_tracking`), dropping and rebuilding (`invalidate`, `rebuild_count`, `refresh_if_tags_changed`), and the checks of held datablock references. |
| `binding_configs.py` | Lookups by binding identity (`find_binding`, `find_bindings`), which reach the canonical candidate's binding record and return a `FoundBinding`: usable with its configuration, unreadable with why, or disabled with its copies; binding creation; configuration writes; and restoring a missing index entry after a write. |
| `ownership_index.py` | Ownership: `ownership(datablock)`, an `Ownership` whose `status` says whether the datablock is unmanaged, managed, or ambiguous, from the `Claim`s on it in the ownership index, built from every destination's manifest. Also a binding's manifest, and manifest writes and removal, each replacing only its destination's claims. |
| `pending_cleanup.py` | The pending-cleanup ledger (`ledger`), held with the index Text's records once read and reread when a datablock it names was removed, its writes by entry (`set_ledger_entries`), whether it can record work (`check_trackable`), and a binding's current cleanup diagnostics, which every result reports as its cleanup status (`cleanup_status`), and whether a binding has none of its entries (`nothing_pending`). A file with more than one binding index refuses the ledger and its writes, and reports an empty status. |
| `stage_tracking.py` | `CurrentStages`: every binding's stages, in source access's `StageRegistry`, compared with the set of existing binding identities before any use once the bindings' state was rebuilt (`rebuild_count`). Vanished bindings keep their attachments and drop their evaluation stages; unreadable and disabled bindings retain both. |
| `copy_detection.py` | Copied-binding detection ([Copied Bindings](../../../../docs/spec/source-access.md#copied-bindings)): `identities()`, which finds each identity's `Candidate`s in the state's records and returns them (`IdentityCandidates`) with the decision of the rule in `proscenium.binding.source_access.canonical_candidate`; and `report()`'s `CopiedBinding`. |

## How the state stays current

- **Writes go through it**, writing the stored record and holding what the write stored, since the records are what's saved and what undo steps capture. A write that changes what the canonical-candidate rule reads decides that identity again.
- **Blender changes the records behind it** only by a file load, undo, or redo. The handlers in `addon.py` drop the state before and after each, and the next use rebuilds it from the records, so the state needs the extension registered (`NotRegisteredError`).
- **Changes no handler announces** are caught where they're used: a change of scenes rebuilds the state at its next use, a removed datablock is found when a lookup checks it, and a collection duplicated on its own is found when a synchronization first compares the tagged collections (`refresh_if_tags_changed`).
- **Only datablock references are held,** each checked before it's returned, never the structs inside a datablock, which Blender can free under a held reference.
