# `proscenium_sync`

The synchronizer: the [bindings](../../../../docs/PROJECT.md#glossary)' records, runtime state, source access, and results; the synchronization transaction; the display component of interaction; the API callers use; and the planner. The bindings' code is kept apart from the planner, so the Blender-facing code and the planner and its Hydra code change independently. Callers use its own names, `bindings/`' exports and `registration.py`'s `register` and `unregister`: `proscenium_sync.BINDINGS`, `proscenium_sync.register()`.

| Path | Holds |
|---|---|
| `__init__.py` | The package and its public API. It imports none of its units, so importing a bpy-free unit, which runs it first, never imports `bpy`: a module `__getattr__` loads the API's units on first use of a name, and finds the name in their `__all__` lists. A unit's name, which a from-import tries as an attribute first, and a dunder load nothing. |
| `__init__.pyi` | The public API as type checkers and editors see it: a star import of each API unit, so each unit's `__all__` is the one list of its names. |
| `registration.py` | The synchronizer's registration: the record namespace's property group, the handlers for file load, undo, and redo that drop or prune the bindings' stages, and the frame-change handler and message-bus subscriptions to what windows show that mirror a scene's source selection again. |
| `bindings/` | What callers use: the binding handle and the process's bindings. |
| `synchronization/` | The synchronization transaction and the application layer it applies plans with. |
| `interaction/` | The display component of the interaction contract: a binding's correspondence from Blender data, and Blender's selection. |
| `runtime/` | Lookups and writes on `persistence/`'s records, read when called, and every binding's stages. |
| `persistence/` | Versioned records in Blender ID properties. |
| `source_access/` | The stages a binding reads its source from, and the binding identifiers, canonical-candidate rule, requested settings, and source-entity identifiers they're found and made by. |
| `results/` | What operations on a binding report: `Result`, whose state derives from its aggregated diagnostics (`result_state`, `deduplicated_diagnostics`) and never from its cleanup status, `DiagnosticCollector`, which gathers an operation's diagnostics as its steps run, `ResultState`, `Diagnostic`, `DiagnosticCode`, the list of stable codes, each with one `DiagnosticCategory` and `Severity`, ([Diagnostics](../../../../docs/spec/pipeline.md#diagnostics)). The binding-state records store diagnostics too. |
| `planner/` | The planner: its C++ source and the built module. |

## Import rules

The workspace's [import rules](../../../README.md#import-rules) hold here, as [this package's `pyproject.toml`](../../pyproject.toml)'s contracts state them. Other packages reach it only through its public API, its own names, and import none of its units.

`__init__.py`, which imports none of its units, is no unit's. `tests/bpy_free/test_sync_api.py` checks that its API units are those `__init__.pyi` imports, and `tests/blender/test_sync_api.py` that it loads their names.
