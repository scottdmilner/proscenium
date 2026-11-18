# `proscenium_sync`

The synchronizer: the [bindings](../../../../docs/PROJECT.md#glossary)' records, runtime state, source access, and results; the synchronization transaction; the display component of interaction; the API callers use; and the planner. The bindings' code is kept apart from the planner, so the Blender-facing code and the planner and its Hydra code change independently. The extension registers it through `registration.py` and reaches it through `bindings/`.

| Path | Holds |
|---|---|
| `__init__.py` | The package. It imports none of its units, so importing a bpy-free unit, which runs it first, never imports `bpy`. |
| `registration.py` | The synchronizer's registration: the record namespace's property group, the handlers for file load, undo, and redo that drop or prune the bindings' stages, and the frame-change handler and message-bus subscriptions to what windows show that mirror a scene's source selection again. |
| `bindings/` | What callers use: the binding handle and the process's bindings. |
| `synchronization/` | The synchronization transaction and the application layer it applies plans with. |
| `interaction/` | The display component of the interaction contract: a binding's correspondence from Blender data, and Blender's selection. |
| `runtime/` | Lookups and writes on `persistence/`'s records, read when called, and every binding's stages. |
| `persistence/` | Versioned records in Blender ID properties. |
| `source_access/` | The stages a binding reads its source from, and the binding identifiers, canonical-candidate rule, requested settings, and source-entity identifiers they're found and made by. The lowest tier. |
| `results/` | What operations on a binding report: `Result`, whose state derives from its aggregated diagnostics (`result_state`, `deduplicated_diagnostics`) and never from its cleanup status, `DiagnosticCollector`, which gathers an operation's diagnostics as its steps run, `ResultState`, `Diagnostic`, `DiagnosticCode`, the list of stable codes, each with one `DiagnosticCategory` and `Severity`, ([Diagnostics](../../../../docs/spec/pipeline.md#diagnostics)). The binding-state records store diagnostics too. The lowest tier. |
| `planner/` | The planner: its C++ source and the built module. The lowest tier. |

## Import rules

The workspace's [import rules](../../../README.md#import-rules) hold here, with this package's tiers, which [this package's `pyproject.toml`](../../pyproject.toml)'s "proscenium_sync's tiers" contract lists from `registration.py` down. It imports no other package of the workspace, and other packages reach it only through its public API, `bindings/` and `registration.py`. The lowest tier, `planner/`, `source_access/`, and `results/`, never imports `bpy`, and its units import only themselves. Of the units that export names, not all their modules, `bindings/`, `synchronization/`, `results/`, and `planner/` are reached only through their `__init__.py`.

`__init__.py`, which imports none of its units, is no unit's.
