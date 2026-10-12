# Hydra bridge sources

The C++ side of the M1b prototype: a compiled Python module, `_hydra_bridge`, that turns a caller's USD stage into a display plan through a Hydra scene-index graph. It is feasibility code for the [M1b evaluation gate](../../../../docs/plans/M01b-evaluation-gate.md), not production code. It links against the OpenUSD that Blender ships and never against a second USD build.

`../build.py` builds it (C++17, CMake, and Ninja from the dev group), and `../run.py` runs the checks in `../probe.py` and `../prototype_probe.py` in the bpy wheel and the Blender binary.

## Data flow

```text
Usd.Stage ──► SceneIndexGraph ──capture──► Snapshot ──build_plan──► Plan ──apply.py──► Blender
            (Hydra)   (C++, no GIL)  (immutable)  (C++, no GIL)  (immutable)    (Python, bpy)
```

1. **Scene-index graph.** `UsdImagingCreateSceneIndices` (draw mode off) is followed by these filters:
   - ext-computation primvar pruning;
   - implicit surfaces to meshes;
   - NURBS approximation;
   - dependency forwarding;
   - prim-type notice batching, which is the terminal.

   The graph is built explicitly rather than through renderer plugin registration, so it doesn't depend on what else is on Blender's plugin path.
2. **Capture.**
   - `SetTime` and `ApplyPendingUpdates` run, then the batching flush, then one parallel pass over the terminal.
   - The pass copies the schemas planning reads (`PlannedSchemas()`) with Hydra's `HdMakeStaticCopy`, one retained container per prim, into an `HdRetainedSceneIndex`. That retained scene index is the `Snapshot`, a Hydra-native frozen scene, so Hydra's own traversal and debug printing work on it.
   - `VtArray`s share storage copy-on-write, so copying them is cheap, and later edits and time changes can't reach the snapshot.
   - Paths in a snapshot are Hydra paths.
3. **Planning.** The planner reads the schemas it needs from the snapshot into plain records, in parallel, then turns them into a `Plan`:
   - validated meshes in Blender's exact element types;
   - material slots from GeomSubsets;
   - primvars as attributes on Blender's domains;
   - one object per drawn copy, with its USD source path and native-instance context;
   - placeholders for untranslated types;
   - diagnostics.

   Sources in a plan are USD paths; Hydra paths and instance indices never are.
4. **Application** (`../apply.py`) passes the plan's Vt arrays to `foreach_set` as flat `memoryview`s, with no Python-side copy.

## Files

| File | Role |
|---|---|
| `module.cpp` | `PXR_BOOST_PYTHON_MODULE`: the `Bridge` class, time conversion, and the loading-check functions |
| `bridge.h/.cpp` | Holds the caller's stage weakly and owns the scene-index graph; `Release()` drops the graph so the stage can expire |
| `capture.h/.cpp` | The parallel pass that fills a `Snapshot`'s retained scene index with static copies of the planned schemas |
| `scene_index_graph.h/.cpp` | Builds the scene-index graph, advances it in time, and records the terminal's notices |
| `snapshot.h/.cpp` | The snapshot: time, retained scene index, events (`EventKind`), diagnostics |
| `prim_record.h/.cpp` | Plain records of what planning reads: mesh topology as `PxOsdMeshTopology`, primvars (indices kept), subsets, instancers, materials |
| `prim_reader.h/.cpp` | `PlannedSchemas()`, the schemas capture copies, and the reader of those records: traversal by `HdSceneIndexPrimView`, materials through `HdDataSourceMaterialNetworkInterface` |
| `instancing.h/.cpp` | Reverse mapping from instancers to USD sources, as `HdxPrimOriginInfo` does it: walks `instancedBy` upward and folds in `instanceLocations` and instance transforms at each level. Switch source identity to `HdxPrimOriginInfo` once Blender's USD has its `cdata()` fix (plan log) |
| `validate.h/.cpp` | Checks before anything reaches Blender: `PxOsdMeshTopology::Validate`, then indices against the points, primvar lengths, and subset indices |
| `mesh_builder.h/.cpp` | A captured mesh to Blender arrays: corner order (left-handed faces reversed), material slots, attributes |
| `plan.h`, `planner.cpp` | Plan types and `BuildPlan` |
| `diagnostics.h/.cpp` | Diagnostic records; Tf errors and warnings collected per prim, or raised as Python exceptions |
| `python_views.h/.cpp` | The `Snapshot` and `Plan` Python views, and `build_plan` |
| `loaded_images.h/.cpp` | Which USD images the process has loaded, for the exactly-one-USD checks |

## Python API

```python
bridge = _hydra_bridge.Bridge(stage)  # raises on an invalid stage or a Tf error while building the graph
snapshot = bridge.capture(1.0)  # or capture() / capture(None) for default time, or a Usd.TimeCode
snapshot.paths(), snapshot.prim(path)  # Hydra paths; prim() returns a dict of what planning reads, or None
snapshot.dump(path)  # a prim's retained schemas, as HdDebugPrintDataSource text
snapshot.events, snapshot.dirty_locators, snapshot.renames  # (kind, path); path -> locators; (old, new)
snapshot.diagnostics, snapshot.time  # time is None at default time
plan = _hydra_bridge.build_plan(snapshot)
plan.meshes, plan.materials, plan.objects, plan.diagnostics  # lists of dicts
bridge.release()  # lets a caller-released stage expire; capture() then raises
```

A capture at default time works, but every sample-time query reports false there. Time-variance detection (Phase D) therefore needs a numeric time.

## What the snapshot holds

Only the schemas planning reads, each copied whole with `HdMakeStaticCopy`. The [spec](../../../../docs/spec/pipeline.md#evaluated-source-snapshot) requires values captured before planning and unchanged during it, not a copy of all scene data. Authoring goes through the USD stage, so an editor doesn't need a complete copy either.

- **Untyped values.** `HdMakeStaticCopy` copies values typed only for Vt's value types and a fixed list of Sdf and Hd types. Any other type posts a Tf error and is dropped, and capture turns that error into a diagnostic. On `prototype.usda`, copying the planned schemas posts no Tf errors; other content, such as material parameters of unusual types, could. The `system` container, whose `ArResolverContext` Hydra can't copy, is not copied.
- **Diffing two snapshots** with `HdsiComputeSceneIndexDiffDelta` compares data-source handles, not values. A prim whose handle differs is reported dirty for every locator (v26.03 `hdsi/computeSceneIndexDiff.cpp`). So it lists the prims that were re-copied, not the values that changed. That becomes useful once captures share unchanged prims' handles (Phase C).

## Conventions

- **C++17,** in `namespace hydra_bridge`. Each stage gets its own header and source. Types follow USD's naming (`PascalCase` methods, `member_` fields).
- **Warnings.** The bridge's own code builds clean with `-Wall -Wextra -Wpedantic`, or `/W4` on MSVC. USD's headers are system includes.
- **No Python inside the pipeline.** Only `module.cpp`, `python_views.cpp`, and `RaiseTfErrors` touch `pxr_boost::python`. Capture and planning run without the GIL.
- **Threading.** Reads of the terminal may run in parallel, but never alongside `Advance`, stage edits, or notice delivery.
- **Errors, not crashes.**
  - Every data source is null-checked when its records are read, and every index is validated before it is used.
  - Invalid geometry becomes a placeholder and a diagnostic, never an exception partway through a plan.
  - Tf errors during capture become diagnostics; only the bridge constructor raises them.
  - Recursion over instancing is depth-limited.
- **Pulls register time-variance.** Copying pulls each planned schema, so the stage scene index flags its time-varying values, and `SetTime` dirties them. This matters for Phase D's dirty sets.
- **Lifetime.** The plan and snapshot are `std::shared_ptr<const …>`. Python views hold that pointer, and the Vt arrays they return keep their own storage alive.
