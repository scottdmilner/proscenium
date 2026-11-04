# `proscenium.core`

The compiled core and its C++ source. It reads Hydra scene indices ([DECISIONS.md](../../../docs/DECISIONS.md) "Evaluation front end and core language"). AGENTS.md's [Compiled core](../../../AGENTS.md#compiled-core) section has its build, boundary, and style rules. It imports without `bpy` and may import only itself; `tests/bpy_free` imports it with Blender's modules blocked.

## Python

| File | Holds |
|---|---|
| `__init__.py` | The package. It imports `pxr.Usd` first, which loads Blender's `usd_ms` and the converters the compiled module's arguments need. |
| `_core.pyi` | The compiled module's types, so ty checks its callers without a build. |

## C++

| File | Holds |
|---|---|
| `module.cpp` | The Python module, `proscenium.core._core`. |
| `errors.h`, `errors.cpp` | Error translation for every entry point: Tf errors and C++ exceptions become Python exceptions. |
| `stage_handle.h`, `stage_handle.cpp` | `StageHandle`, the core's reference to a stage it was given, which it drops on `Release()` so the core never keeps a released stage alive. |
| `scene_index_chain.h`, `scene_index_chain.cpp` | `SceneIndexChain`, the Hydra scene-index chain over an evaluation stage, and its capture of a snapshot at a time code. |
| `snapshot.h` | `Snapshot`, the evaluated source snapshot: plain values, borrowing nothing from the chain. |
| `plan.h`, `plan.cpp` | The planning context, the display plan's envelope, and M5's minimal planner, one placeholder per drawn gprim. |
| `CMakeLists.txt` | The build, against the locked Blender release's headers, linking only Blender's `usd_ms`. `tools/build_extension.py` runs it through `tools/native_build.py`. |
| `.clang-format` | The C++ style, run as a pre-commit hook (the checks are the repository's root `.clang-tidy`). |
| `.gitignore` | Ignores the built module, `_core.*.so` or `_core.*.pyd`, which the build puts in this directory and only the zip ships. |
