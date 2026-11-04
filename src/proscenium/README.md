# `proscenium`

The extension's source directory: what `tools/build_extension.py` zips into the extension Blender installs. It holds the extension's manifest and registration, and three packages: what callers use, the bindings' code, and the compiled core. The bindings' code and the core are kept apart, so either can change without the other.

| Path | Holds |
|---|---|
| `blender_manifest.toml` | The extension manifest. Its `[build]` patterns keep the C++ sources, CMake files, and these READMEs out of the zip; only the built core module ships. |
| `__init__.py` | The package, with `register` and `unregister`. It imports without `bpy`, and imports `addon` only when Blender registers the extension. |
| `addon.py` | Registration: the record namespace's property group, and the handlers for file load, undo, and redo that keep the bindings' in-memory state current. |
| `api/` | What callers use: the binding handle and the process's bindings. |
| `binding/` | The bindings' code: their runtime state, records, source access, and results. |
| `core/` | The compiled core: its C++ source and the built module. |

## Import rules

The Blender-facing code is three tiers, each importing only the tiers below it, with the bpy-free code, `core/`, `binding/source_access/`, and `binding/results.py`, below all three ([tiers](../../docs/plans/source-tiers-and-names.md#tiers)):

| Package | May import |
|---|---|
| `api/` | `binding.runtime`, `binding.persistence`, `core`, `binding.source_access`, `binding.results` |
| `binding/runtime/` | `binding.persistence`, `core`, `binding.source_access`, `binding.results` |
| `binding/persistence/` | `core`, `binding.source_access`, `binding.results` |
| `core/`, `binding/source_access/`, `binding/results.py` | each only itself, and never `bpy` |
| `binding/__init__.py` | nothing |

`addon.py` may import any of them. Code outside `binding/` imports its units and uses what each exports, never the modules inside them, and inside `binding/` a tier's modules are reached only through its package. `tests/bpy_free/test_import_tiers.py` checks these rules by reading each module's imports, and fails on any import of a Blender module in the bpy-free code and its packages; `tests/bpy_free/test_no_blender_imports.py` checks that they import in a fresh interpreter with Blender's modules blocked.
