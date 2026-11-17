# `proscenium_sync`

The synchronizer: the [bindings](../../../../docs/PROJECT.md#glossary)' records, runtime state, source access, and results; the synchronization transaction; the display component of interaction; the API callers use; and the planner. The bindings' code is kept apart from the planner, so the Blender-facing code and the planner and its Hydra code change independently. The extension registers it through `registration.py` and reaches it through `api/`.

| Path | Holds |
|---|---|
| `__init__.py` | The package. It imports none of its units, so importing a bpy-free unit, which runs it first, never imports `bpy`. |
| `registration.py` | The synchronizer's registration: the record namespace's property group, the handlers for file load, undo, and redo that drop or prune the bindings' stages, and the frame-change handler and message-bus subscriptions to what windows show that mirror a scene's source selection again. |
| `api/` | What callers use: the binding handle and the process's bindings. |
| `synchronization/` | The synchronization transaction and the application layer it applies plans with. |
| `interaction/` | The display component of the interaction contract: a binding's correspondence from Blender data, and Blender's selection. |
| `binding_runtime/` | Lookups and writes on `binding_persistence/`'s records, read when called, and every binding's stages. |
| `binding_persistence/` | Versioned records in Blender ID properties. |
| `source_access/` | The stages a binding reads its source from, and the binding identifiers, canonical-candidate rule, requested settings, and source-entity identifiers they're found and made by. The lowest tier. |
| `results.py` | What operations on a binding report: `Result`, whose state derives from its aggregated diagnostics (`result_state`, `deduplicated_diagnostics`) and never from its cleanup status, `DiagnosticCollector`, which gathers an operation's diagnostics as its steps run, `ResultState`, `Diagnostic`, `DiagnosticCode`, the list of stable codes, each with one `DiagnosticCategory` and `Severity`, ([Diagnostics](../../../../docs/spec/pipeline.md#diagnostics)). The binding-state records store diagnostics too. The lowest tier. |
| `planner/` | The planner: its C++ source and the built module. The lowest tier. |

## Import rules

The workspace's [import rules](../../../README.md#import-rules) hold here, with this package's tiers. It imports no other package of the workspace. The lowest tier never imports `bpy`, and its units import only themselves:

| Tier | Units |
|---|---|
| 6 | `registration.py` |
| 5 | `api/` |
| 4 | `synchronization/`, `interaction/` |
| 3 | `binding_runtime/` |
| 2 | `binding_persistence/` |
| 1 | `planner/`, `source_access/`, `results.py` |

`__init__.py`, which imports none of its units, is no unit's.
