# `proscenium`

The extension's source directory: what `tools/build_extension.py` zips into the extension Blender installs. It holds the extension's manifest and registration, and six packages: what callers use, the synchronization transaction, the display component of interaction, the temporary UI, the bindings' code, and the compiled core. The widgets the temporary UI hosts are the `proscenium_ui` package's ([its README](../../packages/proscenium_ui/src/proscenium_ui/README.md)), which the extension depends on and its zip bundles as a wheel. The bindings' code and the core are kept apart, so either can change without the other.

| Path | Holds |
|---|---|
| `blender_manifest.toml` | The extension manifest. Its `[build]` patterns keep the C++ sources, CMake files, and these READMEs out of the zip; only the built core module ships. |
| `__init__.py` | The package, with `register` and `unregister`. It imports without `bpy`, and imports `addon` only when Blender registers the extension. |
| `addon.py` | Registration: the record namespace's property group, the handlers for file load, undo, and redo that drop or prune the bindings' stages, and the frame-change handler and message-bus subscriptions to what windows show that mirror a scene's source selection again. |
| `api/` | What callers use: the binding handle and the process's bindings. |
| `synchronization/` | The synchronization transaction and the application layer it applies plans with. |
| `interaction/` | The display component of the interaction contract: a binding's correspondence from Blender data, and Blender's selection. |
| `interface/` | The temporary UI, which M12 replaces: the Source Select tool and minimal panels, over `api/` and `proscenium_ui`'s widgets only. |
| `binding/` | The bindings' code: their runtime state, records, source access, and results. |
| `core/` | The compiled core: its C++ source and the built module. |

## Import rules

The code is in units, each a package or a single module, in tiers. A unit imports only from itself and from units in lower tiers; the lowest tier's units import only themselves, and never `bpy` ([tiers](../../docs/plans/source-tiers-and-names.md#tiers)). A unit above the lowest tier may also import `proscenium_ui`'s units, since the extension depends on that package; `proscenium_ui` imports nothing of the extension's ([plan](../../docs/plans/workspace-packages.md#import-rules)):

| Tier | Units |
|---|---|
| 7 | `addon.py` |
| 6 | `interface/` |
| 5 | `api/` |
| 4 | `synchronization/`, `interaction/` |
| 3 | `binding/runtime/` |
| 2 | `binding/persistence/` |
| 1 | `core/`, `binding/source_access/`, `binding/results.py` |

`__init__.py`, the extension's entry, and `binding/__init__.py`, which groups its package's units and imports none of them, are no unit's.

Units reach each other through public modules and exported names. A package unit's `__init__.py` exports its public modules and names, its own or its modules', and nothing else; a module unit is public itself. Code in another unit imports a public module from its package and names each use through it: `from ..binding.persistence import manifests`, then `manifests.Manifest`, and `from ..binding import results`, then `results.Result`. Where a module's qualified uses would nest, as in `results.Result(results.Diagnostic(results.DiagnosticCode.X, ...))`, it imports the names from the public module instead: `from ..binding.results import Diagnostic, DiagnosticCode, Result`. A package that exports names is used the same way: imported from its parent, each use named through it (`from .. import synchronization`, then `synchronization.synchronize`), or its names imported from it. Nothing imports a name a package doesn't export, or anything from a module its package doesn't export. A unit's own modules import each other directly, and tests reach into any module.

Module names are unique across `src/proscenium/` and the packages in `packages/`, and name what the module holds, so a use names its unit and doesn't repeat itself: `binding_records.BindingConfig`, `binding_settings.PayloadPolicy`.

`tests/bpy_free/test_import_tiers.py` checks these rules, and `proscenium_ui`'s, by reading each module's imports, and fails on any import of a Blender module in each package's bpy-free tiers and the packages holding them, or of a package its package doesn't depend on; `tests/bpy_free/test_no_blender_imports.py` checks that they import in a fresh interpreter with Blender's modules blocked.
