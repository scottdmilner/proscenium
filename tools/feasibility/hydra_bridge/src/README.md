# Hydra bridge sources

The C++ side of the M1b prototype: a compiled Python module, `_hydra_bridge`, that turns a caller's USD stage into a display plan through a Hydra scene-index graph. It is feasibility code for the [M1b evaluation gate](../../../../docs/plans/M01b-evaluation-gate.md), not production code. It links against the OpenUSD that Blender ships and never against a second USD build.

`../build.py` builds it (C++17, CMake, and Ninja from the dev group), and `../run.py` runs the checks in `../probe.py` (loading), `../prototype_probe.py` (the Phase B slice) and `../correctness_probe.py` (the Phase C cases in `../cases/`) in the bpy wheel and the Blender binary.

## Data flow

```text
Usd.Stage ──► SceneIndexGraph ──capture──► Snapshot ──build_plan──► Plan ──apply.py──► Blender
            (Hydra)   (C++, no GIL)  (immutable)  (C++, no GIL)  (immutable)    (Python, bpy)
```

1. **Scene-index graph.** `UsdImagingCreateSceneIndices` (draw mode off), with the source-info filter in its overrides slot right after the stage scene index, is followed by these filters:
   - ext-computation primvar pruning;
   - implicit surfaces to meshes;
   - NURBS approximation;
   - dependency forwarding;
   - prim-type notice batching, which is the terminal.

   The graph is built explicitly rather than through renderer plugin registration, so it doesn't depend on what else is on Blender's plugin path.

   The source-info filter adds what the UsdImaging chain drops, read from the USD prim at the same path. Under a `prosceniumSource` container:
   - subset `familyName`;
   - authored purpose visibility, as UsdImaging attribute data sources, so animated opinions read at the graph's time and are dirtied when it changes;
   - `doubleSided`;
   - UsdShade's resolved binding per material purpose, and the purposes a prim binds `strongerThanDescendants`;
   - USD's verdict on a mesh's materialBind family (`UsdGeomSubset::ValidateFamily`);
   - for prims Hydra doesn't image (HermiteCurves), their USD type;
   - on gprims and point instancers, the authored attributes UsdImaging drops (not primvars, not in a schema), so the planner can warn;
   - material:binding relationships authored without `MaterialBindingAPI`, which UsdShade honors only for compatibility, so the planner can warn.

   For prims UsdImaging doesn't image at all (no `__usdPrimInfo`) it supplies `UsdImagingDataSourcePrim`, UsdImaging's own data for a prim without an adapter (transform, visibility, purpose, authored extent, primvars). It runs on the filter's own `UsdImagingDataSourceStageGlobals` subclass, which gives it the graph's time and records what it flags as time-varying, so a time change dirties exactly that. For curves, points and HermiteCurves without an authored extent it supplies USD's computed extent, so their placeholders show bounds. Its containers read USD at the graph's time, cached per prim and rebuilt only when that prim or something its facts depend on changes (an ancestor's binding, a collection, a mesh's subsets), and it listens to the stage for edits Hydra doesn't notice, dirtying the prims concerned when the graph advances.

   Values the core puts into Hydra use Vt's own value types: an `SdfPath` made in this module isn't recognized by USD's code (`HdMakeStaticCopy` posts "Unsupported type SdfPath"), so bound material paths travel as tokens.

2. **Capture.**
   - `SetTime` and `ApplyPendingUpdates` run, then the batching flush, then one parallel pass over the terminal.
   - The pass copies the schemas planning reads (`PlannedSchemas()`) with Hydra's `HdMakeStaticCopy`, one retained container per prim, into an `HdRetainedSceneIndex`. That retained scene index is the `Snapshot`, a Hydra-native frozen scene, so Hydra's own traversal and debug printing work on it.
   - `VtArray`s share storage copy-on-write, so copying them is cheap, and later edits and time changes can't reach the snapshot.
   - An incremental capture re-copies only the prims named in notices since the bridge's previous capture: added, dirtied, or under a removed or renamed path. The other prims share the previous snapshot's retained containers, which never change. The correctness probe compares incremental captures with full ones record by record.
   - Paths in a snapshot are Hydra paths.
3. **Planning.** The planner reads the schemas it needs from the snapshot into plain records, in parallel, then turns them into a `Plan`:
   - validated meshes in Blender's exact element types;
   - material slots from GeomSubsets: slot 0 for the mesh's binding, then one per materialBind subset;
   - primvars as attributes on Blender's domains: authored normals as Blender's `custom_normal`, `velocities` as `velocity`;
   - each object's constant primvars, its own and inherited from instance roots, as the ID properties Blender holds;
   - one object per drawn copy, with its USD source path and native-instance context;
   - placeholders for untranslated types: a bounding box when Hydra has an extent, otherwise an empty marker;
   - for each object, whether it displays in the viewport and the final render: its effective visibility (purpose visibility included) and whether the destination includes its purpose;
   - each object's materials per slot, resolved for the material purpose of each destination it displays in, falling back to allPurpose as UsdShade does. A prim shown in both with different materials gets two objects sharing its mesh;
   - diagnostics.

   Sources in a plan are USD paths; Hydra paths and instance indices never are.
4. **Application** (`../apply.py`) passes the plan's Vt arrays to `foreach_set` as flat `memoryview`s, with no Python-side copy.

## Files

| File | Role |
|---|---|
| `module.cpp` | `PXR_BOOST_PYTHON_MODULE`: the `Bridge` class, time conversion, and the loading-check functions |
| `bridge.h/.cpp` | Takes the caller's stage as a weak pointer and owns the scene-index graph and the last snapshot. `Release()` drops both so the stage can expire. A `TfRefPtr` argument would have moved the Python object's ownership into C++ |
| `capture.h/.cpp` | The parallel pass that fills a `Snapshot`'s retained scene index with static copies of the planned schemas, full or incremental; diagnostics without duplicates |
| `scene_index_graph.h/.cpp` | Builds the scene-index graph, advances it in time, and records the terminal's notices |
| `source_info_scene_index.h/.cpp` | The source-info filter: the source facts Hydra drops (a `prosceniumSource` container), `UsdImagingDataSourcePrim` on its own stage globals for unimaged prims, and notices for edits Hydra misses |
| `source_facts.h/.cpp` | What the filter reads from USD: the `prosceniumSource` tokens and lazy containers, UsdShade's bindings per material purpose, the materialBind family verdict, dropped attributes, and computed extents for point-based prims other than meshes and NURBS patches |
| `snapshot.h/.cpp` | The snapshot: time, retained scene index, events (`EventKind`), diagnostics |
| `prim_record.h/.cpp` | Plain records of what planning reads: mesh topology as `PxOsdMeshTopology`, primvars (indices kept), subsets, instancers, materials |
| `prim_reader.h/.cpp` | `PlannedSchemas()`, the schemas capture copies, and the reader of those records: traversal by `HdSceneIndexPrimView`, materials through `HdDataSourceMaterialNetworkInterface` |
| `instancing.h/.cpp` | Reverse mapping from instancers to USD sources, as `HdxPrimOriginInfo` does it: walks `instancedBy` upward and folds in `instanceLocations`, instance transforms, the instancer's visibility mask, the instance roots' own constant primvars and bindings, and purpose-visibility opinions at each level. `BoundMaterial` combines the filter's UsdShade bindings with what's bound at or above each instance root (Hydra's flattened bindings are unusable inside instances). Switch source identity to `HdxPrimOriginInfo` once Blender's USD has its `cdata()` fix (plan log) |
| `validate.h/.cpp` | Checks before anything reaches Blender: `PxOsdMeshTopology::Validate`, then indices against the points, primvar lengths, and subset indices |
| `mesh_builder.h/.cpp` | A captured mesh to Blender arrays: corner order (left-handed faces reversed), material slots from materialBind subsets, attributes (custom normals and velocity under Blender's names) |
| `plan.h`, `planner.cpp` | Plan types, `PlanSettings` (each destination's prim purposes and material purpose), and `BuildPlan`: meshes built in parallel, then added to the plan with their objects, materials and diagnostics in prim order |
| `properties.h/.cpp` | Constant primvars to Blender ID-property values (scalars, strings, lists, nested rows), and which names and types Blender can't hold |
| `diagnostics.h/.cpp` | Diagnostic records; Tf errors and warnings collected per prim, or raised as Python exceptions |
| `python_views.h/.cpp` | The `Snapshot` and `Plan` Python views, and `build_plan` |
| `loaded_images.h/.cpp` | Which USD images the process has loaded, for the exactly-one-USD checks |
| `copy_bindings.h/.cpp` | **Workaround for OpenUSD #3690:** UsdShade's binding per drawn copy, on its instance-proxy path, for the instances a binding collection reaches (Hydra and per-prototype resolution miss collections naming paths inside instances). Cached in the source-info filter until a binding or collection edit; the planner uses it for those copies |
| `fact_timings.h/.cpp` | Phase E only: time the source-info filter spends building facts and in each USD query (bindings, strong purposes, family verdict, dropped attributes, computed extents), summed over threads, and how planning's time splits (reading, building each mesh and its parts, objects) |

The rest of `hydra_bridge/` builds, runs and checks the module:

| File | Role |
|---|---|
| `../CMakeLists.txt` | The module's build against Blender's USD headers and libraries |
| `../build.py` | Builds the module and audits its USD linkage for this platform, through `tools/native_build.py`; the headers come from `tools/blender_deps.py`, pinned by the Blender release in `uv.lock` |
| `../run.py` | Runs the three probes with the same compiled module in the bpy wheel and the Blender binary |
| `../probe.py` | Loading checks: stage exchange, time, inheritance, instancing and stage expiry, on `../scene.usda` |
| `../prototype_probe.py` | Phase B smoke checks of capture, plan and application, on `../prototype.usda` |
| `../correctness_probe.py` | Runs each Phase C case in `../cases/`; a failing case is recorded and the rest still run |
| `../apply.py` | Applies a plan to Blender (meshes, slots, attributes, objects and their properties, placeholders, destination hide flags) |
| `../plan_types.py` | `TypedDict`s for the plan dicts that `python_views.cpp` builds; production should bind classes instead |
| `../cases/harness.py`, `../cases/oracle.py` | What each case gets (module, application, scratch directory, checks), and expected values from UsdGeom and UsdShade, never from Hydra |
| `../measure/run.py` | Phase E measurements: Blender's USD importer against the prototype, one sampled Blender process per run (`child.py`), on the bespoke scenes, generated stress scenes (`stress.py`) and ALab through its measurement entry point (`alab_entry.py`); `report.py` summarizes, `memory.py` reads each platform's memory counters |
| `../cases/<case>.py`, `.usda` | One check module and scene per case: `subsets`, `implicit`, `instances`, `edits`, `untranslated`, `malformed`, `bindings`, `purposes`, `primvars`, `animation` (Phase D: what a time change dirties, and values at each time), and `large_arrays` (its scene is generated) |

## Python API

```python
bridge = _hydra_bridge.Bridge(stage)  # raises on an invalid stage or a Tf error while building the graph
snapshot = bridge.capture(1.0)  # or capture() / capture(None) for default time, or a Usd.TimeCode
snapshot = bridge.capture(1.0, incremental=True)  # shares unchanged prims with the bridge's previous capture
snapshot.paths(), snapshot.prim(path)  # Hydra paths; prim() returns a dict of what planning reads, or None
snapshot.dump(path)  # a prim's retained schemas, as HdDebugPrintDataSource text
snapshot.events, snapshot.dirty_locators, snapshot.renames  # (kind, path); path -> locators; (old, new)
snapshot.copied, snapshot.diagnostics, snapshot.time  # prims copied by this capture; time is None at default time
plan = _hydra_bridge.build_plan(snapshot)  # destinations: viewport_purposes, viewport_material_purpose,
#   render_purposes, render_material_purpose (purposes by USD name; material purpose "", "preview", "full")
plan.meshes, plan.materials, plan.objects, plan.diagnostics  # lists of dicts; a placeholder object has "bounds"
bridge.release()  # lets a caller-released stage expire; capture() then raises
snapshot.copy_bindings  # workaround for OpenUSD #3690: {"instances": [...], "materials": {copy: {purpose: material}}}
_hydra_bridge.take_filter_timings()  # Phase E: {kind: (calls, seconds)} of the filter's USD reads since the last call
```

A capture evaluates one time code. At default time it reads authored default values, so animated values need a numeric time. Capturing several frames, and caching them, is a layer above capture ([feasibility record](../../../../docs/feasibility/runtime-record.md#time-sampled-data-detection-m1b-phase-d)).

## What the snapshot holds

Only the schemas planning reads, each copied whole with `HdMakeStaticCopy`. The [spec](../../../../docs/spec/pipeline.md#evaluated-source-snapshot) requires values captured before planning and unchanged during it, not a copy of all scene data. Authoring goes through the USD stage, so an editor doesn't need a complete copy either.

- **Untyped values.** `HdMakeStaticCopy` copies values typed only for Vt's value types and a fixed list of Sdf and Hd types. Any other type posts a Tf error and is dropped, and capture turns that error into a diagnostic. On `prototype.usda`, copying the planned schemas posts no Tf errors; other content, such as material parameters of unusual types, could. The `system` container, whose `ArResolverContext` Hydra can't copy, is not copied.
- **The source-info container** (`prosceniumSource`) and `extent` are copied with the Hydra schemas.
- **Diffing two snapshots** with `HdsiComputeSceneIndexDiffDelta` compares data-source handles, not values. A prim whose handle differs is reported dirty for every locator (v26.03 `hdsi/computeSceneIndexDiff.cpp`). So between incremental captures it lists the prims that were re-copied, not the values that changed.

## Conventions

- **C++17,** in `namespace hydra_bridge`. Each stage gets its own header and source. Types follow USD's naming (`PascalCase` methods, `member_` fields).
- **Warnings.** The bridge's own code builds clean with `-Wall -Wextra -Wpedantic`, or `/W4` on MSVC. USD's headers are system includes.
- **No Python inside the pipeline.** Only `module.cpp`, `python_views.cpp`, and `RaiseTfErrors` touch `pxr_boost::python`. Capture and planning run without the GIL.
- **Threading.** Reads of the terminal may run in parallel, but never alongside `Advance`, stage edits, or notice delivery.
- **Errors, not crashes.**
  - Every data source is null-checked when its records are read, and every index is validated before it is used.
  - Invalid geometry becomes a placeholder and a diagnostic, never an exception partway through a plan.
  - Tf errors and warnings during capture become diagnostics; only the bridge constructor raises them. Warnings posted while the bridge is built join its first capture's diagnostics, without a source; those posted at release are still printed. (Only warnings have been exercised.)
  - Recursion over instancing is depth-limited.
- **Pulls register time-variance.** Copying pulls each planned schema, so the stage scene index flags its time-varying values, and `SetTime` dirties them. The source-info filter dirties what its stage globals recorded as time-varying when the time changes: what `UsdImagingDataSourcePrim` and its purpose-visibility attribute data sources flag, computed extents of animated points, and animated subset indices, which UsdImaging reads at the current time but never flags. It also dirties the prims whose source facts a stage edit changed.
- **Lifetime.** The plan and snapshot are `std::shared_ptr<const …>`. Python views hold that pointer, and the Vt arrays they return keep their own storage alive. A released stage can outlive `release()` briefly (cause not identified).
