# `proscenium.core.source_access`

The stages a binding reads its source from ([Source Access](../../../../docs/spec/source-access.md)). Part of `proscenium.core`, so it imports without `bpy`. It's runtime state: nothing here is saved in the `.blend`, and undo neither restores nor removes it. A binding's records keep the configuration these stages are made from (`proscenium.persistence.binding_records`). The compiled core receives a stage from here, and never opens one.

| File | Holds |
|---|---|
| `__init__.py` | The package's exports. |
| `sources.py` | A binding's source: a `FileSource`, a root-layer file whose source stage the binding opens itself outside every stage cache, or an `AttachedSource`, a stage a caller attaches under a source key and the binding holds until released. Also `SourceKind`, `PayloadPolicy`, and `SourceUnavailableError`. |
| `binding_stages.py` | A binding's stages: `FileBindingStages`, whose evaluation stage is its source stage, and `AttachedBindingStages`, whose evaluation stage composes the attached stage's root and session layers. Both acquire the evaluation stage under a payload policy, matched to the source stage, and reload layers on request. Also `contributing_layers` and `dirty_layers`. |
| `stage_registry.py` | `StageRegistry`: every binding's stages by binding identifier, made from its configuration on first use, released by source key, and compared with the bindings that exist (`prune`): a file binding's stages go with its binding, and an attached binding keeps its attachment, as undo leaves attachments. |

How a binding's stages behave is in [Source Stages](../../../../docs/spec/source-access.md#source-stages) and [Layer State and Reloading](../../../../docs/spec/source-access.md#layer-state-and-reloading); the decisions behind them are DECISIONS.md's rows "One kind of binding" and "Strictness of the file-backed refresh contract".
