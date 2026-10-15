# Runtime Feasibility Record (M1)

Evidence for the [M1](../milestones/M01-runtime.md) stop/go gate. Each finding is produced by a probe in `tools/feasibility/` and reproduced with:

```sh
uv run python tools/feasibility/run_all.py          # writes build/feasibility/<platform>-*.json
PROSCENIUM_ALAB_ROOT=/path/to/ALab uv run python tools/feasibility/run_all.py   # adds the ALab check
```

Probes run in three runtimes per platform:

- **wheel**: the `bpy` wheel imported by the uv interpreter.
- **wheel-pytest**: the same, inside a pytest session.
- **binary**: the Blender executable in background mode.

The binary is what users run, so its results are authoritative. Every runtime gets an isolated `BLENDER_USER_RESOURCES`. Windowed (UI-mode) behavior is out of scope and listed under [Future Work](#future-work).

Findings describe observed behavior. Where a finding suggests a mechanism, the owning milestone settles it.

## Verdict

| Platform | Status |
|---|---|
| macOS arm64 | **Go.** All 55 checks pass in all three runtimes (2026-10-09, including the M1b `buffer_transfer` probe). |
| Windows x64 | **Go.** All 55 checks pass in all three runtimes. The [compiled Hydra bridge](#compiled-hydra-bridge) passes in both hosts. |
| Linux x64 | **Go.** All 55 checks pass in all three runtimes. The [compiled Hydra bridge](#compiled-hydra-bridge-1) passes in both hosts. |

## macOS arm64

### Environment

| Item | Value |
|---|---|
| Hardware | Apple M1 Max, 32 GB (reference hardware, see [Performance](../testing/acceptance.md#performance)) |
| OS | macOS 26 |
| Blender | 5.2.2 LTS, build hash `d13f752e3b9c`, build date 2026-09-15 |
| `bpy` wheel | 5.2.2, same build hash |
| Embedded Python | 3.13.13 (binary: Blender's bundled interpreter; wheel: uv-managed CPython 3.13.13) |
| OpenUSD | 0.26.3 (`pxr` bundled in both; exactly one `pxr` package on `sys.path` and no installed distribution ships its own top-level `pxr`, checked in each runtime; the `types-usd` stubs install `pxr-stubs` and don't count) |
| MaterialX | 1.39.4 |
| USD plugins | 53 registered, with the same plugin names in wheel and binary |

**Modules.** All `pxr` modules import in every runtime: Ar, CameraUtil, GeomUtil, Gf, Glf, Kind, Pcp, Plug, PxOsd, Sdf, Sdr, SdrGlslfx, Tf, Trace, Ts, Usd, UsdAppUtils, UsdGeom, UsdHydra, UsdImagingGL, UsdLux, UsdMedia, UsdMtlx, UsdPhysics, UsdProc, UsdRender, UsdRi, UsdSemantics, UsdShade, UsdShaders, UsdSkel, UsdUI, UsdUtils, UsdValidation, UsdVol, Vt, Work.

**Paths and plugin discovery.**
- Binary `pxr` path: `Blender.app/Contents/Resources/5.2/python/lib/python3.13/site-packages/pxr`.
- Wheel `pxr` path: `site-packages/bpy/5.2/python/lib/python3.13/site-packages/pxr`. It reaches `sys.path` through `tools/bpy-site-packages`.
- The only USD-related environment variable set is `PXR_MTLX_STDLIB_SEARCH_PATHS`, which points at Blender's bundled MaterialX libraries.
- No `PXR_PLUGINPATH_NAME` is set. Every recorded plugin path is inside the Blender bundle or empty (built in), so no external resolver or schema plugin is loaded.

### Stage exchange

Exchange works.
- Caller code and extension code in the same process share one `pxr` module and one layer registry.
- A file-backed stage handed over by the caller arrives with its unsaved root-layer edits and session-layer opinions, shares its root layer object with the receiver, and can also be looked up by `UsdUtils.StageCache` id.
- These checks pass both for a separately loaded module and for an extension installed through the extension system ([Packaging](#packaging)).
- An anonymous in-memory stage was checked only with the separately loaded module, and only for its unsaved edits.

**Blender's USD importer sees unsaved Python-side layer edits.** `bpy.ops.wm.usd_import` imported a prim that existed only as an unsaved edit to a layer opened in Python. The file on disk was unchanged. Only this direction was tested; reloads and the USD exporter were not exercised.

### Handlers

- A `@persistent` `load_post` handler fired once for one `open_mainfile`, and once for one `read_factory_settings`.
- A non-persistent `load_post` handler was removed by the file load.
- `undo_post` and `redo_post` each fired once for one `ed.undo` and one `ed.redo`.

Each case was exercised once per runtime; the results are identical in the wheel, under pytest, and in the binary.

### Undo

All runtimes here are background mode.

| Case | Global undo on | Global undo off |
|---|---|---|
| Plain function calls `bpy.ops.ed.undo_push`, then `ed.undo` / `ed.redo` | Works. With two pushes after a base step, one undo removes only the second change, redo restores it, and two undos reach the base. | `ed.undo` fails its poll after the pushes. |
| Operator with `bl_options={'UNDO'}` called from Python as `op()` or `op('EXEC_DEFAULT', False)` | **No step pushed** (`ed.undo` fails its poll). This is consistent with `bpy.ops` calls defaulting to `undo=False`. | `ed.undo` fails its poll |
| Same operator called as `op('EXEC_DEFAULT', True)` | Step pushed, and undo removes the operator's change | `ed.undo` fails its poll |

**Implications for M5:**
- A synchronization invoked from the Python API can push its own undo step, either with `ed.undo_push` or by calling its operator with `undo=True`. Calling the operator with no arguments pushes nothing, and nothing reports it.
- With global undo off, nothing pushed this way could be undone, so "one undo step per publication" has no observable effect there.

**Datablock references across undo** (Objects only, one case each):
- A reference to an Object that the undo did not touch stayed valid and compared equal to a fresh lookup.
- A reference to an Object renamed in the undone step, or created in it, raised `ReferenceError`.

Other datablock types and other kinds of change were not tested. Because held references fail only in some cases, they are easy to miss in testing, which supports the rule in [Undo and Runtime State](../spec/lifecycle.md#undo-and-runtime-state).

### In-memory source candidates

Tested the design-note candidate from [In-Memory Sources](../spec/source-access.md#in-memory-sources): a private stage per binding over the caller's root and session layers. It was opened with `Usd.Stage.OpenMasked(root, session, resolverContext, mask, load)` under `BlockStageCaches`. The caller's settings were then reproduced with `MuteAndUnmuteLayers` and `SetInterpolationType`.

All checks pass:
- The private stage is distinct from the caller's.
- It sees the caller's unsaved layer edits and session-layer opinions.
- The binding's payload policy replaces the caller's: `load_none` and `load_all` private stages coexist with the caller's load-all stage.
- The population mask, muted layers, and interpolation are reproduced.
- The caller's load set, mask, muted layers, edit target, interpolation, composed values, and layer contents are all unchanged.

Observations for M3:
- **Cache contexts can return the caller's own stage.** With an active `Usd.StageCacheContext` holding the caller's stage, `Usd.Stage.Open(root, session, LoadNone)` returns the caller's stage itself. Opening under `Usd.StageCacheContext(Usd.BlockStageCaches)` returns a new stage. Suggestion for M3: a private-stage approach should block caches explicitly.
- **Edits stay live.** Private stages share layers, so caller edits made after the private stage is opened are visible. This is consistent with [Source Consistency](../spec/source-access.md#source-consistency): callers must not mutate the stage during a synchronization.
- **Resolver context.** The caller's context passes through as an opaque `Ar.ResolverContext`. Only the default resolver was exercised.

### Dirty layers and fresh stages

- `Usd.Stage.GetUsedLayers()` includes layer-stack layers and layers introduced by references, payloads, nested arcs, absolute-path references, and selected variants. It excludes layers referenced only from unselected variants.
- Under load-all, filtering by `layer.dirty and not layer.anonymous` reported exactly the three edited layers.
- Under load-none, the dirty layer reached only through the payload was not reported, presumably because the unloaded payload does not contribute. Whether that is the right notion of "contributing" is for M3.
- The session layer is anonymous and starts clean.
- **A freshly opened stage composes dirty in-process content.** `Usd.Stage.Open` reuses registry layers, so a fresh open alone does not give the disk state. This is the premise of the dirty-layer rule. The options examined here are the conflict failure and a private disk view; M3 may consider others.
- **Fresh stages.**
  - Opening outside any cache context returns a new stage even when `UsdUtils.StageCache` holds one for the same root.
  - Inside an active cache context, the cached stage is reused.
  - `BlockStageCaches` gives a new stage even inside one.
  - A fresh stage shares its root layer object with existing stages (only the root layer was compared).
- **Reloads.**
  - A non-forced `layer.Reload()` on every clean contributing layer reloads only the layer that changed on disk, and other stages sharing it see the new content.
  - An immediate second rewrite was also detected without `force`. This was on APFS with nanosecond mtimes. Linux CI also detected it; [Windows did not](#windows-x64), because USD's Windows timestamps have whole-second resolution.
  - **A non-forced `Reload()` appears to go by modification time.** It skipped a content change when the file's mtime was restored to its previous value, and `Reload(force=True)` reread it. So a non-forced reload can miss rewrites that preserve mtime.
  - **`Reload()` on a dirty layer discards its unsaved edits without any error.** A refresh that reloads layers must therefore skip dirty ones.
  - Probe note: Blender's bundled Python truncates `os.utime` to microseconds, while the uv interpreter keeps nanoseconds. The probe pins mtimes to whole seconds so the check behaves the same in both.

### Private disk view

The question is whether the on-disk state can be composed without touching shared layers ([File-Backed Refresh](../spec/source-access.md#file-backed-refresh)). The test scene had dirty edits in sublayer, reference, payload-nested, and absolute-path layers. All candidates left the shared layers untouched.

| Candidate | Matches disk | Relative texture path resolves to | Notes |
|---|---|---|---|
| Copy scene dir elsewhere | No | The copied file | The absolute-path reference resolves to the shared, dirty layer. |
| Symlink scene dir | No | The source file | Same absolute-path leak |
| Anonymous copies with remapped asset paths | **Yes** | The source file | Reopens every reachable layer with `Sdf.Layer.OpenAsAnonymous`. Rewrites layer asset paths to the copies and other asset paths to absolute disk paths, using `UsdUtils.ModifyAssetPaths`. |

**Anonymous copies at ALab scale** (clean layers, load-all):
- The set of prim paths and type names is identical to a normal open: 48,289 prims including instance proxies. Attribute values and other composed data were not compared.
- It copied 4,474 layers where the normal stage uses 3,181. A likely cause, not verified, is that the remap follows asset paths in every variant, not just the selected ones.
- 2,400 asset paths could not be resolved during copying. This was not investigated. If those files are missing, a normal open fails to resolve them too, so the matching inventory does not show whether they lie on the composed path.
- **Timing.** Each open ran in a fresh process, alternating normal and anonymous-view opens over two rounds per runtime. A normal open took 0.53–0.68 s; the anonymous view took 15.9–17.1 s, about 25–30× slower. The OS file cache was not purged, so both figures are warm-cache.

**Assessment for M3:**
- A private disk view is **feasible in correctness** for the arcs tested: sublayers, references, payloads, nested arcs, absolute paths, variants, and relative asset attributes.
- As implemented here it is **likely too slow to use on every refresh** of a production scene. That is a judgment: no budget exists yet (M4 sets provisional budgets).
- Not covered: resolver search-path identifiers, asset-path expressions, value clips, `.usdz` packages, file-format arguments, and the heuristic that classifies layer paths by file extension.
- Lazy copying (only layers on the composed path) and copying only the dirty layers' dependents are untested options.

The chosen conflict failure stays valid. Upgrading to a disk view would need M3 to address cost and the uncovered cases.

### Packaging

- **No Blender binary is needed to build.** The wheel ships `bpy/5.2/scripts/addons_core/bl_pkg/cli/blender_ext.py`, which imports only the standard library. Run with the uv interpreter, it validates a source dir, builds an archive, and validates the archive.
- Its archive has the same members with identical file contents as one built by `blender --command extension build` (compared member by member, not as zip bytes).
- `build` requires `--output-dir` to exist already.
- The built archive installs in-process with `bpy.ops.extensions.package_install_files` into a temporary local repo created with `preferences.extensions.repos.new(..., source="USER")`, with `enable_on_install=True`.
  - Install calls `register()`.
  - The installed extension receives the same file-backed caller stage as in [Stage exchange](#stage-exchange), and passes the same checks.
  - `addon_utils.disable` calls `unregister()`.
- The installed files contain no `pxr` directory or `usd_ms` library, and the installed extension's `pxr.Usd` is the same module object the caller uses.

### Buffer transfer

Added for M1b (`probe_buffer_transfer.py`). It asks whether USD arrays reach Blender mesh data without a Python-side copy.

- `Vt.Vec3fArray` exposes a read-only buffer.
- Blender's `foreach_set` rejects the raw array and its 2-D view ("Array length mismatch"). A flat view, `memoryview(array).cast("B").cast("f")`, keeps format `'f'` and 3N elements, and is accepted.
- Through `mesh.attributes["position"].data.foreach_set("vector", flat)`, 1,000,000 points arrive with the values intact.
- A `Vt.IntArray` view sets loop vertex indices.

Single timings for 1,000,000 points, one run each, not benchmarks:

| Runtime | Attribute `position` | `vertices.co` | `bytes()` copy of the same buffer |
|---|---|---|---|
| wheel | 0.26 ms | 31.2 ms | 0.45 ms |
| wheel-pytest | 0.29 ms | 31.5 ms | 0.30 ms |
| binary | 0.27 ms | 31.7 ms | 0.23 ms |

The attribute path costs about one memory copy. `vertices.co` is about 100 times slower on the same buffer.

## Compiled Hydra bridge — macOS arm64

**Verdict: feasible on the tested Blender 5.2.2 / USD 0.26.3 build.** A standalone
Python extension links to Blender's bundled `libusd_ms`, receives the caller's
`Usd.Stage` directly, and consumes Hydra scene indices. The same compiled module
passed **41 loading checks and 20 prototype checks in the bpy wheel, and the same in the
Blender binary**, each in a fresh background process ("Hydra bridge" workflow,
[run 38293887802](https://github.com/scottdmilner/proscenium/actions/runs/38293887802), 2026-10-12). The prototype checks cover M1b Phase B's slice:
capture, a C++ display plan, and application to Blender ([below](#prototype-slice-m1b-phase-b)).
Phase C added a loading check and the correctness cases ([below](#prototype-correctness-m1b-phase-c)), which pass on all three platforms ([run 38359009667](https://github.com/scottdmilner/proscenium/actions/runs/38359009667)).
This is a feasibility result, not adoption of Hydra or qualification of a distributable
bridge. The same checks pass on [Windows x64](#compiled-hydra-bridge) and
[Linux x64](#compiled-hydra-bridge-1), recorded under those platforms.

### Build and reproduction

Source: [`tools/feasibility/hydra_bridge/`](../../tools/feasibility/hydra_bridge/).
The same commands run on macOS arm64, Linux x64, and Windows x64:

```sh
uv run python tools/feasibility/hydra_bridge/build.py   # build, extract, audit linkage
uv run python tools/feasibility/hydra_bridge/run.py     # loading, prototype and correctness checks, wheel and binary
```

`run.py` finds the Blender binary through `BLENDER` or the platform default
(`--blender` overrides). The "Hydra bridge" GitHub workflow runs both on all three
platforms, by hand or on a push to an `m01b-*` branch that changes the bridge, and
uploads `build/hydra-bridge/`.

The bridge is a `CMakeLists.txt` built directly by `build.py`, with the CMake and Ninja
from the dev group. It configures a Release build for the uv environment's
interpreter, installs into a temporary folder, moves the module into
`build/hydra-bridge/` for the probes, and audits it. No wheel is built: the module
is meant to ship inside the extension package, and the main extension still builds
only through `tools/build_extension.py`.

**Dependencies.** The target release is the bpy version in `uv.lock` (5.2.2;
`tools/blender_release.py`). The same helper picks the Blender binary CI downloads.
`prepare_deps.py` reads that release's git tag (`v5.2.2`) from a shallow, treeless
clone of `blender.git` and takes the precompiled-library revisions from its `lib/`
submodule pointers. The resolved tag, commit, and revisions are cached in
`external/blender-<tag>.json`. `build.py` checks that the installed bpy wheel's version
is the locked one, from its metadata. The probe then checks in each host that
`bpy.app.build_hash` is the tag's commit (`d13f752e3b9c`) recorded in `build.json`. So
headers, link input, and test hosts come from one release.

On the first build `prepare_deps.py` makes a blobless sparse checkout of the
platform's library repo under the bridge's gitignored `external/<repo>/`. A warm build
needs no network access: on macOS (2026-10-10) it succeeded with `UV_OFFLINE=1` and Git's
`protocol.allow=never`. The revisions resolved from `v5.2.2` match those used for the
CI results below:

| Platform | Repository and revision | Checked out | Link input |
|---|---|---|---|
| macOS arm64 | `lib-macos_arm64` `a76ef917b4849ba2b1b1deb1a643e131a884a63b` | USD, TBB, Python headers | the bpy wheel's `bpy/lib/libusd_ms.dylib` |
| Linux x64 | `lib-linux_x64` `ecbd06cf6d2a4aa6b00a61ffb479fc81b17aba08` | USD, TBB, Python headers | the bpy wheel's `bpy/lib/libusd_ms.so` |
| Windows x64 | `lib-windows_x64` `60d6e96b917568278d400a4024c98da0fb777338` | headers, plus `usd_ms.lib`, `tbb12.lib`, `python313.lib` | the import library `usd_ms.lib` (the wheel has none) |

No dependency library is shipped. `--usd-library` selects another link input on
macOS and Linux; only its install name or SONAME is recorded in the module.

**Build settings, all platforms:** C++17, with `-Wall -Wextra -Wpedantic` (`/W4` on MSVC) on the bridge's own sources; Blender's generated USD headers (namespace
`pxrBlender_v26_03__pxrReserved__`, which stock upstream headers do not have);
`PXR_BOOST_PYTHON_NO_PY_SIGNATURES`, which Blender's exported pxr Python target
defines; hidden symbol visibility; no embedded rpath. The module uses USD's internal
`pxr_boost::python` and the host's existing converters; no separate Boost.Python is
linked.

- **macOS:** minimum macOS 11.2, Blender 5.2's floor. The earlier build had 26.0 and would not have loaded on older systems.
- **Linux:** built in `manylinux_2_28` (GCC 14, glibc 2.28), matching the floor of Blender's libraries, then tested on `ubuntu-latest`. No libpython link: Blender provides the Python symbols.
- **Windows:** MSVC toolset 14.44, the linker version of Blender 5.2.2's `usd_ms.dll`; `/MD` release runtime; USD's MSVC flags.

**Audit** (`build.py`, fails the build):

| Platform | Checks |
|---|---|
| macOS | Load command `@rpath/libusd_ms.dylib`; no `LC_RPATH`; `minos` 11.2; every imported `pxrBlender` symbol binds to `libusd_ms`, not dynamic lookup |
| Linux | `NEEDED libusd_ms.so`; no RPATH or RUNPATH; no libpython; undefined `pxrBlender` symbols present; highest GLIBC ≤ 2.28 and GLIBCXX ≤ 3.4.25 |
| Windows | Imports `usd_ms.dll` and `python313.dll`; no debug runtime; linker version ≤ 14.44 |
| All | The CMake install holds one top-level module and no USD, TBB, Python, or other library |

On macOS ([run 38293887802](https://github.com/scottdmilner/proscenium/actions/runs/38293887802), 2026-10-12): the module's 269 imported `pxrBlender` symbols all bind to
`libusd_ms`, and `minos` is 11.2 (AppleClang 21.0.0, no compiler warnings). The Phase A
module had 99, before the prototype's capture and planning code.

`build.json` records the platform, pins, CMake configure command, module path,
and audit results. `wheel.json` and `binary.json` record the loading checks and loaded USD
paths; `prototype-wheel.json` and `prototype-binary.json` record the prototype checks and
the plan's diagnostics; `correctness-wheel.json` and `correctness-binary.json` record each Phase C case's checks,
findings and any failure; the accompanying logs and process records include subprocess exits. Both
processes exit successfully after the checks, including shutdown. Each gets a
temporary Blender user directory and a temporary copy of the USD fixture. On macOS,
Blender startup requires access to Metal even in background mode; the successful local
runs were outside the execution sandbox.

### What passed (macOS arm64)

- **Shared runtime:**
  - Exactly one USD library is loaded in each process, from `bpy/lib/` in the wheel and `Blender.app/Contents/Resources/lib/` in the binary, and it is the host's own. The same extension binary works with each host's library; no second USD build is loaded.
  - The library that provides USD imaging code to the module, as the loader bound it, is that same image.
  - Python's `pxr` belongs to the host, no pip `usd-core` is installed, and the module was built for the host's USD version.
  - The host's `bpy.app.build_hash` is the commit of the Blender release whose headers built the module (`d13f752e3b9c`, tag `v5.2.2`).
- **Stage exchange:**
  - A Python-created file-backed stage round-trips through C++ with the same stage and root-layer identity.
  - Unsaved root-layer and session opinions are visible.
  - An anonymous stage also round-trips.
- **Stage lifetime:**
  - A retained Hydra chain keeps a stage alive after the caller releases it, because the stage scene index holds a strong reference.
  - After the bridge's `release()`, which detaches the stage from the chain, a caller-released stage expires: its anonymous root layer is gone, within the check's 2 s wait, together with the bridge's weak stage pointer (expiry can lag `release()`; see [Phase C](#prototype-correctness-m1b-phase-c)). The bridge then reports no stage, and a capture raises.
  - A released bridge leaves a stage the caller still holds alive (added in Phase C).
- **Errors:** passing `None` instead of a stage raises a Python exception rather than crashing. Constructing the bridge converts Tf errors into Python exceptions; during a capture they become diagnostics instead. No loading check posts one.
- **Hydra access:** the bridge builds the scene-index graph: `UsdImagingCreateSceneIndices` (draw mode off), then ext-computation primvar pruning, implicit surfaces to meshes (all six shapes), NURBS approximation, dependency forwarding, and prim-type notice batching. There is no extra `HdFlatteningSceneIndex`; the chain's own flattening supplies inherited state.
- **Mesh extraction:** triangle topology and points match the authored fixture; point arrays arrive through the existing `Vt.Vec3fArray` converter.
- **Implicit geometry:** a cube becomes a mesh with eight points, six quads, and the expected dimensions. Phase C's implicit case checks all six shapes and a NURBS patch.
- **Inherited state:** the triangle receives its parent's translation; an edit to ancestor visibility changes the effective visibility read from the chain.
- **Time:** `capture()` takes a numeric time, `None` or no argument (default time), or a `Usd.TimeCode`; anything else raises `TypeError`.
  - Values at time 1, interpolated values at time 2 (between samples 1 and 3), and a return to time 1 match the fixture.
  - After the time-1 sample is edited, default time still reads the authored default value, not the sample. The snapshot reports no numeric time there.
  - Time changes produce dirty notices; an immediate capture at the same time produces none.
- **Live edits:** changing a points sample in Python changes values read through the retained chain and emits a dirty notice. Adding or removing a prim changes both the queried inventory and the corresponding notifications.
- **Lifetime of captured data:** an earlier point array, and the snapshot it came from, remain unchanged after a later source edit and disposal of the bridge. Twenty repeated construction/capture/disposal cycles complete; this is not a leak or memory-growth measurement.
- **Source preservation:** initial capture leaves root/session layer text unchanged, and the source file is never saved. Deliberate source edits in the probe are caller actions, not bridge actions.
- **Instancing smoke check:** native instance inputs produce at least one Hydra instancer. Instance transforms, counts, nested contexts, and appearance are not validated by this check.

### Prototype slice (M1b Phase B)

`prototype_probe.py` runs capture, the C++ plan, and `apply.py` on `prototype.usda`. That scene has one example of each planner path:
- a mesh with a bound GeomSubset and an indexed UV primvar;
- an exact implicit shape (cube) and an approximated one (sphere);
- basis curves, which the prototype doesn't translate;
- native instances nested two deep, differing in displayColor.

Expected values come from USD (`UsdGeom.XformCache`, primvar inheritance, `UsdShade` bindings and shader inputs) or from the scene's construction, never from Hydra. All 20 checks pass in the wheel and the binary on all three platforms.

The plan has 8 objects, 5 meshes and 2 materials. Its only diagnostics are the approximated sphere and the basis-curve placeholder (as run for Phase B; Phase C's checks are below).

- **Snapshot:** an `HdRetainedSceneIndex` of `HdMakeStaticCopy` copies of the schemas planning reads, and no others. It and the plan are unchanged by a later stage edit, which only the next capture sees.
- **Sources:** one object per gprim USD draws through instance proxies, with its native-instance roots (outermost first), as `Usd.PrimRange` with instance proxies enumerates them.
- **Values:** world transforms match `UsdGeom.XformCache` within 1e-5. displayColor matches `FindPrimvarWithInheritance` through both instancing levels, including an inner instance root's value overriding an outer one's.
- **Diagnostics:** the sphere is diagnosed as approximated and the cube is not. The basis curves become a placeholder with a diagnostic: an empty in Phase B, a bounds-drawn box of USD's computed extent since Phase C.
- **Materials:** the plan's UsdPreviewSurface `diffuseColor` matches the shader's input, and each face's material slot is the one `UsdShade` binds to its GeomSubset or mesh.
- **Blender:**
  - Positions, corner vertices and face sizes match the USD mesh, and `Mesh.validate()` reports nothing to fix.
  - The indexed face-varying UVs reach a UV map, matching USD's flattened primvar.
  - Objects that share a plan mesh share Blender mesh data.
  - Plan arrays reach `foreach_set` as read-only, contiguous buffers in Blender's element types (`'f'`, `'i'`).

### Prototype correctness (M1b Phase C)

`correctness_probe.py` runs each case on its own scene in `cases/`: one `.usda` file with a purpose comment and one check module. The large-array grid is the exception: it is authored through UsdGeom into a temporary crate file.

**Passes on all three platforms:** all 118 checks in the bpy wheel and in the Blender 5.2.2 binary, on macOS arm64, Windows x64 and Linux x64, with the same count per case everywhere ("Hydra bridge" workflow, [run 38359009667](https://github.com/scottdmilner/proscenium/actions/runs/38359009667), commit `b919252`, 2026-10-13). The loading checks (42; 43 on Windows) and the prototype checks (20) pass in the same runs. That run's Windows build had two `/W4` warnings, fixed since (see [Windows](#compiled-hydra-bridge)). In the next run ([run 38361588537](https://github.com/scottdmilner/proscenium/actions/runs/38361588537)), the macOS binary failed one check, a timing: `foreach_set` from the plan buffer took 0.92 ms against 4.36 ms from a list, 4.8× where the check asks for 5× (the earlier binary run measured 35×). Each path had been timed once; the check now takes the minimum of five runs of each (locally 0.06 ms against 3.0 ms). Every other process of that run passed. With that change, every job passes ([run 38362866907](https://github.com/scottdmilner/proscenium/actions/runs/38362866907), commit `679566c`): 118 correctness, 42 loading (43 on Windows) and 20 prototype checks in each host on each platform, with no compiler warnings, and `foreach_set` from the plan buffer 17× to 55× faster than from a list.

**USD warns about HermiteCurves on every platform, as expected.** UsdImaging posts "Datasource support not yet added for adapter 'UsdImagingHermiteCurvesAdapter'" (`UsdImagingPrimAdapter::GetImagingSubprims`) for each HermiteCurves prim. That is why Hydra doesn't image them, and the filter's supplied data covers it. Measured locally: it is posted while the bridge is built (twice for the untranslated scene's one prim, eight times for the edits scene's two) and again at release, both outside capture, so Tf prints it. Posted during a capture, it becomes one `tf-warning` diagnostic with no source, beside the `untranslated-type` warning that names each prim.

Where the checks get their expected values:
- **Scene values** come from USD (`UsdGeom`, `UsdShade`, `ComputeExtentFromPlugins`) or from how the scene is built.
- **Application and incremental capture** are checked against the plan or against a full capture. In the edits case, each step is also checked against USD and against a new bridge.
- **Known gaps** are checks too: each asserts that its gap still reproduces.

The tests were audited on 2026-10-12, before this result, by four reviewers covering geometry, instancing and materials, time and untranslated types, and these docs. The audit found bugs in the core, which are fixed (listed in the M1b plan's Phase C log), and holes in the tests, which these cases now cover.

**The source-info filter.** The core adds one Hydra filter. It sits in `UsdImagingCreateSceneIndices`' overrides slot, right after the stage scene index, where paths are still USD paths. Under a `prosceniumSource` container it supplies what the chain drops:
- subset `familyName`;
- authored purpose visibility;
- `doubleSided`;
- UsdShade's resolved binding for each material purpose, and the purposes a prim binds `strongerThanDescendants`;
- USD's verdict on a mesh's materialBind family (`ValidateFamily`);
- the USD type of prims Hydra doesn't image;
- on gprims and point instancers, the authored attributes UsdImaging drops.

For prims UsdImaging doesn't image at all, it supplies `UsdImagingDataSourcePrim` (transform, visibility, purpose, authored extent, primvars), as UsdImaging does for prims without an adapter. Those data sources run on the filter's own stage globals, so a time change dirties exactly what they flag as time-varying. For curves, points and HermiteCurves without an authored extent it supplies USD's computed extent. Its containers read USD on each access, at the graph's time. It listens to the stage for edits Hydra doesn't notice.

| Case | Checked against USD | Found |
|---|---|---|
| GeomSubsets and indexed primvars (17 checks) | Captured primvars keep USD's indices and unflattened values. Each face's material is UsdShade's materialBind assignment, in the plan and in Blender through each object's slots, matched exactly. That covers faces in no subset, an unbound subset, a mesh with nothing bound, and subsets in another family or in none. A left-handed mesh (triangle, quad, triangle) has its corners reversed after the first, and every face-varying, vertex, uniform and varying value lands on its Blender domain to match `ComputeFlattened`; its face normals follow USD's orientation. An indexed constant displayColor reaches the object flattened. | Hydra binds subsets of any family, including one with no `familyName`; only materialBind subsets make slots. Overlapping materialBind subsets give the face to the first by name, with a warning; a family USD's `ValidateFamily` rejects is diagnosed with USD's reason, and families it accepts are not. A materialBind subset of points is ignored with a warning. A primvar named `sharp_face` (a Blender built-in) isn't transferred. A mesh with USD's default scheme, catmullClark, gets `subdivision-not-applied`. |
| Implicit shapes (13) | The cube, plane, sphere, cone, cylinder, capsule and a bicubic NURBS patch all become meshes. Only the inexact ones are diagnosed. Exact meshes' vertices are exactly the corners of USD's extent. Approximated meshes' vertices lie on the surface USD's parameters define, and span at least 90% of its extent on every axis. Faces point outward in Blender. World transforms and `doubleSided` (fallbacks included) match. | Hydra loses the Cube's authored `doubleSided = true` and keeps Plane's fallback true. Approximations are catmullClark cages: sphere 100 faces, capsule 90, cylinder 30, cone 20. The NURBS patch is displayed as its control hull (9 faces), which is accepted and diagnosed as an approximation: its bounds equal the control points', while the surface's midpoint, computed from the control points, is z = 1.5 under the hull's 2. |
| Nested native instances (17) | 360 drawn copies: Leaf (9 meshes) in Branch (4 leaves), in 10 Branch instances, 2 of them inside Tree instances, so three levels deep. Every copy matches USD: source and instance context, world transform, effective visibility (including invisible groups one and two levels above an instance root, and inside a prototype), inherited purpose, and displayColor (indexed on an outer root). Named primvars (string, bool, int2, float3, a three-element float array, and scalar string and float) match USD inheritance in value and shape; they come from each instance root's own record, since Hydra's instance aggregation keeps only an array's first element. Materials match UsdShade per copy, in the plan and in Blender, through strong outer and inner bindings (including OpenUSD #1571's case), a collection authored inside the asset, `material:binding = None`, a binding to a non-Material, and a binding without `MaterialBindingAPI`. | **A Hydra propagation bug** (below). There are 33 instancers and 216 plan meshes for the 360 copies, with at most 6 objects sharing one. Each leaf mesh's copies share one points buffer. |
| Time, edits, incremental capture (7) | 23 steps on two bridges over one stage, one capturing in full and one incrementally. The steps are times 1, 2, 2.5 and 3, then edits, each in turn:<br>- unchanged refreshes;<br>- a material parameter;<br>- a cube's size;<br>- a topology;<br>- added and removed prims;<br>- a subset's elementType, which changes its mesh's family verdict, and back;<br>- a familyName;<br>- guideVisibility on a prim and on an ancestor;<br>- doubleSided on a cube and on a mesh;<br>- a binding retarget and a strength change;<br>- a static HermiteCurves' transform, visibility and purpose;<br>- prototype content seen by two instances.<br><br>At every step the plan matches USD (transforms, visibility, purpose, displayColor, destinations, per-face materials for both purposes, points, doubleSided, placeholders, material parameters) and equals a new bridge's plan. Each step changes USD's values for exactly the prims it names. Animated HermiteCurves (transform and held visibility) match at each time. | Incremental captures equal full captures record by record (an absent instancer matrix counts as identity) and plan by plan. An unchanged refresh delivers no notices, copies nothing and plans identically. Dirtied prims whose records didn't change: `Blinker` at 2.5 (held visibility); `Aid` and `Aid2` after an ancestor's guideVisibility edit (records hold only each prim's own opinions); `Holder` after its strength change. |
| Untranslated types (14) | One placeholder per unsupported gprim and per point instancer, with an `untranslated-type` warning on its USD path. That covers basis curves, NURBS curves, points, HermiteCurves, a Volume, and basis curves and a point instancer inside native instances, with instance context per copy. Each keeps its world transform, effective visibility and purpose. An authored extent, or else USD's computed extent for curves and points, gives a bounding-box placeholder (a box mesh drawn as bounds); a point instancer or volume without an authored extent gives an empty marker. A point instancer's prototype prims get no objects. A mesh under unsupported basis curves is still built. | HermiteCurves aren't imaged: Hydra has only a typeless prim, without its own transform or visibility (from source reading and snapshot inspection). The filter supplies type, transform, visibility and purpose. |
| Large arrays (9) | A 512 × 512 quad grid: 263,169 points, 1,048,576 corners, a vertex float and face-varying UVs. The plan's arrays equal the authored arrays byte for byte, and Blender's equal the plan's. They are read-only contiguous buffers in `'f'`/`'i'`, and a buffer in the wrong format is refused. The plan-buffer `foreach_set` is at least 5× faster than from a list (the minimum of five runs of each). | Each attribute and corner transfer allocates under 1 KiB of Python memory (`tracemalloc`, which doesn't see Blender's own allocator). `polygons.foreach_set('loop_start')` allocates a 1 MiB temporary, 4 bytes per face. In one binary run, `foreach_set` took 0.09 ms from the plan buffer against 3.2 ms from a list. |
| Malformed input (14) | 11 broken topologies become placeholders, each with an `invalid-mesh` error whose message gives the reason expected from how it's built: an out-of-range index, a negative index, count mismatches, a two-corner face, a negative count, counts summing past `int`, a hole out of range, an unknown scheme or orientation, and missing or wrong-typed points. Faces Blender's `Mesh.validate()` deletes (one using a point twice, a later face on an earlier face's points in either winding) are left out with a `faces-left-out` warning instead, as Blender would repair them: the rest of each mesh builds, and per-face data and subset slots stay with their faces. Invalid primvars and subsets are skipped with reasons, and the meshes and their valid primvars still build. An empty mesh and a points-only mesh are planned without diagnostics and match USD's counts in Blender. Every Blender mesh passes `Mesh.validate()` unchanged. API misuse raises Python exceptions, and diagnostics have no duplicates. | A `timecode` shader input posts a Tf warning during capture, which becomes one diagnostic on the material's USD path. Wrong-typed points read as empty. Several reasons are PxOsd's own message text, which a USD upgrade can reword. |
| Bindings and purpose visibility (8) | A collection binding outside instances, purpose bindings for allPurpose, preview and full, and a binding without `MaterialBindingAPI` all match UsdShade. Effective purpose visibility matches `ComputeEffectiveVisibility`, including an opinion on an instance root. | **Two collection gaps** (below). Hydra flattens each purpose separately with no allPurpose fallback. Hydra reports a hidden proxy as visible, because purpose visibility isn't imaged. |
| Prim and material purposes per destination (9) | Default, proxy, render and guide prims: one guide explicitly visible, and one whose nearest opinion is `inherited`. A render prim hidden by `renderVisibility`, a mesh whose subsets the destinations bind differently, and a native instance with each purpose. The viewport shows exactly default, proxy and explicitly visible guide prims, and the render default and render prims, each once. Each destination's object has UsdShade's materials for its purpose, matched exactly. Prims shown in both with the same materials are one object; with different materials, two objects sharing one mesh, both with the right source and instance context. Blender's hide flags and object-linked slots match the plan, and every planned material is linked by an object (a proxy prim's `full` binding, which nothing displays, isn't planned). | The Phase B application ignored purpose. Hydra's graph resolves each purpose separately, but its bindings inside instances are unusable (the nested binding bug), so the core resolves them. |
| Normals, velocities, constant primvars, custom attributes (10) | Authored normals per point, per corner (indexed, with `primvars:normals` winning over the `normals` attribute) and per face are Blender's custom normals, and `corner_normals` match USD for every Blender corner, a left-handed mesh's reversed corners included. A catmullClark mesh's normals are ignored with a diagnostic. `velocities` are Blender's `velocity` attribute; `accelerations` stay a generic attribute; a primvar named `velocity` keeps the name. 16 constant primvars, one of each kind Blender holds, become ID properties on the object, matching USD's values under the plan's conversion. An int64 and an int64 array beyond 32 bits (both ways) are wrapped to their low 32 bits, with one warning each; each instance's object gets its instance root's tint and keeps its own gloss. Dropped attributes are listed exactly: three on a mesh, one on a placeholder, one inside a prototype (once per instance), none for unauthored, applied-schema, transform-op or subset-family attributes; adding and removing one updates an incremental capture. | UsdImaging passes only primvars and schema attributes to Hydra. The three constant primvars Blender can't hold (an asset path, a name over 63 bytes, the `proscenium_` prefix) are warned and not authored. Accelerations, the `velocity` name collision and the ignored normals are warned. |

**The nested-instance binding bug.** Every prototype level is re-rooted to the same placeholder path, `UsdImaging_NiPrototypeSceneIndex::GetPrototypePath()` (v26.03, and unchanged in `dev` at `5bc38c9`, from source reading). An inner instance root's binding to a material in the enclosing prototype is therefore re-rooted into the inner prototype.
- In the fixture, Moss's binding names a prim that doesn't exist, and Bark's names the inner prototype's own Bark: a different material, with no diagnostic.
- With `strongerThanDescendants` on the inner root, Hydra applies the strength but keeps the broken path. Both are known-gap checks.
- **The core doesn't use Hydra's flattened bindings.** The filter records UsdShade's binding for each prim. Inside a prototype, that covers everything the prototype authors. The core adds only what lies at or above each instance root: a strong binding there wins; otherwise the prototype's own binding; otherwise the instance root's.
- All 360 copies match UsdShade.

**Collection bindings: two gaps without a workaround.**
- **A collection outside the instance:** USD binds `Inside/Blade` through a collection while `Outside/Blade`, another instance of the same prototype, stays unbound. The plan binds neither.
- **A collection on the instanced asset's root:** `KitA` and `KitB` each bind their own `Looks/Bark`, the shape of the scene attached to [OpenUSD #3690](https://github.com/PixarAnimationStudios/OpenUSD/issues/3690) (open). The plan binds nothing.
- **Why:** in both, the collection names instance-proxy paths, which a prototype can't see.
- **What works:** a collection authored below the asset's root, inside the prototype, now matches UsdShade.

**A type-identity finding at the module boundary.** An `SdfPath` value made in the bridge's module isn't recognized by USD's own code: `HdMakeStaticCopy` posts "Unsupported type SdfPath". This is the same boundary as Phase B's `ArResolverContext`, now for a core type. It also blocks UsdImaging plugin adapters built outside `libusd_ms` on macOS: the adapter factory base class's `type_info` isn't exported either (an ad hoc experiment; see the plan's Hydra-native review). The filter therefore passes bound material paths as tokens, and the core maps them to Hydra paths. Values the core gives Hydra must be Vt's own types.

**Stage lifetime fix.** `Bridge(stage)` used to take a `UsdStageRefPtr`. Tf's Python converter for a `TfRefPtr` argument moves ownership from the Python object into C++ (`pxr/base/tf/pyPtrHelpers.h`), so releasing or deleting a bridge destroyed a stage its caller still held. The bridge now takes a `UsdStagePtr` and adds its own reference. The loading check "released bridge leaves a caller-held stage alive" covers it.

**Expiry can lag `release()`.**
- In 200 ad hoc iterations (macOS wheel), the root layer was still registered right after `release()` in 28, and gone within 50 ms in all.
- Another ad hoc run saw the layer gone before the bridge's weak stage pointer had expired (1 in 22).
- The cause wasn't identified. `~UsdStage` releases the root layer synchronously, so it isn't asynchronous teardown inside the stage.
- The check now waits up to 2 s for both and records the wait in `wheel.json`/`binary.json`.

### Limits and next gates

The prototype and correctness checks use small bespoke scenes. Untested:
- time-varying detection (Phase D), including animated visibility on an instance root's ancestor;
- deformation;
- translating point instancers (they are placeholders);
- performance at scale (Phase E), including the filter's UsdShade queries and computed extents per prim;
- a keyless UsdImaging adapter in place of the filter on Linux and Windows. On macOS it can't be manufactured: `libusd_ms` doesn't export the `type_info` of the adapter factory base class, so its `dynamic_cast` rejects a factory from another binary (ad hoc, M1b plan's Hydra-native review);
- layer muting, sublayer edits and variant switches in the edits case (ad hoc probes passed);
- animated unimaged prims inside a prototype;
- primvars with `elementSize > 1`: the bridge doesn't read elementSize (UsdImaging passes it through), so their counts fail validation and they're reported invalid;
- non-unit authored normals in rendering, and whether Blender's `velocity` expects USD's per-second units;
- texCoord3f and constant texCoords;
- a real Tf error during capture: only a warning has been exercised.

Zero-copy transfer is also measured separately by the `buffer_transfer` probe.

Not tested: Windows arm64 and other unsupported platforms, other Blender builds, installed extension lifecycle,
selection mapping, stage-setting fidelity, threading beyond the parallel read passes of capture and planning,
undo/save/reopen, production-scale data, or memory/performance regressions.

`release()` is explicit. A production binding would call it when its source is
released, to preserve the caller-release contract in
[In-Memory Sources](../spec/source-access.md#in-memory-sources). The bridge's native
objects and lazily queried scene indices are not persisted Blender state.

Native loading now holds on all three platforms for this module. The remaining gate is
the end-to-end prototype in the [M1b plan](../plans/M01b-evaluation-gate.md).
The current Python-only implementation decision remains unchanged pending M1b's
recorded decision.

## Windows x64

**Go.** All 55 checks pass in all three runtimes ("Feasibility" workflow, [run 38032882242](https://github.com/scottdmilner/proscenium/actions/runs/38032882242), `windows-latest`, 2026-10-10). Apart from paths and timings, every recorded fact matches macOS except those below.

| Item | Value |
|---|---|
| Runner | GitHub `windows-latest`, Windows Server 2025, AMD64 |
| Blender | 5.2.2 LTS, build hash `d13f752e3b9c`, portable zip |
| Embedded Python | binary: Blender's bundled 3.13.13 (MSC v.1944); wheel: uv-managed CPython 3.13.15 |
| OpenUSD | 0.26.3; all 37 `pxr` modules import in every runtime; MaterialX 1.39.4 |
| USD plugins | binary 52, wheel 46 (see below) |

- **The Windows wheel registers six fewer USD plugins than the binary:** `hdStorm`, `hioAvif`, `hioOiio`, `hioOpenEXR`, `sdrGlslfx`, and `usdShaders`.
  - **Cause: a Blender packaging bug.** Blender's USD build keeps these six plugins' resources in a separate `usd/plugin/usd/` directory. Their code is in `usd_ms`, like the rest. Blender's install rule copies that directory to a fixed `blender.shared/usd` on Windows (`source/creator/CMakeLists.txt:1996` at v5.2.2). That is right for the binary. For the wheel, though, the main USD resources go to `bpy/usd` while this directory still goes to `blender.shared/usd`, outside the wheel's only package, `bpy/`. Linux installs both to the same place. This was established from the published wheel's and zip's file lists, the pinned `lib-windows_x64` tree, and Blender's source, not by building a wheel.
  - **Observed effect** (second [run 38034363291](https://github.com/scottdmilner/proscenium/actions/runs/38034363291)): in the Windows wheel, `Sdr.Registry().GetShaderNodeByIdentifier("UsdPreviewSurface")` raises `Tf.ErrorException` from `usdShaders`' discovery plugin: "Could not find shader resource: shaderDefs.usda". The discovery code still runs, because it is compiled into `usd_ms`, but its resources are missing. The binary finds the node.
  - **Consequences:**
    - Code that queries Sdr for UsdPreviewSurface behaves differently in the Windows wheel, such as reading default input values.
    - The bridge's capture records Tf errors as diagnostics rather than raising them. In [run 38293887802](https://github.com/scottdmilner/proscenium/actions/runs/38293887802), the prototype's UsdPreviewSurface materials, whose shaders have an `info:id`, produced no Tf errors in the Windows wheel. That fits the source-reading inference that UsdImaging's material path consults Sdr only for shaders without one. It was observed for this fixture only.
    - The plugins the bridge uses (`usdImaging`, `hdsi`, `usdSkelImaging`) are present in every runtime. The binary is authoritative.
- **`PXR_USD_WINDOWS_DLL_PATH` is set:** to `blender.shared` in the binary and to the `bpy` directory in the wheel, alongside `PXR_MTLX_STDLIB_SEARCH_PATHS`. No `PXR_PLUGINPATH_NAME` is set.
- **A non-forced `Reload()` misses a rewrite within the same second,** in all three runtimes.
  - **Cause:** `SdfLayer::Reload` skips rereading when the layer's modification timestamp equals the stored one (`sdf/layer.cpp:1017-1023`, v26.03). On Windows, `ArchGetModificationTime` returns `_wstat64`'s whole-second `st_mtime` (`arch/fileSystem.cpp:186-197`, marked "this may need adjusting"); Linux and macOS use nanoseconds. OpenUSD `dev` has the same code.
  - **Observed** (second [run 38034363291](https://github.com/scottdmilner/proscenium/actions/runs/38034363291)): USD's timestamp for a layer had no sub-second part on Windows, and it did on macOS and Linux. An immediate second rewrite was missed, while a rewrite made 1.1 s later was seen.
  - **For M3's [File-Backed Refresh](../spec/source-access.md#file-backed-refresh):** a refresh that relies on non-forced reloads can miss a save made within a second of the previous read on Windows. Forced reloads or another change test avoid it; M3 decides.
- **Buffer transfer** (single runs, 1,000,000 points): attribute `position` 0.53 ms in the binary and 1.72 ms in the wheel; `vertices.co` 64.9 ms and 65.7 ms.

### Compiled Hydra bridge

**Passes:** 42 loading checks and 20 prototype checks in the bpy wheel, and the same in the Blender 5.2.2 binary ("Hydra bridge" workflow, [run 38293887802](https://github.com/scottdmilner/proscenium/actions/runs/38293887802), `windows-latest`, 2026-10-12; loading first passed in [run 38030083435](https://github.com/scottdmilner/proscenium/actions/runs/38030083435)). Every process exits 0. The loading checks are the macOS ones plus a pre-import check that the host had already loaded `usd_ms.dll`. The prototype results match macOS, with the same two diagnostics.

- **Build:** MSVC 19.44.35229 (tools 14.44.35207), loaded by `build.py` through Visual Studio's `vswhere` and `vcvarsall -vcvars_ver=14.44`; CMake and Ninja come from the dev group in `.venv`. No warnings at `/W4`. The runner also has Visual Studio 2026 installed, so without the pin a newer toolset would have built the module. (The first run selected the same toolset with the `ilammy/msvc-dev-cmd` action.)
- **Audit:** the module imports `usd_ms.dll`, `python313.dll`, `tbb12.dll`, `msvcp140.dll`, `vcruntime140.dll`, `vcruntime140_1.dll`, `kernel32.dll`, and four `api-ms-win-crt-*` DLLs, with no debug runtime. Linker version 14.44.
  - `tbb12.dll` is new since Phase A: the capture's parallel read pass uses `WorkParallelForN`. Blender ships that DLL, and the module loads in both hosts.
- **One USD per process:**
  - Wheel: `bpy\usd_ms.dll`, beside `bpy\__init__.pyd`.
  - Binary: `blender.shared\usd_ms.dll`.
  - In both, the image providing USD code to the module is that same file.
- **Loading:** the module's import of `usd_ms.dll` resolved to the copy the host had already loaded, though no DLL directory points at it. This confirms on this run what the research inferred from the loader's documented behaviour.

- **Phase C** ([run 38359009667](https://github.com/scottdmilner/proscenium/actions/runs/38359009667), 2026-10-13): 43 loading, 20 prototype and 118 correctness checks pass in both hosts.
  - The build had two `/W4` warnings in Phase C code: C4267 in `properties.cpp`, a `size_t` matrix index where Gf takes `int`, and C4458 in `prim_record.cpp`, a parameter named like a member. Both are fixed. Clang builds now add `-Wshadow-all -Wshorten-64-to-32`, which report both (checked against the run's sources) and two harmless lambda shadowings, now renamed. The next build, of commit `a6d8186` ([run 38361588537](https://github.com/scottdmilner/proscenium/actions/runs/38361588537)), has no warnings on Windows, nor on macOS with the new flags.
  - No Sdr message appears in the run's Windows logs or JSON. The probes don't save every diagnostic, so this shows only that Phase A's Sdr error didn't fail anything.

## Linux x64

**Go.** All 55 checks pass in all three runtimes ("Feasibility" workflow, [run 38032882242](https://github.com/scottdmilner/proscenium/actions/runs/38032882242), `ubuntu-latest`, 2026-10-10). Apart from paths and timings, every recorded fact matches macOS except those below.

| Item | Value |
|---|---|
| Runner | GitHub `ubuntu-latest`, kernel 6.17 (Azure), x86_64 |
| Blender | 5.2.2 LTS, build hash `d13f752e3b9c`, portable tarball |
| Embedded Python | binary: Blender's bundled 3.13.13 (GCC 14.2.1); wheel: uv-managed CPython 3.13.16 |
| OpenUSD | 0.26.3; all 37 `pxr` modules import in every runtime; MaterialX 1.39.4 |
| USD plugins | 52 in every runtime: macOS's set without `hgiMetal` and `hioImageIO`, plus `hgiVulkan` |

- **A non-forced `Reload()` saw an immediate second rewrite,** as on macOS; USD's layer timestamps have a sub-second part (second [run 38034363291](https://github.com/scottdmilner/proscenium/actions/runs/38034363291)).
- **Buffer transfer** (single runs, 1,000,000 points): attribute `position` 0.78 ms in the binary and 1.71 ms in the wheel; `vertices.co` 87.3 ms and 88.8 ms.

### Compiled Hydra bridge

**Passes:** 41 loading checks and 20 prototype checks in the bpy wheel, and the same in the Blender 5.2.2 binary ("Hydra bridge" workflow, [run 38293887802](https://github.com/scottdmilner/proscenium/actions/runs/38293887802), 2026-10-12; loading first passed in [run 38030083435](https://github.com/scottdmilner/proscenium/actions/runs/38030083435)). Every process exits 0. The prototype results match macOS, with the same two diagnostics. The module was built in `quay.io/pypa/manylinux_2_28_x86_64` and tested on `ubuntu-latest`.

- **Build:** GCC 14.2.1 (`gcc-toolset-14`), the compiler that built Blender's `libusd_ms.so`.
  - The only warning is libstdc++'s deprecated-header `#warning`, once per source file. It comes from USD's `tf/hashset.h` including `<ext/hash_set>`.
  - USD builds itself with `-Wno-deprecated` for this reason (`cmake/defaults/gccclangshareddefaults.cmake`). The bridge passes the same flag on GCC, and the build has no warnings ([run 38295477698](https://github.com/scottdmilner/proscenium/actions/runs/38295477698)).
- **Audit:**
  - `NEEDED`: `libusd_ms.so`, `libdl.so.2`, `libstdc++.so.6`, `libm.so.6`, `libgcc_s.so.1`, `libc.so.6`, and `ld-linux-x86-64.so.2`.
  - No RPATH or RUNPATH, and no libpython.
  - 250 undefined `pxrBlender` symbols (100 for the Phase A module).
  - Highest symbol versions GLIBC 2.14 and GLIBCXX 3.4.21, below Blender's floor.
- **Phase C** ([run 38359009667](https://github.com/scottdmilner/proscenium/actions/runs/38359009667), 2026-10-13): 42 loading, 20 prototype and 118 correctness checks pass in both hosts. The build has no warnings. The audit's `NEEDED` list and symbol versions are unchanged; the module now imports 374 USD symbols (`usd_import_count`).
- **One USD per process:**
  - Wheel: `bpy/lib/libusd_ms.so`.
  - Binary: `lib/libusd_ms.so` in the unpacked tarball.
  - In both, the image providing USD code to the module is that same file.
- **Loading:** with no search path embedded, the module's `libusd_ms.so` dependency resolved to the library the host had already loaded, matched by SONAME. This confirms on this run what the research inferred.

## Future Work

- Windowed (UI-mode) behavior: handler timing, undo with a window manager, and viewport interaction. Out of scope for this project.
