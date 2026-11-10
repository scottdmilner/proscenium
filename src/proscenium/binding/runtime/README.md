# `proscenium.binding.runtime`

The bindings' runtime: lookups and writes on their records, read when called, and every binding's stages ([Undo and Runtime State](../../../../docs/spec/lifecycle.md#undo-and-runtime-state), DECISIONS.md "Binding records read when called"). Tier 3: it may import `proscenium.binding.persistence` and the lowest tier (`proscenium.core`, `proscenium.binding.source_access`, `proscenium.binding.results`).

Code in other units reaches it through the modules `__init__.py` exports ([import rules](../../README.md#import-rules)); tests reach into any module.

| File | Holds |
|---|---|
| `__init__.py` | The package's exports: its modules. |
| `copy_detection.py` | Copied-binding detection ([Copied Bindings](../../../../docs/spec/source-access.md#copied-bindings)): `BindingRecord`, one collection's binding record as read; `identity()` and `identities()`, which read an identity's candidates, its binding records that can't be read or name a target scene that exists, and return them (`IdentityCandidates`) with the decision of the rule in `proscenium.binding.source_access.canonical_candidate`; and `report()`'s `CopiedBinding`. |
| `binding_configs.py` | Lookups by binding identity (`find_binding`, `find_bindings`), which reach the canonical candidate's binding record and return a `FoundBinding`, with its destination and target scene: usable with its configuration, unreadable with why, or disabled with its copies; binding creation; configuration writes; and restoring a missing index entry after a write. |
| `ownership.py` | Ownership: `of(datablock)`, an `Ownership` whose `status` says whether the datablock is unmanaged, managed, or ambiguous, from the `Claim`s on it in the manifests among its users (`bpy.data.user_map`). Also a binding's manifest (`manifest`), and manifest writes, whole (`set_manifest`) or by entry (`set_manifest_entries`, from the manifest its caller read, if given). |
| `pending_cleanup.py` | The pending-cleanup ledger (`ledger`), read from the index's Text, its writes by entry (`set_ledger_entries`), whether it can record a failed removal (`check_trackable`), and a binding's current cleanup diagnostics, which every result reports as its cleanup status (`cleanup_status`), and whether a binding has none of its entries (`nothing_pending`). A file with more than one binding index refuses the ledger and its writes, and reports an empty status. |
| `stage_tracking.py` | `BindingStageTracker`: every binding's stages, in source access's `StageRegistry`, compared with the bindings that exist before each use. Vanished bindings keep their attachments and drop their evaluation stages; unreadable and disabled bindings retain both. |

## Records read when called

- **Every lookup reads the records** as they are when it's called, and every write writes them; nothing is held between calls, so a file load, undo, redo, or removal needs nothing done, and no lookup can return a removed datablock: Blender clears a removed datablock's pointers in the records.
- **Only the stages are runtime state.** `addon.py`'s handlers drop them all when a file is loaded and prune them after undo and redo.
