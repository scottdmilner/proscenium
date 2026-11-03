# `proscenium.source_access`

The stages a binding reads its source from ([Source Access](../../../docs/spec/source-access.md)), and the identities and settings they're found and made by: binding identifiers, the canonical-candidate rule, requested settings, and source-entity identifiers. It sits below the Blender-facing tiers, which may import it, imports without `bpy`, and may import only itself; `tests/bpy_free` imports it with Blender's modules blocked. Runtime state that needs no `bpy`, such as the stage registry, belongs here, not in `proscenium.runtime`. Nothing here is saved in the `.blend`. Undo retains attachments and drops evaluation stages of vanished bindings. A binding's records keep the configuration these stages are made from (`proscenium.persistence.binding_records`). The compiled core receives a stage from here, and never opens one.

| File | Holds |
|---|---|
| `__init__.py` | The package's exports: the stages and their errors and helpers. The other modules are imported by name. |
| `binding_ids.py` | `BindingId`, a binding's persistent identifier: a `NewType` of `str`, so the checker tells it from other strings. Every tier uses it. |
| `canonical_candidate.py` | The canonical-candidate rule, as a pure function of what Blender data says about each candidate and each binding index ([Canonical Candidate](../../../docs/spec/source-access.md#canonical-candidate)). `proscenium.runtime.copy_detection` reads that evidence from the records. |
| `requested_settings.py` | `RequestedSettings`, the settings a binding's next synchronization uses ([Binding State](../../../docs/spec/lifecycle.md#binding-state)). The binding's configuration holds them. |
| `source_entities.py` | Source-entity identifiers: an entity's path in the composed stage, with the instance context its instance-proxy path carries. |
| `binding_stages.py` | `BindingStages` holds the attached stage and reused evaluation stage. It owns attachment, replacement, release, evaluation under the binding's payload policy, and explicit reloading. Also `PayloadPolicy`, `SourceUnavailableError`, `contributing_layers`, and `dirty_layers`. |
| `stage_registry.py` | `StageRegistry`: every binding's stages by binding identifier, made unattached on first use and released by binding identifier. Pruning compares with the set of existing binding identities and drops evaluation stages of vanished bindings while keeping their attachments for undo and redo. |

How a binding's stages behave is in [Source Stages](../../../docs/spec/source-access.md#source-stages) and [Layer State and Reloading](../../../docs/spec/source-access.md#layer-state-and-reloading); the decisions behind them are DECISIONS.md's rows "One kind of binding" and "Evaluation-stage reuse".
