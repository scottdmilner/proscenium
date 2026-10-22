# `proscenium`

The extension's source directory: what `tools/build_extension.py` zips into the extension Blender installs. It holds the extension's manifest and registration, and its code in four packages.

| Path | Holds |
|---|---|
| `blender_manifest.toml` | The extension manifest. Its `[build]` patterns keep the C++ sources, CMake files, and these READMEs out of the zip; only the built core module ships. |
| `__init__.py` | The package, with `register` and `unregister`. It imports without `bpy`, and imports `addon` only when Blender registers the extension. |
| `addon.py` | Registration: the record namespace's property group, and the handlers for file load, undo, and redo that keep the bindings' in-memory state current. |
| `api/` | What callers use: the binding handle and the process's bindings. |
| `runtime/` | Disposable in-memory state built from `persistence/`'s records. |
| `persistence/` | Versioned records in Blender ID properties. |
| `core/` | Everything that imports without `bpy`, including the compiled core's C++ source. |

## Import rules

The Blender-facing code is three tiers, each importing only the tiers below it, with `core/` below all three ([tiers](../../docs/plans/source-tiers-and-names.md#tiers)):

| Package | May import |
|---|---|
| `api/` | `runtime`, `persistence`, `core` |
| `runtime/` | `persistence`, `core` |
| `persistence/` | `core` |
| `core/` | `core` only, and never `bpy` |

`addon.py` may import any of them. `tests/bpy_free/test_import_tiers.py` checks these rules by reading each module's imports, and `tests/bpy_free/test_no_blender_imports.py` checks that `proscenium` and `proscenium.core` import with Blender's modules blocked.
