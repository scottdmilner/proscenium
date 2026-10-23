# `proscenium.runtime`

The bindings' in-memory state: a disposable write-through cache of their records, and the runtime indexes into it ([Undo and Runtime State](../../../docs/spec/lifecycle.md#undo-and-runtime-state)). The middle tier: it may import `proscenium.persistence` and `proscenium.core`, never `proscenium.api`.

Callers use what `__init__.py` exports, not the modules below it.

| File | Holds |
|---|---|
| `__init__.py` | The public lookups and writes, re-exported from the modules below. |
| `state.py` | The state itself: each binding's candidates, their configurations and manifests as read when first needed, and each identity's canonical-candidate decision. Also tracking (`start`, `stop`), dropping and rebuilding (`invalidate`, `rebuild_count`, `refresh_if_tags_changed`), and the checks of held datablock references. |
| `binding_configs.py` | Lookups by binding identity, which reach the canonical candidate; binding creation; configuration writes; and restoring a missing index entry after a write. |
| `ownership_index.py` | The ownership index, `Claim`s by datablock, built from every candidate's manifest; manifest lookups and writes, each replacing only its destination's claims. |
| `copy_detection.py` | Copied-binding detection ([Copied Bindings](../../../docs/spec/source-access.md#copied-bindings)): each identity's candidates read from the records, the decision of the rule in `proscenium.core.canonical_candidate`, and the `CopiedBinding` reports. |

## How the state stays current

- **Writes go through it**, updating memory and writing the records at once, since the records are what's saved and what undo steps capture.
- **Blender changes the records behind it** only by a file load, undo, or redo. The handlers in `addon.py` drop the state before and after each, and the next use rebuilds it from the records, so the state needs the extension registered (`NotRegisteredError`).
- **Changes no handler announces** are caught where they're used: a change of scenes rebuilds the state at its next use, a removed datablock is found when a lookup checks it, and a collection duplicated on its own is found when a synchronization first compares the tagged collections (`refresh_if_tags_changed`).
- **Only datablock references are held,** each checked before it's returned, never the structs inside a datablock, which Blender can free under a held reference.
