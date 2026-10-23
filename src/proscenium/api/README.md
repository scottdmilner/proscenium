# `proscenium.api`

What callers use to reach bindings ([Synchronization API](../../../docs/spec/source-access.md#synchronization-api)). The top tier: it may import `proscenium.runtime`, `proscenium.persistence`, and `proscenium.core`.

| File | Holds |
|---|---|
| `__init__.py` | The package. |
| `bindings.py` | `BindingHandle`, the immutable value of a binding's identifier that callers hold, and `Bindings`, the process's bindings, of which `BINDINGS` is the one instance. Also `RequestedSettings`, `AttachResult`, and `BindingNotFoundError`. |

## `bindings.py`

- **The handle** holds only the binding's identifier, never a datablock or cached state, so undo, redo, and file loads can't leave it stale. Its methods (`synchronize`, `set_settings`, `reload`, `requested_settings`, `live_stage`) delegate to the methods of `BINDINGS` keyed by that identifier, which tests call on a fresh `Bindings`.
- **Operations that span bindings** are `Bindings`' own: creating a file or attached binding, listing a scene's bindings (`in_scene`), reporting copied bindings (`copied`), and attaching or releasing a stage under a source key.
- **Results and refusals:** an operation returns a `Result` (`proscenium.core.results`) whose diagnostics say why it failed: an unavailable source, a configuration that can't be read, a removed destination, or a binding with copies and no canonical candidate. A query raises instead, and every call raises `BindingNotFoundError` for a binding that doesn't exist.
- **Runtime stages:** each binding's source and evaluation stages are in a `StageRegistry` (`proscenium.core.source_access`), made from its configuration on first use and compared with the bindings whenever the bindings' state was rebuilt (`prune_stages`). `addon.py` drops them all when a file is loaded (`drop_all_stages`).

M3 implements source acquisition only. M5 adds evaluation, planning, application, and publication behind `synchronize`.
