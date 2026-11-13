# `proscenium`

The extension's source directory: what `tools/build_extension.py` zips into the extension Blender installs. It holds the extension's manifest and registration, and five packages: what callers use, the synchronization transaction, the bindings' code, the compiled core, and the user interface. The bindings' code and the core are kept apart, so either can change without the other.

| Path | Holds |
|---|---|
| `blender_manifest.toml` | The extension manifest. Its `[build]` patterns keep the C++ sources, CMake files, and these READMEs out of the zip; only the built core module ships. |
| `__init__.py` | The package, with `register` and `unregister`. It imports without `bpy`, and imports `addon` only when Blender registers the extension. |
| `addon.py` | Registration: the record namespace's property group, and the handlers for file load, undo, and redo that drop or prune the bindings' stages. |
| `api/` | What callers use: the binding handle and the process's bindings. |
| `synchronization/` | The synchronization transaction and the application layer it applies plans with. |
| `binding/` | The bindings' code: their runtime state, records, source access, and results. |
| `core/` | The compiled core: its C++ source and the built module. |
| `ui/` | The user interface: widgets an add-on places in Blender's editors, such as the scene graph's prim tree, and what the widgets share. |

## Import rules

The code is in units, each a package or a single module, in tiers. A unit imports only from itself and from units in lower tiers; the lowest tier's units import only themselves. The two lowest tiers never import `bpy` ([tiers](../../docs/plans/source-tiers-and-names.md#tiers)):

| Tier | Units |
|---|---|
| 10 | `addon.py` |
| 9 | `ui/scene_graph_widget/display/` |
| 8 | `ui/search_box.py` |
| 7 | `ui/widget_resources/`, `ui/columned_list/`, `ui/widget_updates.py` |
| 6 | `api/` |
| 5 | `synchronization/` |
| 4 | `binding/runtime/` |
| 3 | `binding/persistence/` |
| 2 | `ui/scene_graph_widget/prim_tree/` |
| 1 | `core/`, `binding/source_access/`, `binding/results.py`, `ui/widget_model/` |

`__init__.py`, the extension's entry, and `binding/__init__.py`, `ui/__init__.py`, and `ui/scene_graph_widget/__init__.py`, which group their packages' units and import none of them, are no unit's.

Units reach each other through public modules and exported names. A package unit's `__init__.py` exports its public modules and names, its own or its modules', and nothing else; a module unit is public itself. Code in another unit imports a public module from its package and names each use through it: `from ..binding.persistence import manifests`, then `manifests.Manifest`, and `from ..binding import results`, then `results.Result`. Where a module's qualified uses would nest, as in `results.Result(results.Diagnostic(results.DiagnosticCode.X, ...))`, it imports the names from the public module instead: `from ..binding.results import Diagnostic, DiagnosticCode, Result`. A package that exports names is used the same way: imported from its parent, each use named through it (`from .. import synchronization`, then `synchronization.synchronize`), or its names imported from it. Nothing imports a name a package doesn't export, or anything from a module its package doesn't export. A unit's own modules import each other directly, and tests reach into any module.

Module names are unique across `src/proscenium/` and name what the module holds, so a use names its unit and doesn't repeat itself: `binding_records.BindingConfig`, `binding_settings.PayloadPolicy`.

`tests/bpy_free/test_import_tiers.py` checks these rules by reading each module's imports, and fails on any import of a Blender module in the two lowest tiers and the packages holding them; `tests/bpy_free/test_no_blender_imports.py` checks that they import in a fresh interpreter with Blender's modules blocked.
