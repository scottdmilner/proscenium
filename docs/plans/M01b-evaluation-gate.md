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
  - doubleSided is forced to false.
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
- **Skinning** is resolved in the chain by default, by a CPU ext computation. Deformed points are readable only after adding ext-computation pruning. Whether the points are correct, and whether their sample times are reported, is unverified.
- **Not imaged:** `UsdGeomVisibilityAPI` (purpose visibility), HermiteCurves, and computed extents.
- **Lifetime.**
  - `UsdImagingStageSceneIndex` holds a strong stage reference. To honour the caller-release contract, the core must call `SetStage(nullptr)` on release.
  - The flattening cache keeps every queried prim for the life of the chain.

### Change tracking and time

- Notices are synchronous, single-threaded, and delivered in registration order.
- A dirty notice covers child locators, not child prims. Flattening adds descendant dirties only for descendants whose data was pulled before.
- A resync arrives as Added on existing paths, plus Removed for paths that are gone.
- `SetTime` dirties exactly the locators that were flagged time-varying (from `ValueMightBeTimeVarying`), and only on data sources already pulled. Flags are never cleared, so dirties also arrive for removed paths and unchanged values.
- **`GetContributingSampleTimesForInterval`:**
  - Attributes report sample times, and a static child under an animated parent reports its parent's (the flattened-xform combiner merges both).
  - A zero-width interval gives inconsistent answers (false exactly on a sample frame), so detection must query a real interval.
  - Visibility and instancer masks never report sample times; they appear only as dirties.
  - Mesh orientation, scheme, doubleSided, and subdivision tags are not flagged.
  - **Crash risk:** UsdImaging sampled sources write to the output vector without a null check, so always pass one.
- Data-source handles read the stage and current time live, so a handle is not a snapshot. Values must be copied out. The xform combiner caches its value at offset 0 and goes stale across `SetTime`.
- Capturing with `UsdTimeCode::Default()` makes every sample-time query return false. The stage scene index starts at numeric time 0.0.

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
  4. NURBS approximation
  5. dependency forwarding
  6. prim-type notice batching
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

## Phase D — Time-sampled data detection

Recorded in the feasibility record whatever the decision. For points, transforms, primvars, visibility, and topology, compare against authored samples and against `UsdAttribute::ValueMightBeTimeVarying`, including a static mesh under an animated ancestor. Three candidate signals:

1. `GetContributingSampleTimesForInterval` over a real interval (never zero-width).
2. The dirty set that `SetTime` emits.
3. Direct USD queries.

Record which values each signal reports, over what interval, and where they disagree. Visibility is expected to appear only as a dirty. Skinned points are included if the ext-computation path works.

## Phase E — Measurements

Kept separate, as the milestone requires: Hydra capture, C++ planning, C++ → Python transfer, Blender construction, and peak memory.

- **Baseline:** a direct-USD Python implementation of the same capture on the same fixtures.
- **Scale:** the bespoke fixtures, a synthetic stress scene (many instances, large meshes), and ALab under the pinned [acceptance](../testing/acceptance.md) setup, on the reference hardware.

The measurements report what was run; they are not extrapolated to Phase 2 budgets.

## Phase F — Decision

**Criteria, fixed before results:** Hydra is adopted only if all of these hold:

1. Native loading works on all three platforms in both hosts.
2. Distribution works through the chosen channel (Phase 0 settled that a compiled core is acceptable).
3. Every Phase C case passes, or its gap has a bounded workaround in the core that keeps the requirement intact (Hydra does not relax requirements).
4. Measurements show no regression against the Python baseline that matters at ALab scale, and a gain in at least one of capture or planning.

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
