# `proscenium.synchronization`

The synchronization transaction ([Synchronization Transaction](../../../docs/spec/pipeline.md#synchronization-transaction)): one attempt to display a binding's source, from acquisition through retirement, and the application layer it applies display plans with. `proscenium.api` calls it. It may import `proscenium.binding.runtime`, `proscenium.binding.persistence`, and the bpy-free code (`proscenium.core`, `proscenium.binding.source_access`, `proscenium.binding.results`), using what each package exports. M5's application layer is a stub, which M7 replaces.

| File | Holds |
|---|---|
| `__init__.py` | The package's exports: `synchronize`. |
| `application.py` | M5's stub application layer, which M7 replaces: `prepare` makes each of a plan's placeholders, an object drawing its bounds and its bounds mesh, in prepared work's staging collection, which no scene links, keyed by the published entries whose identities they have, and tracks each as it's made. Preparation only creates datablocks, so it changes nothing the published generation reaches (TXN-05). The transaction doesn't call it until publication lands (M5 plan, D6). |
| `prepared_work.py` | `PreparedWork`, what a preparation has made, which the stub and M7's application layer share: `track` records each resource in the pending-cleanup ledger before anything else can fail (TXN-08), and `dispose` removes it all, resolving each entry and leaving each removal that fails retryable, with its cleanup diagnostic. |
| `transaction.py` | `synchronize`, the transaction's steps for a binding the caller has found usable. So far it refuses a binding whose manifest can't be read, a manifest naming an unknown role included, and acquires the evaluation stage. |
