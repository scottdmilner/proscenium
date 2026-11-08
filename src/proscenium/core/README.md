# `proscenium.core`

The compiled core and its C++ source. It reads Hydra scene indices ([DECISIONS.md](../../../docs/DECISIONS.md) "Evaluation front end and core language"). AGENTS.md's [Compiled core](../../../AGENTS.md#compiled-core) section has its build, boundary, and style rules. It imports without `bpy` and may import only itself; `tests/bpy_free` imports it with Blender's modules blocked.

## Python

| File | Holds |
|---|---|
| `__init__.py` | The package's exports: `_core`. It imports `pxr.Usd` first, which loads Blender's `usd_ms` and the converters the compiled module's arguments need. |
| `_core.pyi` | The compiled module's types, so ty checks its callers without a build. |

## C++

| File | Holds |
|---|---|
| `module.cpp` | The Python module, `proscenium.core._core`. |
| `diagnostics.h`, `diagnostics.cpp` | The source-side diagnostics the core reports, each named by a code from Python's `DiagnosticCode` list, and every code it can report; and the collector of Tf errors and warnings posted while reading the source, attributed to the prim being read. |
| `errors.h`, `errors.cpp` | Error translation for every entry point: Tf errors and C++ exceptions become Python exceptions. |
| `stage_handle.h`, `stage_handle.cpp` | `StageHandle`, the core's reference to a stage it was given, which it drops on `Release()` so the core never keeps a released stage alive. |
| `scene_index_chain.h`, `scene_index_chain.cpp` | `SceneIndexChain`, the Hydra scene-index chain over an evaluation stage, and its capture of a snapshot at a time code. |
| `source_info_scene_index.h`, `source_info_scene_index.cpp` | `SourceInfoSceneIndex`, the source-info filter right after the stage scene index: UsdImaging's prim data for prims Hydra doesn't image, computed extents for curves and points, authored purpose visibility, and each instance root's USD prototype. |
| `source_facts.h`, `source_facts.cpp` | What the filter reads from USD: the `prosceniumSource` container's tokens and facts, its lazily rebuilt containers, and computed extents. |
| `instancing.h`, `instancing.cpp` | `InstanceResolver`, provisional: the drawn copies of a prim inside native instances, mapped back from Hydra's instancers to instance-proxy sources and instance contexts, with the workaround for OpenUSD #862, and each copy's effective visibility through its instance roots. |
| `snapshot.h`, `snapshot.cpp` | `Snapshot`, the evaluated source snapshot: a retained scene index of static copies of the schemas planning reads (`PlannedSchemas`), borrowing nothing from the chain, the stage's `metersPerUnit` and `upAxis`, and the Tf errors and warnings posted while capturing. |
| `prim_record.h`, `prim_record.cpp` | Plain records of what planning reads from a snapshot, and the table of them by path. |
| `prim_reader.h`, `prim_reader.cpp` | The reader of those records, once per plan. |
| `plan.h`, `plan.cpp` | The planning settings and context, the display plan's envelope, and the planner: each drawn copy of a gprim in a copy table of read-only buffers, with its world transform under coordinate conversion's correction, split with a shear parent when it shears, and each destination's participation, a mesh's copies sharing its provisional geometry description and any other gprim's copy a placeholder. |
| `CMakeLists.txt` | The build, against the locked Blender release's headers, linking only Blender's `usd_ms`. `tools/build_extension.py` runs it through `tools/native_build.py`. |
| `.clang-format` | The C++ style, run as a pre-commit hook (the checks are the repository's root `.clang-tidy`). |
| `.gitignore` | Ignores the built module, `_core.*.so` or `_core.*.pyd`, which the build puts in this directory and only the zip ships. |
