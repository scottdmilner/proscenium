# `proscenium.core.source_access`

The stages a binding reads its source from ([Source Access](../../../../docs/spec/source-access.md)). Part of `proscenium.core`, so it imports without `bpy`. Nothing here is saved in the `.blend`. Undo retains attachments and drops evaluation stages of vanished bindings. A binding's records keep the configuration these stages are made from (`proscenium.persistence.binding_records`). The compiled core receives a stage from here, and never opens one.

| File | Holds |
|---|---|
| `__init__.py` | The package's exports. |
| `binding_stages.py` | `BindingStages` holds the source key, attached stage, and reused evaluation stage. It owns attachment, replacement, release, evaluation under the binding's payload policy, and explicit reloading. Also `PayloadPolicy`, `SourceUnavailableError`, `contributing_layers`, and `dirty_layers`. |
| `stage_registry.py` | `StageRegistry`: every binding's stages by binding identifier, made from its source key on first use and released by source key. Pruning compares with the set of existing binding identities and drops evaluation stages of vanished bindings while keeping their attachments for undo and redo. |

How a binding's stages behave is in [Source Stages](../../../../docs/spec/source-access.md#source-stages) and [Layer State and Reloading](../../../../docs/spec/source-access.md#layer-state-and-reloading); the decisions behind them are DECISIONS.md's rows "One kind of binding" and "Evaluation-stage reuse".
