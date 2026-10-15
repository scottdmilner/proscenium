# M1b — Evaluation front end and core language gate: plan

How M1b will reach its decision, what the research before it found, and the order of work. Requirements are in the [M1b milestone](../milestones/M01b-evaluation-gate.md); where this plan and a requirement file disagree, the requirement file wins. Mechanisms named here are suggestions unless a phase records them as settled. Once work starts, each phase gains a short decision log in the style of the [M1 plan](M01-runtime.md).

## Research basis (2026-10-09)

Four source-reading investigations covered the Hydra 2 core, the UsdImaging scene-index chain, HdStorm/HdEmbree/HdPrman as reference consumers, and native builds and the C++/Python boundary. They read OpenUSD v26.03 (what Blender 5.2 bundles) and `dev` at `5bc38c9`, the Blender 5.2.2 sources and pinned `lib-*` repositories, and the shipped binaries. **Unless marked *measured*, findings come from reading code and documents, not from running anything.** They are inputs for the phases below to verify, not results.

### What changes the shape of the work

- **Distribution.** The [extensions.blender.org Terms of Service](https://extensions.blender.org/terms-of-service/) §3.6 (updated 10 August 2026) forbids non-Python source and "external, pre-compiled packages". **Settled with the user (2026-10-09): Proscenium will not be listed on extensions.blender.org, so §3.6 does not apply.** A compiled core ships through another channel, which the "Native core distribution" row names.
- **USD version lock.** Blender 5.2.0–5.2.2 ship byte-identical USD headers and libraries. Blender 5.3 and `main` move to USD 26.08, which changes the namespace (`pxrBlender_v26_03__pxrReserved__`). A compiled core needs a rebuild and new dependency pins for every Blender minor release, and a `blender_version_max`.
- **No render delegate.** Storm and Embree consume the scene-index chain through Hydra 1 emulation (`HdRprim::Sync` and dirty bits). Emulation drops GeomSubsets without a material binding, folds invisible subsets into hidden faces, and loses USD instance paths (`GetScenePrimPath` is not implemented under emulation). HdPrman's scene-index-native path is experimental, off by default, and only handles spheres. The prototype reads the terminal scene index directly, as the bridge does, with no `HdRenderIndex`.
- **No prior art.** No public project was found that translates Hydra 2 scene indices into an application's native scene (MayaHydra and Omniverse go application → Hydra). The search was not exhaustive.

### Scene-index chain (v26.03)

- `UsdImagingCreateSceneIndices` chains, in order: stage → optional override callback → optional unloaded draw mode → extent resolving → point-instancer and native-instance prototype propagation → notice batching → instance-proxy path translation → material-binding resolution → UsdImaging plugin scene indices (in Blender's build, usdSkelImaging's skeleton and points resolving) → selection → render-settings flattening.
- **It already flattens.** Native-instance propagation inserts an `HdFlatteningSceneIndex` at every instancing level, so its output carries flattened xform, visibility, purpose, primvars, material bindings, and model. The bridge's own flattening pass is redundant, and its *tested* inherited state came from the internal pass.
- **The consumer must add:**
  - The implicit-surface filter.
  - `HdDependencyForwardingSceneIndex`: without it, dependency-declared dirties are lost, so editing a cube's `size` after conversion to a mesh never dirties `points`.
  - `HdSiExtComputationPrimvarPruningSceneIndex`, needed to read skinned points.
  - Optionally NURBS approximation, material primvar transfer, and `HdsiPrimTypeNoticeBatchingSceneIndex` for Phase 2.
- The notice batching inside the chain is off until `SetBatchingEnabled(true)`, so the bridge's `Flush()` does nothing.
- `UsdImagingCreateSceneIndices` always appends every UsdImaging scene-index plugin Blender registers, with no opt-out. On `dev` it is deprecated in favour of `UsdImagingSceneIndex`; the prototype targets the v26.03 API.

### Data the chain exposes, and where it differs from direct USD

- **Meshes and primvars.**
  - Subdivision scheme, holes, creases, orientation, and doubleSided pass through unchanged.
  - Indexed primvars keep their values and `indices` separately (`HdPrimvarSchema::GetIndexedPrimvarValue`/`GetIndices`). The plain `GetPrimvarValue` de-indexes silently and substitutes defaults for bad indices.
  - Only authored primvars appear; there is no displayColor fallback.
- **GeomSubsets.** Each subset is a child `geomSubset` prim carrying only its element type and indices. **`familyName` is not exposed, and every family appears.** Subsets resolve material bindings like any prim.
- **Implicit surfaces.**
  - **There is no approximation signal.** The prim's type becomes `mesh`.
  - Cube and plane are exact.
  - Sphere, cone, cylinder, and capsule become coarse catmullClark cages with hard-coded tessellation (10 segments, sphere 10×10).
  - doubleSided is forced to false, except Plane, which keeps its own (Phase C: the filter passes Plane's through and loses a Cube's authored true).
  - The original USD type stays readable (`__usdPrimInfo`), so the diagnostic can be derived from it.
  - NURBS approximation produces the control hull.
- **Native instancing.**
  - Instancers sit at generated paths (`…/UsdNiPropagatedPrototypes/<hash>/__Prototype_N/UsdNiInstancer`). They carry `instanceIndices`, a visibility mask, instance transforms, and `instanceLocations` (instance-root paths, in positional order, so not durable).
  - Instances split into separate instancers by differing flattened material bindings, purpose, draw mode, assetInfo, skel binding, or the set of constant-primvar names.
  - **Instances that differ only in primvar values share an instancer**, with per-instance primvars. Nothing encodes whether an instance's primvar or the prototype's own primvar wins.
- **Reverse mapping.** `HdxPrimOriginInfo` (`hdx/pickTask.cpp`) decodes (instancer, instance index) into the USD instance-proxy path, using only the terminal scene index:
  - It walks `instancedBy` upward; the innermost level varies fastest.
  - It folds in `instanceLocations` and `primOrigin` at each level.
  - Point instancers have no `instanceLocations`, so their identity is (instancer path, point index).
  - The symbols are exported by Blender 5.2.2. The nested-context case is inferred from code and needs a fixture.
- **Materials.**
  - Networks are exposed as nodes, parameters, connections, and terminals per render context. `HdMaterialSchema::GetMaterialNetwork` falls back to the universal context, where UsdPreviewSurface lives.
  - Collection-based bindings are evaluated on Hydra paths, so **they miss prims inside instances** (marked XXX in the source).
  - **A purpose-specific binding does not fall back to allPurpose.**
- **Skinning** is resolved in the chain by default, by a CPU ext computation. Deformed points are readable only after adding ext-computation pruning. Whether the points are correct is unverified (Phase D: correct for one linear-blend skin).
- **Not imaged:** `UsdGeomVisibilityAPI` (purpose visibility), HermiteCurves, and computed extents.
- **Lifetime.**
  - `UsdImagingStageSceneIndex` holds a strong stage reference. To honour the caller-release contract, the core must call `SetStage(nullptr)` on release.
  - The flattening cache keeps every queried prim for the life of the chain.

### Change tracking and time

- Notices are synchronous, single-threaded, and delivered in registration order.
- A dirty notice covers child locators, not child prims. Flattening adds descendant dirties only for descendants whose data was pulled before.
- A resync arrives as Added on existing paths, plus Removed for paths that are gone.
- `SetTime` dirties exactly the locators that were flagged time-varying (from `ValueMightBeTimeVarying`), and only on data sources already pulled. Flags are never cleared, so dirties also arrive for removed paths and unchanged values.
- Mesh orientation, scheme, doubleSided, and subdivision tags are not flagged time-varying, so `SetTime` never dirties them.
- Data-source handles read the stage and current time live, so a handle is not a snapshot. Values must be copied out. The xform combiner caches its value at offset 0 and goes stale across `SetTime`.
- At `UsdTimeCode::Default()`, attribute data sources read authored default values. The stage scene index starts at numeric time 0.0.

### Threading and errors

- `GetPrim`, `GetChildPrimPaths`, and data-source reads are threadsafe by contract, and Hydra's own sync reads in parallel. Observers and notices are not threadsafe.
- Reads must not overlap `SetTime`, `ApplyPendingUpdates`, or stage edits. A parallel read pass (`WorkParallelForEach`, with the GIL released) between mutations is the expected pattern.
- No fatal asserts were found in the core files checked. Missing or wrong-typed fields come back null, and UsdImaging attribute reads fall back to `T{}`, so missing and empty look the same.
- Nothing validates topology at the scene-index level. No delegate checks face-vertex indices against the point count, and Storm and HdPrman index arrays with negative subset indices unchecked.
- Reusable validators: `PxOsdMeshTopology::Validate`, `HdMeshUtil`, `Hd_VertexAdjacency`.
- **Errors from a `PXR_BOOST_PYTHON_MODULE` module go to stderr, not Python.** Every entry point needs a `TfErrorMark` that converts errors to exceptions.
- Still able to crash: `TF_FATAL_ERROR`/`TF_AXIOM`, null data sources, unchecked `VtArray` indexing, overflow, deep recursion, and exceptions in `noexcept` code.

### Native build and boundary

- **Windows:**
  - `lib-windows_x64` at the v5.2.2 pin has `usd_ms.lib`, the headers, `tbb12.lib`, and `python313.lib`. The bpy wheel has no import library or headers.
  - `blender.exe` and the wheel's `bpy/__init__.pyd` both import `usd_ms.dll`, so USD is loaded before extension code runs. Blender's own `pxr/*.pyd` rely on Windows reusing that loaded copy, and ours would too (inferred).
  - Constraints: MSVC toolset ≤ 14.44, `/MD`, Release only, USD's MSVC flags, and TBB's lib dir for auto-linking.
- **Linux:**
  - `libusd_ms.so` has SONAME `libusd_ms.so`, uses the libstdc++ new ABI, was built with GCC 14 on Rocky 8, and needs at most GLIBC_2.27.
  - Its Python symbols are undefined; the host provides them.
  - Build in `manylinux_2_28` with hidden visibility, no RUNPATH, and no libpython.
- **macOS:**
  - The bridge was built for minimum macOS 26.0, but Blender 5.2's floor is 11.2 (*measured*). It needs `CMAKE_OSX_DEPLOYMENT_TARGET=11.2`.
  - It omits `PXR_BOOST_PYTHON_NO_PY_SIGNATURES`, which Blender's exported targets set.
- **Zero-copy transfer** (*measured*, macOS wheel):
  - `Vt` arrays support the buffer protocol in v26.03: read-only and O(1), and the view keeps the data alive.
  - `memoryview(a).cast('B').cast('f')` passed to `mesh.attributes['position'].data.foreach_set('vector', …)` took 0.22 ms for 1M points, against 31.5 ms through `mesh.vertices.foreach_set('co', …)`.
  - Blender rejects 2-D views. Element types must match Blender's exactly (`'f'`, `'i'`, `'?'`), or it silently falls back to a slow per-item path.
- **Packaging:**
  - `--split-platforms` filters only `wheels`; loose `.so`/`.pyd` files go into every zip.
  - Build one zip per platform on that platform's runner, with `platforms = ["<one>"]`.
- **Converters are process-global and modules never unload.** Bound C++ types need a per-build namespace, or an in-session update reuses the old converter.

The full reports are in [M01b-research/](M01b-research/README.md); this section is their digest. The zero-copy measurement is reproducible with the `buffer_transfer` feasibility probe.

## Phase 0 — Gating questions (settled)

- **Official extensions platform:** settled. Proscenium is not listed on extensions.blender.org, so its no-compiled-code rule does not apply.
- **Release cadence:** settled with the user (2026-10-09). A rebuild and new release for every Blender minor version that changes USD is acceptable (5.3 already does).
- **Distribution channel** (GitHub releases, a self-hosted extension repository, or both): not gating. It is chosen in Phase F if Hydra is adopted.

The answers go into DECISIONS.md under "Native core distribution", with the user's agreement.

**Corrections to the milestone's Background**, made in the same change as this plan's first phase:

- Inherited state comes from the flattening inside `UsdImagingCreateSceneIndices`, not from the bridge's pass.
- The implicit-surface filter gives no approximation signal.
- Add the version-lock risk.

## Phase A — Native loading on three platforms

Goal: the milestone's "Cross-platform native loading" deliverable and its first test.

- **Fix the macOS bridge:**
  - Set the deployment target to 11.2 and add `PXR_BOOST_PYTHON_NO_PY_SIGNATURES`.
  - Wrap entry points in `TfErrorMark`.
  - Hold the stage weakly, with an explicit release that calls `SetStage(nullptr)`.
  - Remove the redundant flattening pass and the no-op `Flush()`.
- **Generalize the CMake build** to Windows (pinned toolset, `/MD`, `usd_ms.lib` and `tbb12.lib` from the pinned lib repo) and Linux (`manylinux_2_28`, linking the wheel's `libusd_ms.so`). Dependency headers come from each platform's `lib-*` repo at the v5.2.2 pin, as macOS does today.
- **Extend the runtime checks** to all platforms. The exactly-one-USD check:
  - enumerates loaded images (`dyld`, `dl_iterate_phdr`, `EnumProcessModules`);
  - checks which library provides a USD symbol;
  - checks `pxr.__file__`;
  - checks that `usd-core` is absent.

  On Windows, check that `usd_ms.dll` is loaded before importing the module.
- **Run on GitHub Actions** through the feasibility workflow, in both the wheel and the binary, and record per-platform results in the [feasibility record](../feasibility/runtime-record.md).
  - The record's Windows and Linux sections for M1's own probes are still pending. Fill them in from the same workflow runs, since M1b relies on that CI path.

**Exit:** loading recorded for all three platforms, or a recorded blocker.

### Phase A log

Branch `m01b-phase-a`, off `main`. Each later phase branches off the previous one.

- **Status (2026-10-10): complete.** Native loading holds on all three platforms. The "Hydra bridge" workflow passes every job: 36 checks per host on macOS and Linux, and 37 on Windows, with the release check and the direct CMake build (run 38040274107). The Feasibility workflow then filled in M1's pending Windows and Linux results: 55 checks pass in all three runtimes on both. Everything is in the feasibility record.
- **Findings for later milestones**, recorded there and not acted on here:
  - On Windows, a non-forced `Reload()` misses a rewrite within the same second, because USD's Windows file timestamps have whole-second resolution (M3, file-backed refresh).
  - The Windows bpy wheel omits six USD plugins' resources, because of a Blender install rule. There, any Sdr lookup of UsdPreviewSurface raises a Tf error (M9 tests).
- **Phase B/C watch item:** the bridge raises posted Tf errors as exceptions. A capture that triggers Sdr discovery would therefore fail in the Windows wheel, which is a test-environment artifact, not user-facing behaviour. If it happens, the prototype's Windows wheel tests need to account for it.
- **One release pin: `uv.lock`'s bpy version.** `tools/blender_release.py` reads it. `setup-blender` downloads that Blender binary, and `prepare_deps.py` derives the lib-repo revisions from the release's git tag (its `lib/` submodules), caching them per tag. `build.py` checks the installed wheel's version from its metadata, and the probe checks each host's `bpy.app.build_hash` against the tag's commit. Headers, link input, test wheel, and test binary therefore come from one release, and the bpy pin is tightened to `~=5.2.0` so moving to 5.3 (USD 26.08) is a deliberate edit.
- **Link input from the bpy wheel on macOS and Linux.** It is already in the uv environment, and only its install name or SONAME ends up in the module. Windows needs an import library, which only the lib repo has.
- **Linux built in `manylinux_2_28`, tested on `ubuntu-latest`.** Building on a current distribution could raise the required glibc above Blender's floor; the audit checks the symbol versions.
- **CMake directly, no wheel.** `build.py` runs CMake and Ninja from the dev group (Release, the uv interpreter's SOABI) and takes the module from a temporary install. Product builds will also need the module itself: wheels unpack into the site-packages that all extensions share, so the module ships inside the extension package (research §6).
- **Windows loads the pinned toolset itself.** `build.py` finds Visual Studio with Microsoft's `vswhere` and loads the 14.44 environment with `vcvarsall -vcvars_ver=14.44`, so neither CI nor a local build needs a third-party action or a developer prompt. It uses the Ninja generator so that toolset is the one that compiles, and the audit rejects a newer linker.
- **`release()` is explicit.** The chain's strong stage reference is a fact of `UsdImagingStageSceneIndex`. The probe records both sides: the stage stays alive before release and expires after it.
- **A separate workflow** (`hydra-bridge.yml`), not pull-request CI: the bridge is not production code. It runs by hand, or on a push to an `m01b-*` branch that touches the bridge, since manual dispatch only works once the file is on the default branch.
- **The record's error claim is narrow.** Only a `None` stage is tested. Tf-error conversion is wired in, but posting a real Tf error is left to Phase C's malformed-input cases.

## Phase B — Prototype: capture, plan, transfer

The prototype extends `tools/feasibility/hydra_bridge/` (suggested; it stays feasibility code, not `src/`). It is a thin vertical slice, not a design for M5/M6.

- **Chain** (suggested order, built explicitly in C++ rather than through renderer plugin registration):
  1. `UsdImagingCreateSceneIndices` (draw mode off)
  2. ext-computation pruning
  3. implicit surfaces → mesh
  4. dependency forwarding
  5. prim-type notice batching
- **Capture** at an explicit numeric time code:
  - `SetTime`, `ApplyPendingUpdates`, then one parallel read pass with the GIL released.
  - Values are copied into an immutable snapshot (`VtArray`s are copy-on-write, so the snapshot can hold them without a deep copy).
  - Every read is guarded: null data sources, types, sizes.
  - Source identity comes from the composed stage: Hydra paths map back through `primOrigin`, `instancedBy`, and `instanceLocations`, as `HdxPrimOriginInfo` does. Hydra paths and instance indices are never source identities.
- **Planning in C++:**
  - A minimal display plan: meshes with material-slot subsets, instance groups, placeholders, and diagnostics.
  - Geometry is validated before anything reaches Blender: point and face-vertex counts, index bounds, primvar lengths per interpolation, and subset bounds. `PxOsdMeshTopology::Validate` can be reused.
  - Tf warnings and errors raised during capture become diagnostics.
- **Transfer and application in Python:** plan arrays are exposed through the buffer protocol in Blender's exact element types, and applied with `foreach_set` on attribute data, with no Python-side copies.

### Phase B log

Branch `m01b-phase-b`, off `m01b-phase-a`.

- **Status (2026-10-12): slice built and passing on all three platforms.** `prototype.usda` runs capture → C++ plan → Blender. 20 prototype checks and the loading checks (41, or 42 on Windows) pass in the wheel and the binary on macOS, Linux and Windows ("Hydra bridge" workflow, [run 38293887802](https://github.com/scottdmilner/proscenium/actions/runs/38293887802)). Each prototype check takes its expected value from USD (`UsdGeom`, `UsdShade`) or from how the scene is built. Results are in the [feasibility record](../feasibility/runtime-record.md#prototype-slice-m1b-phase-b).
- **C++17 sources in `src/`, one file per stage:**
  - `scene_index_graph`: the scene-index graph and its observer.
  - `capture`: produces the immutable `snapshot`.
  - `instancing`: reverse mapping.
  - `validate`, `mesh_builder` and `planner`: produce the `plan`.
  - `python_views` and `module`: the Python bindings.
  - `diagnostics`, `loaded_images` and `bridge`.

  `src/README.md` describes the data flow, the files, the Python API and the conventions.

  The bridge's own code builds with `-Wall -Wextra -Wpedantic` (`/W4` on MSVC); USD's headers are system includes.
- **Scene-index graph in the plan's order.** Prim-type notice batching is the terminal, and capture flushes it each time: the scene is empty until the first flush, and notices wait for each one. All prim types share one batching priority, because capture re-reads every prim rather than applying notices. Materials first might suit a Phase 2 consumer that applies notices incrementally, but that is untested and undecided.
- **Draw mode off** (`addDrawModeSceneIndex = false`), carried over from the M1 bridge.
  - With it on, `UsdImagingDrawModeSceneIndex` would replace a model's subtree with generated stand-ins: a bounds box, origin axes, or cards with Storm-only glslfx materials. Capture would then never see the source meshes, subsets, primvars, or bindings, and the spec puts generated simplified proxies out of scope.
  - The `geomModel` data still reaches each prim, and it still splits instancers. The planner can therefore read it if Proscenium later honors `model:drawMode`, which [Deferred and Out of Scope](../spec/support/visibility.md#deferred-and-out-of-scope) notes as a logical future step.
  - From source reading; not tested.
- **Capture takes a numeric time, default time, or a `Usd.TimeCode`.** `capture()` and `capture(None)` mean default time.
  - At default time animated values read their authored defaults, so animation needs numeric times.
  - The Phase A checks now run mostly at time 1, the fixture's first points sample. Two were renamed, and "snapshot outlives its bridge" was added.
  - Default time has four checks. One reads the authored default value after the time-1 sample has been edited. The others cover the time reported at default time, the `None` and `Usd.TimeCode` arguments, and a rejected non-time argument.
- **Tf errors and warnings during capture become diagnostics.**
  - Each prim read opens its own `TfErrorMark`, so errors are attributed to the prim being read.
  - Warnings go to a `TfDiagnosticMgr` delegate, which attributes them through a thread-local current prim.
  - Constructing the bridge still raises.
  - This changes the Phase A watch item: an Sdr error in the Windows wheel should now appear as a diagnostic instead of failing the capture (to be seen on CI).
- **No GIL during the chain update, the parallel read pass (`WorkParallelForN`), or planning.**
- **Prototype simplifications, each weighed in Phase C** (the first two and the last are superseded there: bindings are resolved per destination purpose, only the materialBind family makes slots, and normals are transferred):
  - Material bindings use `allPurpose` only. The spec leaves purpose selection open (M9).
  - Every face-set GeomSubset becomes a material slot through its binding, because `familyName` is not exposed. Where subsets overlap, the first keeps the face and a diagnostic is raised.
  - Point instancers get a diagnostic and are not translated. The milestone's cases are native instances.
  - Normals and value types other than float, float2, float3 and int are not transferred, with an info diagnostic.
- **Constant primvars travel per object, not on the shared mesh.** A primvar on the prim itself, of any interpolation, shadows an inherited per-instance value, and an inner instance root's value beats an outer one's, as in USD inheritance. Varying primvars become attributes on Blender's domains, with indexed values expanded in C++. Left-handed faces are reversed, keeping their first corner.
- **The snapshot is built with Hydra's own tools.** It is an `HdRetainedSceneIndex` of `HdMakeStaticCopy` copies of only the schemas planning reads (`PlannedSchemas()`), one retained container per prim. Planning reads its records from it (`prim_reader`), so null checks stay in one place. `snapshot.dump(path)` prints a prim's copy through `HdDebugPrintDataSource`.
  - **Not a complete copy** (settled with the user, 2026-10-12). The [spec](../spec/pipeline.md#evaluated-source-snapshot) requires values captured before planning and unchanged during it, and says the separation "does not require copying all scene data". An editor authors through the USD stage, not the snapshot.
  - **Why not complete:**
    - A full copy was tried first. `HdMakeStaticCopy` dropped `ArResolverContext` under `system/assetResolution` on `/` and every instance root, each with a Tf error, because the type is outside its typed dispatch.
    - Keeping that value needed a custom copy. Recognising the type then hit a **boundary finding**: `VtValue::IsHolding<ArResolverContext>()` is false in this module. For types outside Vt's known value types it compares `type_info` objects, and our hidden-visibility module has its own typeinfo for USD classes that aren't exported. Any production type check across the boundary needs the same care.
    - A full copy also pulls every data source, so `SetTime` dirties everything.
  - **Precedent:** neither usdview (OpenUSD `dev` 5bc38c9) nor the Maya Hydra viewport (maya-hydra 6de1e2c, maya-usd 48eae12) freezes a scene index.
    - Both read live and keep their own converted per-prim state, refreshed on dirty notices.
    - `HdMakeStaticCopy` has two production callers, both for narrow subtrees: a material prim, and the instance-aggregation key entries.
    - maya-hydra stores light parameters it can't type in the untyped `HdRetainedSampledDataSource`.
  - **For Phase C's incremental refresh:**
    - Re-copy only the prims named in notices and reuse the other prims' retained handles. Retained containers never change, so earlier snapshots stay intact.
    - `HdsiComputeSceneIndexDiffDelta` compares handles, not values, so it only lists the re-copied prims. The oracle for incremental capture is therefore a full re-read compared record by record.
  - **For Phase D:** the copy keeps one sample per value, at shutter offset 0, so a snapshot is one time code. Several frames mean several captures.
- **Source identity: `HdxPrimOriginInfo` measured against our frame mapping.**
  - For the comparison, a temporary `build_plan` mode took sources and instance contexts from Hydra's picking reverse mapping, `HdxPrimOriginInfo::FromPickHits` on the snapshot, instead of `Frame::Map`. Transforms, visibility and inherited primvars still came from the frames, because Hydra has no consumer-side helper for them.
  - The two agreed on every source and context in `prototype.usda`, and at every benchmark size.
  - **Benchmark** (*measured*, with a since-removed script; bpy wheel, Apple M1 Max, minimum of 5 runs, one machine). Each "branch" draws ten leaf meshes two instancing levels deep:

    | Branches | Objects | Capture | `build_plan`, frames | `build_plan`, `HdxPrimOriginInfo` |
    |---|---|---|---|---|
    | 10 | 100 | 0.43 ms | 0.07 ms | 0.17 ms |
    | 100 | 1,000 | 1.3 ms | 0.46 ms | 1.8 ms |
    | 1,000 | 10,000 | 6.1 ms | 4.8 ms | 54 ms |
    | 5,000 | 50,000 | 32 ms | 25 ms | 1,330 ms |

  - **Cause: a quadratic cost in v26.03.** `_FromPickHitWithCache` (`hdx/pickTask.cpp:1182,1194`) copies the cached instancer info into a local, then indexes it with non-const `VtArray::operator[]`. That detaches the shared arrays, copying every instance location on every hit.
    - OpenUSD `dev` (5bc38c9) reads them with `cdata()` and a comment saying why. It isn't in `dev`'s CHANGELOG, so the release that ships the fix is unknown.
  - **Decision (with the user, 2026-10-12): identity stays on the frame mapping.** The `HdxPrimOriginInfo` mode, its agreement check and the benchmark were removed.
  - **Switch to `HdxPrimOriginInfo` once the USD Blender bundles has the `cdata()` fix.** Re-run the comparison first, checking that the two agree and that it scales linearly. Point-instancer identity, which `HdxPrimOriginInfo` handles and we don't, would come with the switch. A note in `src/instancing.h` points here.
- **USD's own helpers where it has them.** Capture uses:
  - `HdSceneIndexPrimView` for the traversal, instead of a hand-written stack.

  Reading the records then uses:
  - `HdPrimvarSchema::IsIndexed` and `GetIndexedPrimvarValue` for primvar values and indices;
  - `HdDataSourceMaterialNetworkInterface`, the interface Hydra's own material filters use, for networks;
  - `VtArray<SdfPath>` as Hydra hands it out.

  Mesh topology is held as a `PxOsdMeshTopology`, and validation starts with `PxOsdMeshTopology::Validate`. Its checks cover corner counts, negative indices, the index count, hole indices, and the scheme and orientation tokens. The bridge adds only what USD can't check without the points: indices below the point count, and counts within Blender's `int`.

  `Validate` rejects USD's `"none"` scheme (no subdivision), because it accepts only OpenSubdiv's refinement schemes. Such meshes therefore validate as bilinear, since none of the other checks depend on the scheme. An ad hoc run confirmed the validator's messages for a two-corner face, a negative index, an index-count mismatch, a bad scheme, and an out-of-range index. Phase C's malformed-input fixtures will make these checks permanent.
- **Application** (`apply.py`) sets `position`, `.corner_vert`, `polygons.loop_start`, `material_index`, and each attribute through flat `memoryview` casts of the Vt arrays. `flat()` rejects a format that doesn't match Blender's, rather than letting `foreach_set` fall back to reading items one at a time. Edges come from `mesh.update(calc_edges=True)`.

## Phase C — Prototype correctness

Each case gets a `.usda` scene with a purpose comment. Expected values come from how the scene is built or from direct USD (`UsdGeom` transforms, visibility, and primvars), never from Hydra's output.

| Milestone case | What the check establishes | Known risk from research |
|---|---|---|
| Mesh with GeomSubsets and indexed primvars | Indices kept, subsets mapped to material slots, faces in no subset covered | `familyName` missing: non-material families can't be told apart |
| Implicit shape → mesh | Mesh produced; approximation diagnostic for inexact shapes (from the original type), none for cube | No native signal; fixed, coarse tessellation |
| Nested native instances, differing inherited appearance | Every instance's world transform, visibility, material, and primvar matches UsdGeom; instance context recovered for each level | Primvar-only differences share an instancer, with unspecified precedence; nested mapping inferred |
| Time-code change, material parameter edit, unchanged refresh | Values match at each time; the edit is visible after refresh; an unchanged refresh changes nothing | Dirties over-report; a held handle goes stale |
| Untranslated type (basis curves) | Placeholder plus diagnostic | — |
| Large arrays to Blender | No Python-side copy; Blender data matches | Format mismatch falls back silently to the slow path |
| Malformed input | Out-of-range indices, wrong primvar lengths, and negative subset indices raise Python exceptions or diagnostics, never crash | Hydra does not validate |

Also checked, because research found them and the spec requires them: collection-based bindings on prims inside instances, purpose-specific bindings without an allPurpose fallback, and `UsdGeomVisibilityAPI`. Each either has a workaround in the core or is recorded as a gap the decision weighs.

### Phase C log

Branch `m01b-phase-c`, off `m01b-phase-b`.

- **Status (2026-10-13): all ten cases pass on macOS arm64, Windows x64 and Linux x64, in the wheel and the binary** ("Hydra bridge" workflow, [run 38359009667](https://github.com/scottdmilner/proscenium/actions/runs/38359009667)). That is 118 correctness checks per host, with the same count per case everywhere; the loading (42, 43 on Windows) and prototype (20) checks also pass. The run's Windows build had two `/W4` warnings, fixed since, with clang flags that now report them on macOS; the next run ([run 38361588537](https://github.com/scottdmilner/proscenium/actions/runs/38361588537)) builds without warnings on every platform. In that run a single-sample timing check failed in the macOS binary (4.8× against the 5× asked for); it now takes the minimum of five runs per path, and every job then passes ([run 38362866907](https://github.com/scottdmilner/proscenium/actions/runs/38362866907), commit `679566c`). Results are in the [feasibility record](../feasibility/runtime-record.md#prototype-correctness-m1b-phase-c).
- **Layout.** `correctness_probe.py` runs each case in `cases/`: one `.usda` scene with a purpose comment and one check module per case. A failing case is recorded and the others still run. `run.py` runs it in both hosts beside the other probes.
  - Scene values come from `cases/oracle.py` (UsdGeom, UsdShade) or the scene's construction. The prototype probe shares that module.
  - Application, and incremental capture, are checked against the plan or a full capture; the edits case also checks each step against USD and a new bridge.
  - **Known gaps are checks too.** `known_gap` asserts that each gap still reproduces, so the record can't go stale silently.
  - The cases are the seven milestone cases, plus bindings (the research risks), purposes (destinations), and primvars (what becomes Blender data besides varying attributes; added with the user).
- **Audit (2026-10-12).** Four subagents reviewed the cases before the result above:
  - three covered the code and tests (geometry; instancing and materials; time, untranslated types and infrastructure);
  - one checked these docs against the checks.

  They found real bugs, all now fixed and covered:
  - **Frozen source-info values.** The filter's containers held values fixed when built. A downstream scene index keeps input containers between notices, so animated or edited HermiteCurves kept their first-read transform and visibility, even on a new bridge.
  - **Missed notices.** Edits to a `familyName`, an authored guideVisibility, or `doubleSided` sent no notice at all.
  - **Visibility.** An invisible ancestor of an instance root was ignored. A guide whose nearest opinion is `inherited` counted as visible, and the oracle shared that mistake.
  - **Binding detection.** The binding workaround's "authored binding" test was fooled by a collection that doesn't include the prim, and by an empty binding.
  - **Collections inside assets.** A collection authored inside an instanced asset was lost in every instance.
  - **Point instancers.** Their prototypes became stray placeholders.
  - **Primvars.**
    - Indexed constant primvars were dropped.
    - Per-instance primvars of several types were dropped, and scalars came back as one-element arrays.
    - A primvar named after a Blender built-in (`sharp_face`) changed shading.
  - **Faces.** A face using a point twice, or two faces with the same points, reached Blender, which `Mesh.validate()` would change.
  - **Application and reporting.**
    - Empty and points-only meshes crashed application.
    - Overlapping subsets depended on Hydra's child order.
    - Point-element subsets and unapplied subdivision had no diagnostic.
    - The loading probe's expiry check was flaky.

  They also found checks that could pass vacuously, and these docs overstating several results; both are corrected. Remaining holes are listed in the record's limits.
- **Source-info filter** (`src/source_info_scene_index.*`), the core's one addition to the graph. It sits in `UsdImagingCreateSceneIndices`' overrides slot, right after the stage scene index, where paths are still USD paths (prototypes included). Under a `prosceniumSource` container it supplies what the chain drops:
  - subset `familyName`;
  - authored purpose visibility;
  - `doubleSided`;
  - UsdShade's resolved binding per material purpose, and the purposes a prim binds `strongerThanDescendants`;
  - USD's verdict on a mesh's materialBind family (`UsdGeomSubset::ValidateFamily`);
  - for prims Hydra doesn't image, their USD type;
  - on gprims and point instancers, the authored attributes UsdImaging drops (below).

  More about the filter:
  - **Unimaged prims.** For prims UsdImaging doesn't image at all (no `__usdPrimInfo`, such as HermiteCurves), it supplies `UsdImagingDataSourcePrim`: transform, visibility, purpose, authored extent and primvars, which is what UsdImaging gives any prim it has no adapter for. Flattening applies them, and inheritance works as in UsdImaging.
    - **Time.** Those data sources run on the filter's own `UsdImagingDataSourceStageGlobals` subclass. It gives them the graph's time and records what they flag as time-varying, so `SetTime` dirties exactly that, as `UsdImagingStageSceneIndex::SetTime` does (measured: an animated HermiteCurves is dirtied for `xform` and `visibility`, a static one not at all).
    - **Edits.** An edit to such a prim is dirtied for the locators `UsdImagingDataSourcePrim::Invalidate` gives.
    - **History.** Earlier versions hand-built these schemas. The first supplied a visible `true` for every typeless prim, Xforms and Scopes included, which hid an invisible ancestor's visibility from everything below (found in the Hydra-native review, below). The hand-built transform, visibility, purpose and time-variance code is gone.
  - **Extents.** For a point-based prim Hydra gives no extent and doesn't draw as a mesh (curves, points, HermiteCurves), it supplies USD's computed extent (`UsdGeomBoundable::ComputeExtentFromPlugins`), so its placeholder shows bounds. Point instancers and volumes are left out: their extents would mean evaluating prototypes or reading field files merely for a placeholder.
  - **Freshness.** Its containers read USD at the graph's time when first accessed. Its containers are cached per prim and rebuilt only when that prim, or something its facts depend on, changes: an edit to it, an ancestor's binding or any collection (every prim's bindings), or one of a mesh's subsets (its family verdict). Resyncs rebuild everything when next read. Measured with a temporary counter: one build per prim on the instances scene (56 for 55, all while the bridge is built), none on later captures, 4 per time change on the edits scene (its animated prims) and none at release; the previous single generation counter built 366 times for 55 prims in the first capture alone, and rebuilt every prim after any notice.
  - **Edits Hydra misses.** It listens to `UsdNotice::ObjectsChanged`, and when the graph advances it dirties the prims whose source facts changed.
  - **Prototypes.** Propagation carries all of this into every prototype copy.
- **Results by case** (details and numbers in the record):

  | Case | Result | Gap found, and the workaround |
  |---|---|---|
  | GeomSubsets and indexed primvars | Pass | Hydra binds a subset of any family, including one with no `familyName`; only materialBind subsets make slots, by the filter's family. |
  | Implicit shapes | Pass | Hydra loses a Cube's authored `doubleSided = true`; the filter supplies USD's value. The NURBS patch is displayed as its control hull, which is accepted (diagnosed as an approximation). **Correction to research:** Hydra keeps Plane's `doubleSided`, so it isn't always forced to false. |
  | Nested instances | Pass, 360 copies three levels deep | **A Hydra propagation bug** (below). |
  | Time, edits, incremental capture | Pass, against USD, a new bridge and full captures | Notices over-report, but no step missed a change once the filter listened to the stage. |
  | Untranslated types | Pass | HermiteCurves aren't imaged at all (from source reading and snapshot inspection); the filter supplies their type, transform, visibility and purpose. Point instancers get one placeholder each. |
  | Large arrays | Pass | Blender copies face offsets: `polygons.foreach_set('loop_start')` allocates a temporary of 4 bytes per face. Every other transfer allocates no Python memory beyond about 1 KiB (`tracemalloc`; Blender's own allocator isn't measured). |
  | Malformed input | Pass: errors and diagnostics, no crash, nothing `Mesh.validate()` would change reaches Blender; faces it would delete are left out with a warning | A wrong-typed attribute arrives empty, so the message describes missing points, not a type error. |
  | Bindings and purpose visibility | Pass, except two collection gaps | Collection bindings that name instance-proxy paths are missed; **no workaround** (below). Purpose visibility needs the filter. |
  | Normals, velocities, constant primvars, custom attributes | Pass | UsdImaging passes only primvars and schema attributes; the filter lists the attributes it drops, so they can be warned (below). |
  | Prim and material purposes per destination | Pass | The Phase B application ignored prim purpose. Hydra resolves each purpose separately but the nested binding bug makes its values unusable inside instances, so the core resolves each destination itself (below). |

- **Primvars beyond varying attributes** (settled with the user, 2026-10-12). Phase B skipped normals, and authored constant primvars only as `displayColor`.
  - **Normals are Blender's custom normals.** Blender 5.2 keeps custom normals as a `custom_normal` float-vector attribute on points, faces or corners, so authored normals go to the domain of their interpolation through the same zero-copy transfer as other attributes. Indexed normals are expanded in C++, and `primvars:normals` wins over the `normals` attribute (UsdImaging's choice, checked against UsdGeom's rule). On a left-handed mesh each reversed corner keeps its own normal.
    - Blender stores the vectors as given: an ad hoc wheel test read back a zero and a length-2 normal unchanged. The fixtures' normals are unit length; non-unit authored normals are untested in rendering.
    - A subdivision surface's authored normals are ignored with an `ignored-normals` diagnostic, as UsdGeomMesh specifies. The prototype displays the cage, so they would apply to flat faces they weren't authored for.
  - **Velocities are Blender's `velocity`.** `accelerations` stay a generic attribute with a `no-blender-equivalent` warning, since Blender has no acceleration attribute. A primvar named `velocity` keeps the name, and `velocities` are then skipped with a `name-collision` warning. Whether Blender's velocity attribute expects USD's units (per second) is unchecked.
  - **Constant primvars are ID properties on each object**, named as the primvar, so an Attribute node of type Object can read them. They follow the existing inheritance: the prim's own, then its instance roots' that it doesn't shadow. The plan converts them to what ID properties hold:
    - bool, int and float scalars (USD's narrower and wider types widened or narrowed to Blender's), strings and tokens;
    - vectors as arrays; arrays of scalars or strings as lists; arrays of vectors, and matrices, as lists of rows;
    - a one-element array as its element, as constant primvars are conventionally authored (`displayColor = [(r, g, b)]`), which also lets shaders read it as a color.

    Integers outside 32 bits keep their low 32 bits (two's complement wrap), best effort, with a `narrowed-primvar` warning per primvar (Blender's integer properties are 32-bit, measured). Not held, and warned (`untransferred-primvar`): types with no property form (an asset path, quaternions), arrays of matrices, names over 63 bytes, and the `proscenium_` prefix, which the bridge's own properties use. `displayColor` still also sets the object's color.
  - **Dropped custom attributes are warned.** UsdImaging gives Hydra only primvars and attributes its adapters map (measured: `userProp`, `custom float myCustom` and an unprefixed `float3[]` never reach the snapshot). The source-info filter therefore lists, for each gprim and point instancer, the authored attributes with values that no schema of the prim defines and USD doesn't read on its behalf, and the planner warns with `dropped-attribute`. Primvars, transform ops, applied-schema attributes, unauthored declarations, GeomSubset family types and collection settings are left out. The family types were a false positive on the existing scenes, found by scanning them. Adding or removing such an attribute updates the warning on the next capture.
  - **A primvar with a Blender built-in name** (`sharp_face`) is now a warning rather than info, since its data is lost.
- **Code review (2026-10-12).** Ten notes from a review, each checked before changing anything:
  - **Fixed:**
    - The planner resolved both destinations' materials for every copy, so a proxy-only prim's `full` binding became a material nothing displayed. Each destination is now resolved only when the object displays there (a copy in neither keeps the viewport's). `purposes.usda` gains `Unseen`, and a check that every planned material is linked; reverting the fix fails it.
    - The filter's cache lived in containers rebuilt on every `GetPrim`, and one generation counter invalidated every prim on any notice. Now it caches per prim, with dependency invalidation (see Freshness above). That exposed a dependency the counter had hidden: a subset edit changes its mesh's family verdict. An edits step now changes Strip's elementType to point and back; with the parent invalidation removed, the long-lived bridge misses USD's new verdict and the new-bridge check fails.
    - **Faces Blender's `Mesh.validate()` deletes are a best-effort repair, not a placeholder** (settled with the user). A face that uses a point more than once, and a later face on an earlier face's points in either winding, are valid USD that Blender's `validate()` deletes, keeping the first of each duplicate set (measured, including the reversed pair). The planner now does the same repair before Blender: it leaves those faces out with a `faces-left-out` warning, and the rest of the mesh builds. Per-face primvars, face-varying corners and subsets follow the remaining faces, and a subset index naming a left-out face is ignored (`malformed.usda` `DuplicateFace`: face 2 keeps its uniform value and its subset's slot). Every Blender mesh still passes `validate()` unchanged.
    - The check no longer makes one vector per face: it sorts each face in place in one copy of the indices and sorts per-face hashes. Measured (bpy wheel, 1M quads, minimum of 5): the whole plan takes about 120 ms either way, so the old check wasn't measurably slow; the new one avoids a million allocations.
    - `velocities` become `velocity` only per point; on another domain they keep their name.
    - The graph raises at construction if `UsdImagingCreateSceneIndices` never calls the overrides callback, and `Advance` no longer assumes the filter.
  - **Checked and unchanged:**
    - *Reversed-winding duplicate faces* are duplicates to Blender too: `validate()` merges a face with its reverse (measured). `malformed.usda` gains `ReversedDuplicateFace`, now repaired as above.
    - *Custom normals on point and face domains.* Blender 5.2 takes a float-vector `custom_normal` on points, faces and corners (measured), and the primvars case compares `corner_normals` with USD for each, not only the attribute's existence.
    - *Guides under an `inherited` opinion.* `ComputeEffectiveVisibility` returns the nearest authored opinion, `inherited` included (measured: a child authoring `inherited` under a parent authoring `visible` gives `inherited`), and UsdGeomVisibilityAPI makes a guide visible only when its purpose visibility evaluates to `visible`. Render and proxy prims evaluating to `inherited` stay visible. The core already follows this; `purposes.usda`'s InheritedGuide covers it.
    - *Guide in the default viewport purposes.* VIS-03 excludes guides by default and VIS-04 shows explicitly visible ones. Including the guide purpose with the guide rule gives exactly that; the plan settings document it.
    - *Two objects with one source.* By design: a copy shown in both destinations with different materials is two objects sharing a mesh, distinguished by their `viewport` and `render` flags. Their identity is source, instance context and destination, which M5's binding records must carry (the [spec](../spec/lifecycle.md#ownership-and-lifecycle) records representation role separately from source).
- **Nested-instance binding bug** (v26.03, and unchanged in `dev` at `5bc38c9`, from source reading).
  - Every prototype level is re-rooted to the same placeholder path (`UsdImaging_NiPrototypeSceneIndex::GetPrototypePath()`). An inner instance root's binding to a material in the enclosing prototype is therefore re-rooted into the inner prototype.
  - In the fixture, Moss's binding names a prim that doesn't exist, and Bark's names the inner prototype's own Bark instead of Branch's, a different material, **with no diagnostic**. With `strongerThanDescendants` on the inner root, Hydra applies the strength but keeps the broken path.
  - **Workaround: the core doesn't use Hydra's flattened bindings.**
    - The filter records UsdShade's binding per purpose for every imageable prim and subset. Inside a prototype that covers what the prototype authors: collection membership, strength, empty bindings, bindings to non-Materials, and bindings without `MaterialBindingAPI`.
    - `BoundMaterial` adds what lies at or above each instance root: a strong binding there wins; otherwise the prototype's own; otherwise the instance root's own. Then it falls back to allPurpose, as UsdShade does.
    - This replaces two earlier versions that tried to correct Hydra's values. The audit fooled the second with a collection that didn't include the prim, and with an empty binding.
  - **History.** The first version missed strong inner roots (6 copies wrong, found ad hoc). Disabling the strength rule then, ad hoc, failed the check on `BranchE`'s two Blades.
  - **Upstream.** OpenUSD [#1571](https://github.com/PixarAnimationStudios/OpenUSD/issues/1571)'s case (a strong outer binding) is now in the fixture and matches. [#3690](https://github.com/PixarAnimationStudios/OpenUSD/issues/3690) is a different bug (collections, below). No upstream issue was found for the re-rooting; it is worth reporting.
- **Collection bindings that name instance-proxy paths: gaps without a bounded workaround.**
  - **Shapes:** a collection outside the instance that includes one instance's prim, and a collection on the instanced asset's root (`KitA`/`KitB`, the shape of #3690's scene, which has a single instance and also loses its binding through our pipeline, ad hoc).
  - **Why:** a prototype can't see proxy paths. The source suggests Hydra evaluates membership on prototype paths (marked XXX).
  - **What works:** a collection authored below the asset's root, inside the prototype, matches UsdShade through the filter.
  - **Fixing the rest** means evaluating such collections per instance and splitting instances by them, outside Hydra's aggregation. Phase F weighs this.
- **A type-identity finding at the module boundary.**
  - An `SdfPath` value made in the bridge's module isn't recognized by USD's own code: `HdMakeStaticCopy` posts "Unsupported type SdfPath". It is the same boundary as Phase B's `ArResolverContext`, now for a core type.
  - Bound paths therefore travel as tokens, and the core maps them to Hydra paths through the prim's prototype-relative origin.
  - **Rule for production:** values the core gives Hydra must be Vt's own types, and so must per-instance primvar types it recognizes.
- **Sharing, as evidence for M4 and M8.** The nested-instance scene plans 216 meshes for 360 drawn copies, with at most 6 objects sharing one.
  - Hydra splits instancers by binding and purpose, so copies share a Hydra prim only where their instance roots agree.
  - Each leaf mesh's copies share one points buffer, so deduplicating by array identity looks cheap. That it's copy-on-write from the one USD prototype is an inference; the prototype doesn't do it.
  - The [Geometry Sharing](../spec/support/instancing.md#geometry-sharing) requirement can't rest on Hydra's instancers alone.
  - **Counts only.** The leaf meshes are small (at most 9 points), though since Phase D they carry a materialBind subset, indexed face-varying UVs and normals, vertex and uniform primvars and a left-handed mesh, and every copy is checked against USD in Blender. The counts didn't change with that. So this says how Hydra splits copies, not what the 216 meshes cost, or whether identity-based deduplication holds for production meshes and for edits on one copy. Phase E measures sharing at scale.
- **Splitting by binding is Pixar's current policy, and planned to change.** In the AOUSD forum thread [Hydra Prototype and Instances](https://forum.aousd.org/t/hydra-prototype-and-instances/1747) (August 2024), Pixar's Tom C confirms that "currently, instances need to share a material binding". He calls it a "lightweight policy choice": material bindings are among `UsdImagingStageSceneIndex`'s `instanceDataSourceNames`. Pixar plans per-instance bindings on one prototype, via "a new hydra schema and a bit of glue code".
  - That explains the sharing result above.
  - The core doesn't depend on it: materials are resolved for each drawn copy and linked per object. A first version resolved them once per Hydra prim, guarded by a warning, which per-copy resolution made unnecessary.
  - The same thread says `instanceLocations` serve "picking, selection, and collection resolution", not drawing. That matches how the reverse mapping uses them, and may be where a fix for #3690 would resolve collections (an inference).
- **Prim and material purposes per destination** (settled with the user, 2026-10-12).
  - The [spec](../spec/support/visibility.md#visibility-and-purpose) has the viewport show default and proxy prims, and the final render default and render prims, both from one snapshot. Explicitly visible guides display in the viewport (spec row VIS-04, added with the user). The Phase B application ignored purpose.
  - **Settings.** `PlanSettings` (binding settings) gives each destination its prim purposes and its material purpose. The defaults are `{default, proxy, guide}` with preview for the viewport, and `{default, render}` with full for the render. A guide displays only when its nearest guideVisibility opinion is `visible`, so including guides shows only the explicitly visible ones.
  - **Material slots follow subsets, not materials.** Slot 0 is the mesh's binding, then one slot per materialBind subset in name order. One mesh serves both destinations even where they group its faces differently. Each object links its own material to each slot (`link = 'OBJECT'`).
  - **Objects:**
    - A copy that displays in both destinations with the same materials is one object.
    - One whose preview and full materials differ is two objects sharing one mesh.
    - A copy in neither is one hidden object, kept for correspondence.
    - Materials are resolved for each drawn copy.
  - **Material resolution stays the core's, for now.** Correction (Hydra-native review): the graph's `UsdImagingMaterialBindingsResolvingSceneIndex` already resolves every purpose separately, with no allPurpose fallback (measured: `/World/Both` gives preview and full, `/World/Same` allPurpose). Only `HdsiMaterialBindingResolvingSceneIndex`, which the bridge doesn't use, collapses them to one purpose (from source: `GetNames()` returns only its target). What keeps resolution in the core is the nested-instance binding bug and the collection handling inside prototypes, not purposes; once those are fixed upstream, Hydra's per-purpose bindings plus the core's allPurpose fallback would serve both destinations.
  - **Render-time switching isn't needed.** Per-destination objects use Blender's own hide flags.
    - In one ad hoc background-mode test (Blender 5.2.2 binary, Workbench, the blocking `render.render()` operator, still and animation), a `render_init` handler's material swap reached the render and `render_complete` restored it.
    - Interactive F12, cancellation, undo and other engines are untested.
    - Geometry Nodes' Is Viewport node is available as a handler-free switch.
    - Both are left for M4.
  - In ad hoc runs made deliberately wrong (preview materials for the render, or render prims in the viewport), the purposes case failed on the matching check. Which material purpose each destination uses remains M9's choice.
- **Incremental capture** (`capture(time, incremental=True)`).
  - It re-copies the prims that notices since the previous capture named, and shares the rest.
  - On the edits case's 23 steps it equals full captures, record by record and plan by plan, and both equal USD and a new bridge.
  - In an ad hoc mutation run, a bridge made to return its previous snapshot at a step failed these checks there.
  - An unchanged refresh delivers no notices, copies nothing and plans identically.
  - **Over-reporting** is visible: dirtied prims whose records didn't change (paths in the record's findings).
  - **Scope:** one scene, not proof that notices are complete. Phase D's time-variance work and M13 build on it.
- **A lifetime bug from Phase B, fixed.** `Bridge(stage)` took a `UsdStageRefPtr`, and Tf's Python converter for a `TfRefPtr` argument moves ownership from the Python object into C++ (`pxr/base/tf/pyPtrHelpers.h`). Releasing or deleting a bridge therefore destroyed a stage its caller still held.
  - The bridge now takes a `UsdStagePtr` and adds its own strong reference.
  - A new loading check covers it, making 42 loading checks (43 on Windows).
  - Production bindings across this boundary need the same care.
- **Expiry can lag `release()`** (cause not identified).
  - `~UsdStage` releases the root layer synchronously (`usd/stage.cpp`), so it isn't asynchronous teardown inside the stage.
  - In 200 ad hoc iterations, the root layer outlived `release()` in 28. In another ad hoc run, the layer was gone before the bridge's weak stage pointer had expired (1 in 22).
  - The check waits up to 2 s for both and records the wait.
- **Hydra-native review (2026-10-12).** Three subagents checked every bridge fix against OpenUSD v26.03, `dev` (5bc38c9) and maya-hydra for a native equivalent, and whether Blender 5.2.2's `libusd_ms` exports it. Inferences are theirs unless measured.
  - **Adopted:**
    - Point-instancer prototypes are recognized by Hydra's `__usdPrimInfo:piPropagatedPrototypes` marker, and point instancers by their null `instanceLocations` (documented in `HdInstancerTopologySchema`; maya-hydra uses the same test), replacing a path-prefix test.
    - Indexed constant primvars flatten through `UsdGeomPrimvar::ComputeFlattened`, which reports bad indices; Hydra's own flattener substitutes defaults with an unattributed warning.
    - Placeholder bounds use `ComputeExtentFromPlugins` (see the filter).
    - The materialBind family verdict comes from `UsdGeomSubset::ValidateFamily` (a new `invalid-subset-family` warning with USD's reason); the overlap rule itself stays the core's, since nothing native picks a winner (Storm draws an overlapping face in both subsets).
    - Instance-root ancestor visibility comes from Hydra's instancer mask, which is computed from the flattened instance root. The core's ancestor walk only compensated for the filter's visibility bug and is gone.
    - Per-instance primvars come from the instance root's own record, flattened in its namespace with the authored type and shape. Hydra's instance aggregation keeps only an array's first element and takes names and types from the first instance (measured: `[7, 8]` reached copies as `[7]`), so the instancer's arrays are no longer read.
  - **Bugs this found, now fixed and covered:** the filter's visible `true` for typeless prims (an unauthored Xform under an invisible group showed its meshes; `edits.usda` `Hush/Wrap/Quiet`), and truncated per-instance arrays (`instances.usda` `weights`).
  - **Tried and blocked on macOS: a keyless UsdImaging API-schema adapter** (`"apiSchemaName": ""` in plugInfo). The stage scene index runs one on every prim with its real stage globals and asks it to invalidate on property changes, so it would have replaced the filter's laziness, generation cache, time dirtying, notice listener and supplied schemas (via `UsdImagingDataSourcePrim`).
    - Built ad hoc (2026-10-12, macOS wheel; the code is kept outside the repository). The bridge wrote a plugInfo.json naming its module and registered it with `PlugRegistry::RegisterPlugins` before UsdImaging's first use. UsdImaging found the type, loaded the plugin, and then failed with "Cannot manufacture type 'hydra_bridge::SourceInfoAdapter'".
    - **Cause: the type-identity boundary again.** `UsdImagingAdapterRegistry` gets the factory with `TfType::GetFactory<UsdImagingAPISchemaAdapterFactoryBase>()`, a `dynamic_cast` inside `libusd_ms`. That base class is defined inline in its header, so its `type_info` is local to each binary: `libusd_ms` doesn't export it (`nm`), and the bridge's module has its own. The cast can't recognize the bridge's factory.
    - The adapter base class itself is exported, but every factory must derive from the unexported one. So, with Blender 5.2.2's library on macOS, no adapter built outside `libusd_ms` can be manufactured.
    - Linux and Windows compare `type_info` by name, so it may work there (untested). macOS is a required platform, so the filter stays.
    - Hf's plugins (Hydra scene-index plugins, render delegates) avoid this by design. `HfPluginRegistry::Define` passes the factory as a `std::function` through the exported `_SetFactory`, and `libusd_ms` wraps it in its own factory class (`hf/pluginEntry.h:97` gives the reason). Their base classes' `type_info` objects are exported. A scene-index plugin is only a filtering scene index, though, with no access to the stage scene index's globals or property invalidation, so it can't replace the adapter; the bridge already inserts its filter directly.
    - **Rule for a compiled core:** register any Tf-factory type through an exported USD helper like Hf's, never by deriving from a header-only factory base.
    - **Adopted instead: the lighter variant.** The filter stays, but builds UsdImaging's own data sources with a bridge-owned `UsdImagingDataSourceStageGlobals` subclass (see the filter above). That only calls virtual methods and exported constructors, with no cast across the boundary. All checks and the audit reproductions pass as before.
  - **No native equivalent (keep custom):** subset familyName, purpose visibility, a Cube's `doubleSided` (hard-coded false in v26.03 and `dev`), bound paths as tokens (`libusd_ms` doesn't export `SdfPath`'s `type_info`, so `VtValue::IsHolding` can't match a value made in the module), domain maps and left-handed reversal, the face checks, reserved names, diagnostics deduplication, and the incremental-capture design (Hydra's caching scene indices read live values; usdview and maya-hydra re-pull dirty prims the same way).
  - **Upstream state:** `dev` reroots collection path expressions into prototypes, fixing collections authored inside assets in Hydra; the nested re-rooting bug and collections naming instance-proxy paths remain. `HdxPrimOriginInfo`'s quadratic cost is fixed in `dev` (`cdata()`).
  - **Production direction for subdivision:** Blender's Subdivision Surface modifier, as Blender's own USD importer uses; OpenSubdiv's refiner (`PxOsdRefinerFactory`, with Blender's `libosdCPU`) only if baked or loop results are needed.
- **Diagnostics are deduplicated in capture.** Hydra can read a value more than once, posting the same warning each time.
- **Plan records are typed by hand, for the prototype only.** `plan_types.py` describes the plan's records as `TypedDict`s copied from the dicts `python_views.cpp` builds, and `apply.py` is annotated with them. If Hydra is adopted, production code should bind the records as classes with attribute access (`mesh.positions`) and ship stubs for them, so the types can't drift from the bindings. This belongs to M5, where the plan interface becomes the C++/Python boundary.

## Phase D — Time-sampled data detection

Recorded in the feasibility record whatever the decision. Each capture evaluates one time code. For points, transforms, primvars, visibility, and topology, compare what a time change reports against authored samples and against `UsdAttribute::ValueMightBeTimeVarying`, including a static mesh under an animated ancestor. Two signals:

1. The dirty set that `SetTime` emits.
2. Direct USD queries.

Record which values each signal reports and where they disagree, and check the values captured at each time against USD. Skinned points are included if the ext-computation path works.

### Phase D log

Branch `m01b-phase-d`, off `m01b-phase-c`.

- **Status (2026-10-14): passes on all three platforms.** The `animation` case, and the instances case with its richer leaf meshes, pass in the wheel and the binary on macOS, Windows and Linux, with the same findings everywhere: 125 correctness checks per host, plus the loading (42; 43 on Windows) and prototype (20) checks, with no compiler warnings ("Hydra bridge" workflow, [run 38636577232](https://github.com/scottdmilner/proscenium/actions/runs/38636577232), commit `4ae78fb`). Results are in the [feasibility record](../feasibility/runtime-record.md#time-sampled-data-detection-m1b-phase-d).
- **What earlier phases already gave.** Capture took numeric times and recorded dirty locators (Phase B). The edits case checked values at four times, including a static mesh under an animated parent, and measured over-reporting (Phase C). Neither had compared what a time change dirties with the scene's construction.
- **Decision (with the user, 2026-10-13): one time code per capture, no interval query.** `GetContributingSampleTimesForInterval` answers a motion-blur question: which samples reconstruct a value over a shutter window around the current frame. Its header says so, and Blender computes its own motion blur.
  - A first version of this phase queried it over frame ranges and recorded its window semantics (bracketing samples, window ends, false at a zero-width sample frame) as misreports.
  - To make visibility visible to that query, it also added a visibility opinion to the filter.
  - Both, and the `sample_interval` capture option, are removed. The record keeps the query's behaviour as an ad hoc observation.
  - Caching several evaluated frames, when a representation needs it, is a layer above capture.
- **What the case checks instead:**
  - direct USD against the construction, as the oracle;
  - that each time change dirties exactly the varying values, visibility and instance masks included;
  - the plan at each time, from full and incremental captures, against USD, skinned points included.
- **Two filter bugs, fixed, each with a check a mutation run showed fails without it:**
  - Purpose visibility was read at default time. It is now UsdImaging's attribute data sources on the filter's globals, read at the graph's time and dirtied when it changes.
  - UsdImaging never flags animated subset indices, so incremental captures kept stale subsets. The filter now flags them.
- **Skinning works through the graph's ext-computation pruning,** for one linear-blend skin with identity transforms: Body's points match `ComputeSkinnedPoints` at every time. UsdSkel's primvars still reach the plan as attributes and a property: recorded, not fixed, since it is M8's geometry policy.
- **Filter rebuilds per time change are wider than needed** (16 on the case's scene, from every dirtied prim; 3 in an ad hoc build that invalidated only for extents). Not changed; Phase E imports one frame only, so the cost is left for M4 (listed in Phase E's plan).
- **Warnings posted outside capture** (2026-10-14, after the CI run above). The CI logs printed 491 HermiteCurves warnings and 131 for bindings without `MaterialBindingAPI`, all expected. But those posted while a bridge is built never became diagnostics, because only a capture collects them. Two fixes, each with checks a mutation run showed fail without them:
  - The bridge collects warnings while it is built and adds them, without a source, to its first capture's diagnostics, as events reach the capture after them. Release-time warnings are still printed, since no capture follows.
  - The filter reports bindings authored without `MaterialBindingAPI` (`bindingsWithoutApi`), so the plan warns on each copy's source whenever USD would honor such a binding, independent of when USD posts its own warning.

  128 checks pass in both hosts on all three platforms, with no compiler warnings ([run 38642723300](https://github.com/scottdmilner/proscenium/actions/runs/38642723300), commit `a1c8b80`).
- **Notes for M4.** The record's [notes on evaluating frames](../feasibility/runtime-record.md#for-m4-evaluating-frames): per-frame capture with dirty-driven change discovery, caching as a layer above it, and direct USD when a representation needs authored keys. The M4 milestone links to them.

## Phase E — Measurements

Kept separate, as the milestone requires: Hydra capture, C++ planning, C++ → Python transfer, Blender construction, and peak memory. Results come from the Blender binary on the reference hardware, under [Performance](../testing/acceptance.md#performance): AC power, no other heavy load, the OS version and Blender build hash recorded, and repeated runs.

- **Baseline: Blender's native USD importer** (`bpy.ops.wm.usd_import`). This replaces a direct-USD Python implementation of the same capture (with the user, 2026-10-14). A pure-Python version is very unlikely to come close to compiled code, so comparing against it would say little. The importer is C++ reading USD directly, and its cost is one users already accept to get USD into Blender.
  - **The feature sets differ.**
    - **The importer:**
      - opens its own stage from the file;
      - skips invisible prims by default;
      - builds an object hierarchy, Principled BSDF networks from UsdPreviewSurface, curves, lights, cameras, armatures and subdivision modifiers;
      - makes collection instances for native instances;
      - reads animated meshes and transforms when the depsgraph evaluates, through Mesh Sequence Cache modifiers and Transform Cache constraints, not while it imports. The first depsgraph evaluation is therefore part of its cost.
    - **The prototype:** works from a caller's stage and builds:
      - flat objects with world matrices;
      - viewport-color materials;
      - one mesh per plan mesh;
      - placeholders for untranslated types;
      - objects for every purpose.
  - **Three importer configurations.**
    - **Defaults:** what a user gets.
    - **Matched:** the options closest to the prototype. Every purpose and invisible prims are imported, and UsdPreviewSurface conversion, unit scaling and the types the prototype makes placeholders for are off (`measure/child.py` lists them).
    - **Expanded:** matched, with scene instancing off. Added during Phase E: with instancing on, the importer drops materials bound at an instance root, which the prototype honors (see the Phase E log).
    - **Counts recorded with every run:** objects, meshes, materials, collections, vertices and corners, so the difference in work shows next to the numbers.
  - **Compared end to end.** The importer is one operator call: its stage open, translation and construction can't be timed apart. The comparisons are:
    - initial synchronization, from opening the file in a fresh process through the first depsgraph evaluation;
    - Blender construction plus that evaluation, on its own.
  - **One frame only** (with the user, 2026-10-14): each run imports one time code. Frame changes and frame ranges are not measured.
- **Prototype stages, each measured separately:**
  1. stage open;
  2. bridge construction (the scene-index chain);
  3. capture;
  4. C++ planning;
  5. transfer (the plan's Python views);
  6. Blender construction;
  7. the first depsgraph evaluation;
  8. release.
- **CPU and memory, during and after.**
  - **Sampling.** Each run is a fresh binary process with factory startup. A parent process samples it at a short fixed interval with psutil, added to the dev group (with the user, 2026-10-14), recording:
    - resident memory;
    - CPU time (user and system);
    - thread count.
    The child writes stage markers for aligning the samples. An in-process sampler thread may not run while C++ code or an operator holds the GIL, so it isn't relied on.
  - **Per stage:**
    - wall time;
    - CPU time, and its ratio to wall time (average cores busy);
    - peak resident memory within the stage, from the samples, and the process's own peak counter where the OS provides one;
    - resident memory at the end.
  - **Baseline memory.** The empty factory-startup process is measured and subtracted.
  - **Retained memory after synchronization.** Measured once memory settles, at each of these points:
    1. with the bridge alive, since incremental capture keeps the scene-index chain and its flattening cache;
    2. after releasing the bridge;
    3. after also dropping the stage;
    4. after deleting the Blender data.
    The differences split what is retained into Hydra chain, stage and Blender data. For the importer, retained memory is measured after the import and again after deleting its data.
  - **Platform names.** Which memory counter each platform reports is recorded by name. On macOS, Activity Monitor's figure (physical footprint) differs from resident memory.
- **Repeats.**
  - Three runs per scene and configuration (cut from five with the user, 2026-10-14, to keep the run short), alternating importer and prototype, reporting the median and range.
  - The OS file cache is warm, as in the anonymous-view timings: purging it needs root. Each sequence's first run is also reported separately.
- **Scenes:**
  - **The bespoke fixtures:** dropped from the measured set (with the user, 2026-10-14). The smallest stress scene shows the fixed overhead.
  - **Generated stress scenes of controlled size**, each varying one dimension:
    - mesh size: one mesh, of thousands and of millions of points;
    - prim count: 10,000 small meshes;
    - instancing: prototypes times instances, nested two levels, with appearance variation that splits instancers;
    - animation: a large deforming mesh and many animated transforms, imported at one time code. The importer adds cache modifiers and constraints for them, so its first depsgraph evaluation reads them.
    A script writes them under `build/` (not committed) and records their parameters.
  - **ALab, through a custom entry point** (with the user, 2026-10-14). Load-all, at one time code, pinned under [Production-Scale Validation](../testing/acceptance.md#production-scale-validation-alab), run by hand. Load-none is empty, so it isn't measured.
    - **Why.** Both sides then import the same content. The importer translates content the prototype only marks with placeholders, and that work would otherwise count against it.
    - **The entry point.** A new root layer sublayers `entry.usda` and deactivates every prim of a type the prototype doesn't translate. From the [inventory](../testing/alab/inventory.md), that means lights, the camera, NurbsCurves, Points, PointInstancers and `ALAudio`.
      - A script writes it under `build/`, with a comment stating its purpose. It finds the prims by traversing the composed stage and records the paths it deactivated. The pinned ALab tree is unchanged.
    - **Limit.** A stronger layer can't deactivate prims inside native-instance prototypes, because opinions on instance proxies are ignored. ALab has 3 RectLights there (6 expanded), so they stay. The matched importer configuration doesn't import lights, and the prototype gives them placeholders. The run records what remains of each untranslated type.
- **Carried in from Phase C:**
  - **Sharing.** On the instancing stress scene and ALab: plan meshes against distinct USD meshes, and what the difference costs in Blender construction and memory. Phase C's count (216 meshes for 9 leaf meshes) comes from small meshes.
  - **The filter's per-prim USD queries** on first capture: UsdShade's binding resolution for each material purpose, the materialBind family verdict, the dropped-attribute scan, and computed extents (Phase C's limits).
- **CI** runs the harness on one small scene on all three platforms, to keep it working. Shared runners make its numbers unreliable, so none are recorded as results.

- **Not measured, left for M4:** time changes and frame ranges, and the filter's rebuilds on a time change. The source-info filter rebuilds a prim's cached facts for every prim dirtied on a time change, though only computed extents go stale (Phase D: 16 rebuilds per change on the animation case, 3 in an ad hoc build that invalidated only for extents). Whether narrowing that invalidation is worth it depends on how M4 evaluates frames ([notes](../feasibility/runtime-record.md#for-m4-evaluating-frames)).

The measurements report what was run; they are not extrapolated to Phase 2 budgets.

### Phase E log

Branch `m01b-phase-e`, off `m01b-phase-d`.

- **Status (2026-10-14): measured on macOS arm64** (reference hardware, Blender 5.2.2 binary). Results are in the [feasibility record](../feasibility/runtime-record.md#measurements-m1b-phase-e). CI runs the harness on one small scene on all three platforms, recording no numbers. The correctness checks are unchanged (128 in both hosts, macOS).
- **Harness** (`hydra_bridge/measure/`):
  - **`run.py`** runs each scene and mode in a fresh binary process and samples it from outside with psutil. psutil is in the dev group.
  - **`child.py`** marks each stage with CPU time, the lifetime peak and the live heap.
  - **Inputs:** `stress.py` generates the scenes, and `alab_entry.py` writes ALab's entry point.
  - **`report.py`** summarizes the runs.
  - **Timers for the filter and the planner** (`src/fact_timings.*`, exposed as `take_filter_timings()`) are for this phase only.
- **Changes to the plan while running:**
  - **A third importer configuration, "expanded"** (matched without scene instancing). With instancing on, the importer drops materials bound at an instance root, so neither of the first two builds what the prototype builds on instancing scenes.
  - **A smaller run** (with the user, 2026-10-14): three repeats, five stress scenes (one small and one large mesh, 10,000 prims, nested instancing, animation) and ALab, with no bespoke fixtures. It takes about 6 minutes; the first plan would have taken about 1.5 hours.
  - **Retained memory is read as live heap.** The footprint stays high after memory is freed (the allocator keeps the pages), so it says little about what is still owned. The live heap showed both sides back to under 40 MB after deleting their data.
  - **The cleanup re-evaluates the depsgraph after deleting data.** Evaluated copies hold their memory until the next evaluation: 1.7 GB on ALab's imported data.
- **Results on ALab, against the matched importer** (the recorded run, with parallel planning):
  - **Time:** 3.69 s against 3.45 s (1.07×).
  - **Peak memory:** 3,113 MB against 1,795 MB (1.73×).
  - **The Hydra stages (1.27 s) take less time than Blender construction (1.86 s).**
  - **With the bridge alive,** 1,451 MB of live heap is held: the snapshot (517 MB at capture) and the plan (901 MB at planning).

  All three parts of the tentative criterion 4 hold. In the first run, with serial planning, the stage-split part didn't: the Hydra stages took 2.12 s against 1.91 s (time 1.43×, memory 1.76×). The user sets the final criterion.
- **Answers to the items carried in:**
  - **Sharing:** 3,945 plan meshes for 6,679 mesh copies on ALab, the same as the instancing importer.
  - **The filter's per-prim queries:** they cost 0.53 s of CPU (summed over threads) while ALab's bridge is built, out of 1.88 s. Binding resolution is most of it (0.35 s). On 10,000 small prims the filter takes 0.83 s of the stage's 1.05 s, 0.63 s of it bindings.
- **Where planning's time goes** (2026-10-14, measured after the run above, with timers in the planner):
  - On ALab, building meshes one at a time is 95% of planning: 1.30 s of 1.36 s. Objects take 0.02 s, and reading the records 0.03 s.
  - Within mesh building, USD's `PxOsdMeshTopology::Validate` takes 0.55 s, finding the faces Blender would delete 0.28 s, primvars 0.31 s and the layout 0.12 s.
  - On the 4.2M-point mesh, half of its 0.62 s is USD's validation.
  - The options for multithreading planning are, in order:
    1. Build meshes in parallel, with a serial pass for objects and diagnostics in prim order, so the plan stays identical.
    2. For a single large mesh, run its independent passes concurrently and parallelize the bridge's own loops; USD's validation is one call.
    3. Not worth it now: parallel object building, which takes 0.02 s.
- **Option 1 implemented** (with the user, 2026-10-14). `Planner::BuildMeshes` builds every mesh in parallel; the serial pass adds them to the plan in prim order.
  - **ALab:** planning goes from 1.20 s to 0.26 s (5.7 cores), synchronization from 4.61 s to 3.69 s, and the Hydra stages from 2.12 s to 1.27 s.
  - **The large mesh is unchanged** (0.61 s), as expected.
  - **Against the matched importer in the same run:** 1.07× the time and 1.73× the peak memory, with the Hydra stages below Blender construction (1.86 s). All three parts of the tentative criterion 4 now hold.
  - **The plan is identical** (canonical digest on ALab, and the correctness checks).
  - **Found while checking:** the plan's order varies between processes, though its content doesn't. Its 3,945 meshes hold 3,369 distinct contents.
  - Options 2 and 3 are not implemented.
  - **Mesh building's summed time rose from 1.30 s to 2.00 s in parallel,** so the threads contend for something. It is recorded for the production core in the record's [notes for production planning](../feasibility/runtime-record.md#for-production-planning-m8), which the M8 milestone links.

## Phase F — Decision

**Criteria, fixed before results** (except criterion 4's thresholds, below)**:** Hydra is adopted only if all of these hold:

1. Native loading works on all three platforms in both hosts.
2. Distribution works through the chosen channel (Phase 0 settled that a compiled core is acceptable).
3. Every Phase C case passes, or its gap has a bounded workaround in the core that keeps the requirement intact (Hydra does not relax requirements).
4. **Tentative (with the user, 2026-10-14), replacing the Python-baseline criterion:** at ALab scale (the custom entry point), measured against Blender's native importer in its matched configuration:
   - initial synchronization's end-to-end time is at most 2× the importer's, and so is its peak memory;
   - the Hydra stages (capture, planning and transfer) together take less time than Blender construction;
   - memory retained with the bridge alive is reported, not gated.

   The user sets the final criterion after seeing Phase E's data. Unlike the other criteria, it is not fixed before results, and the decision record says so.

Otherwise: "Hydra not adopted", and the Python-only row continues under M4.

**Outputs:**

- The DECISIONS.md rows "Evaluation front end and core language", "Python-only implementation", "Native core distribution" (if adopted), and "Compiled Hydra evaluation bridge".
- The time-sampling findings, for the "Time-sampled data representation" row.
- If Hydra is adopted, the milestone's follow-up updates (AGENTS.md, PROJECT.md, and milestones M3, M5, M6, M8–M10, M13), made in the same change.

## Requirement matrix

Done at the start of Phase A: M1b is in `started`, with oracles on its two rows.

- **COMP-04 (contract):** the decision record, backed by the prototype's results and measurements.
- **COMP-06 (process):** the per-platform build audit and run-time single-USD and provenance checks.
- **SNAP-16 and SNAP-17** moved to M6 (agreed with the user, 2026-10-09). M1b's prototype is not production code, so it checks these cases but cannot deliver them. Their notes still say they apply only if Hydra is adopted.
