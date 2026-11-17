# `proscenium_sync.core`

The compiled core and its C++ source. It reads Hydra scene indices ([DECISIONS.md](../../../../../docs/DECISIONS.md) "Evaluation front end and core language"). AGENTS.md's [Compiled core](../../../../../AGENTS.md#compiled-core) section has its build, boundary, and style rules. It imports without `bpy` and may import only itself; `tests/bpy_free` imports it with Blender's modules blocked.

## Python

| File | Holds |
|---|---|
| `__init__.py` | The package's exports: every public name of the compiled module, which is the package's own, so callers write `core.Plan`. It imports `pxr.Usd` first, which loads Blender's `usd_ms` and the converters the compiled module's arguments need. |
| `_core.pyi` | The compiled module's types, so ty checks its callers without a build. |

## C++

| File | Holds |
|---|---|
| `python_bindings.cpp` | Python wrappers, read-only buffer exposure, reads of only the plan elements asked for, and registration of `proscenium_sync.core._core`. |
| `correspondence.h`, `correspondence.cpp` | The correspondence layer, ported from the bridge's `correspondence` and `interaction`: a shown generation's display elements as Python gives them, each copy's instance context derived from its path on the live stage when no held plan gives it, floors, the browsing universe, and the viewport's elements by floor; `resolve_pick`, `displayed`, `highlight_targets`, and, through the inspection layer, `select_targets` and `selection_from_blender`, which raise `SourceUnavailableError` once the live stage expires. |
| `plan_diff.h`, `plan_diff.cpp` | What a new plan changes from the plan of the generation the destination shows, ported from the bridge's `plan_diff` for M7's content: drawn copies matched by identity, and each kept copy rebuilt where its partition holds other resources, or else moved, its bounds changed, or its participation changed. |
| `batch_groups.h`, `batch_groups.cpp` | The drawn copies a batch shows as instances of one prototype, grouped by what they share, as the bridge's `batch_groups` does. |
| `diagnostics.h`, `diagnostics.cpp` | The source-side diagnostics the core reports, each named by a code from Python's `DiagnosticCode` list, and every code it can report; `SummarizeRepeatedDiagnostics`, which lists a problem's first ten prims and counts the rest; and the collector of Tf errors and warnings posted while reading the source, attributed to the prim being read. |
| `python_error_translation.h`, `python_error_translation.cpp` | Error translation for every entry point: Tf errors and C++ exceptions become Python exceptions. |
| `stage_handle.h`, `stage_handle.cpp` | `StageHandle`, the core's reference to a stage it was given, which it drops on `Release()` so the core never keeps a released stage alive. |
| `scene_index_chain.h`, `scene_index_chain.cpp` | `SceneIndexChain`, the Hydra scene-index chain over an evaluation stage, and its capture of a snapshot at a time code, copying in parallel only the prims notices named since its capture before, and sharing the rest; and, for tests of missed notices only, a hook that makes its next capture drop them. |
| `scene_index_notices.h`, `scene_index_notices.cpp` | `NoticeRecorder`, which records the notices the chain's terminal sends between captures, as the bridge's `RecordingObserver` does, and `NoticedPrims`, the prims they name. |
| `source_info_scene_index.h`, `source_info_scene_index.cpp` | `SourceInfoSceneIndex`, the source-info filter right after the stage scene index: UsdImaging's prim data for prims Hydra doesn't image, computed extents for gprims other than meshes (curves, points, and the meshes implicit shapes and NURBS patches become), authored purpose visibility, each instance root's USD prototype, the USD type of gprims other than meshes and of point instancers, and a point instancer's authored ids; and its stage listener, which dirties what of those Hydra doesn't. |
| `source_facts.h`, `source_facts.cpp` | What the filter reads from USD: the `prosceniumSource` container's tokens and facts, among them a non-mesh gprim's authored extent, which reads a value block as none, computed extents, and which properties they read (`FactReadsProperty`). |
| `revision_cached_container.h`, `revision_cached_container.cpp` | `RevisionCachedContainer`, a lazy Hydra container that reuses its contents until its revision counter changes, with mutex-protected cache access and rebuilding. |
| `instancing.h`, `instancing.cpp` | `InstanceResolver`, provisional: the drawn copies of a prim inside native instances or a point instancer's prototypes, mapped back from Hydra's instancers to instance-proxy or point-instance sources and instance contexts, with the workaround for OpenUSD #862, and each copy's effective visibility through its instance roots. |
| `snapshot.h`, `snapshot.cpp` | `Snapshot`, the evaluated source snapshot: a retained scene index of static copies of the schemas planning reads (`PlannedSchemas`), borrowing nothing from the chain, the stage's `metersPerUnit` and `upAxis`, the Tf errors and warnings posted while capturing, each prim's own, and how many prims it copied. |
| `prim_record.h`, `prim_record.cpp` | Plain records of what planning reads from a snapshot, and the table of them by path. |
| `snapshot_prim_reader.h`, `snapshot_prim_reader.cpp` | Reads the frozen snapshot into plain prim records, once per plan, in parallel. |
| `plan.h`, `plan.cpp` | The planning settings and context, the display plan's envelope, and the planner: each drawn copy of a gprim in a copy table of read-only buffers, with its world transform under coordinate conversion's correction, split with a shear parent when it shears, the resources of its partition, and each destination's participation, a mesh's copies sharing its provisional geometry description, any other gprim's copy a placeholder or, with no usable bounds, an empty marker, and their diagnostics. |
| `inspection/` | The inspection layer, a static library of its own that includes and links only USD, which the core links ([its README](inspection/README.md)). |
| `CMakeLists.txt` | The build, against the locked Blender release's headers, linking only Blender's `usd_ms`, with the settings it and the inspection layer's build share (`proscenium_compile_settings`). `tools/build_extension.py` runs it through `tools/native_build.py`. |
| `.clang-format` | The C++ style, run as a pre-commit hook (the checks are the repository's root `.clang-tidy`). |
| `.gitignore` | Ignores the built module, `_core.*.so` or `_core.*.pyd`, which the build puts in this directory and only the package's wheel ships (`hatch_build.py`). |
