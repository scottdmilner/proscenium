# `proscenium.synchronization`

The synchronization transaction ([Synchronization Transaction](../../../docs/spec/pipeline.md#synchronization-transaction)): one attempt to display a binding's source, from acquisition through retirement, and the application layer it applies display plans with. `proscenium.api` calls it. It may import `proscenium.binding.runtime`, `proscenium.binding.persistence`, and the bpy-free code (`proscenium.core`, `proscenium.binding.source_access`, `proscenium.binding.results`), using what each package exports. M5's application layer is a stub, which M7 replaces.

| File | Holds |
|---|---|
| `__init__.py` | The package's exports: `synchronize`. |
| `transaction.py` | `synchronize`, the transaction's steps for a binding the caller has found usable. So far it refuses a binding whose manifest can't be read, a manifest naming an unknown role included, and acquires the evaluation stage. |
