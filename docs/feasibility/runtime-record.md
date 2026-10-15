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
M1b adopted Hydra on this evidence (Phase F, [DECISIONS.md](../DECISIONS.md) "Evaluation front end and
core language"); the bridge itself remains feasibility code. Phase F also installed it from a per-platform
extension zip ([below](#distribution-m1b-phase-f)). The same checks pass on [Windows x64](#compiled-hydra-bridge) and
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

**USD warns about HermiteCurves on every platform, as expected.** UsdImaging posts "Datasource support not yet added for adapter 'UsdImagingHermiteCurvesAdapter'" (`UsdImagingPrimAdapter::GetImagingSubprims`) for each HermiteCurves prim. That is why Hydra doesn't image them, and the filter's supplied data covers it. Measured locally: it is posted while the bridge is built (twice for the untranslated scene's one prim, eight times for the edits scene's two) and again at release. Posted during a capture, it becomes one `tf-warning` diagnostic with no source, beside the `untranslated-type` warning that names each prim. Since Phase D, warnings posted while the bridge is built join its first capture's diagnostics too, without a source (one check). Only the release-time ones are still printed, since no capture follows a release.

**UsdShade warns about bindings without `MaterialBindingAPI`, as expected.** Two fixtures author one on purpose (bindings' `Legacy`, instances' `NoApi`). UsdShade honors it for compatibility and posts "Found material bindings on prim … but MaterialBindingAPI is not applied" each time it resolves it. Those posted while the bridge is built join the first capture's diagnostics as above. The ones still printed in CI come from the Python oracle's own UsdShade calls (traced for one call, ad hoc). Since Phase D the filter also reports such bindings itself, as `bindingsWithoutApi`, so the plan has a `binding-without-api` warning on each copy's own source, whether or not USD posts its warning (one check in each case; a mutation run without the fact failed both).

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
| Nested native instances (19) | 360 drawn copies: Leaf (9 meshes) in Branch (4 leaves), in 10 Branch instances, 2 of them inside Tree instances, so three levels deep. Every copy matches USD: source and instance context, world transform, effective visibility (including invisible groups one and two levels above an instance root, and inside a prototype), inherited purpose, and displayColor (indexed on an outer root). Named primvars (string, bool, int2, float3, a three-element float array, and scalar string and float) match USD inheritance in value and shape; they come from each instance root's own record, since Hydra's instance aggregation keeps only an array's first element. Materials match UsdShade per copy, in the plan and in Blender, through strong outer and inner bindings (including OpenUSD #1571's case), a collection authored inside the asset, `material:binding = None`, a binding to a non-Material, and a binding without `MaterialBindingAPI`. The leaf meshes are small but not trivial (since Phase D): a quad grid with a materialBind subset and indexed face-varying UVs, a box with indexed face-varying normals, a pyramid mixing quads and triangles, vertex and uniform primvars, and a left-handed strip. Every copy's Blender mesh matches its USD prototype: points, corners, UVs, custom normals and primvars on their domains, and the subset's faces take UsdShade's material in each copy. Each of the 40 NoApi copies gets a `binding-without-api` warning on its own source. | **A Hydra propagation bug** (below). There are 33 instancers and 216 plan meshes for the 360 copies, with at most 6 objects sharing one. Each leaf mesh's copies share one points buffer. The meshes are small (at most 9 points), so these are counts, not costs. |
| Time, edits, incremental capture (7) | 23 steps on two bridges over one stage, one capturing in full and one incrementally. The steps are times 1, 2, 2.5 and 3, then edits, each in turn:<br>- unchanged refreshes;<br>- a material parameter;<br>- a cube's size;<br>- a topology;<br>- added and removed prims;<br>- a subset's elementType, which changes its mesh's family verdict, and back;<br>- a familyName;<br>- guideVisibility on a prim and on an ancestor;<br>- doubleSided on a cube and on a mesh;<br>- a binding retarget and a strength change;<br>- a static HermiteCurves' transform, visibility and purpose;<br>- prototype content seen by two instances.<br><br>At every step the plan matches USD (transforms, visibility, purpose, displayColor, destinations, per-face materials for both purposes, points, doubleSided, placeholders, material parameters) and equals a new bridge's plan. Each step changes USD's values for exactly the prims it names. Animated HermiteCurves (transform and held visibility) match at each time. | Incremental captures equal full captures record by record (an absent instancer matrix counts as identity) and plan by plan. An unchanged refresh delivers no notices, copies nothing and plans identically. Dirtied prims whose records didn't change: `Blinker` at 2.5 (held visibility); `Aid` and `Aid2` after an ancestor's guideVisibility edit (records hold only each prim's own opinions); `Holder` after its strength change. |
| Untranslated types (14) | One placeholder per unsupported gprim and per point instancer, with an `untranslated-type` warning on its USD path. That covers basis curves, NURBS curves, points, HermiteCurves, a Volume, and basis curves and a point instancer inside native instances, with instance context per copy. Each keeps its world transform, effective visibility and purpose. An authored extent, or else USD's computed extent for curves and points, gives a bounding-box placeholder (a box mesh drawn as bounds); a point instancer or volume without an authored extent gives an empty marker. A point instancer's prototype prims get no objects. A mesh under unsupported basis curves is still built. | HermiteCurves aren't imaged: Hydra has only a typeless prim, without its own transform or visibility (from source reading and snapshot inspection). The filter supplies type, transform, visibility and purpose. |
| Large arrays (9) | A 512 × 512 quad grid: 263,169 points, 1,048,576 corners, a vertex float and face-varying UVs. The plan's arrays equal the authored arrays byte for byte, and Blender's equal the plan's. They are read-only contiguous buffers in `'f'`/`'i'`, and a buffer in the wrong format is refused. The plan-buffer `foreach_set` is at least 5× faster than from a list (the minimum of five runs of each). | Each attribute and corner transfer allocates under 1 KiB of Python memory (`tracemalloc`, which doesn't see Blender's own allocator). `polygons.foreach_set('loop_start')` allocates a 1 MiB temporary, 4 bytes per face. In one binary run, `foreach_set` took 0.09 ms from the plan buffer against 3.2 ms from a list. |
| Malformed input (14) | 11 broken topologies become placeholders, each with an `invalid-mesh` error whose message gives the reason expected from how it's built: an out-of-range index, a negative index, count mismatches, a two-corner face, a negative count, counts summing past `int`, a hole out of range, an unknown scheme or orientation, and missing or wrong-typed points. Faces Blender's `Mesh.validate()` deletes (one using a point twice, a later face on an earlier face's points in either winding) are left out with a `faces-left-out` warning instead, as Blender would repair them: the rest of each mesh builds, and per-face data and subset slots stay with their faces. Invalid primvars and subsets are skipped with reasons, and the meshes and their valid primvars still build. An empty mesh and a points-only mesh are planned without diagnostics and match USD's counts in Blender. Every Blender mesh passes `Mesh.validate()` unchanged. API misuse raises Python exceptions, and diagnostics have no duplicates. | A `timecode` shader input posts a Tf warning during capture, which becomes one diagnostic on the material's USD path. Wrong-typed points read as empty. Several reasons are PxOsd's own message text, which a USD upgrade can reword. |
| Bindings and purpose visibility (10; 13 since Phase E) | A collection binding outside instances, purpose bindings for allPurpose, preview and full, and a binding without `MaterialBindingAPI` all match UsdShade. Effective purpose visibility matches `ComputeEffectiveVisibility`, including an opinion on an instance root. A `binding-without-api` warning marks exactly the prim that binds without the API, and UsdShade's Tf warning for it, posted while the bridge is built, reaches the first capture's diagnostics once. | **Two collection gaps** (below), covered since Phase E by a workaround for OpenUSD #3690. Hydra flattens each purpose separately with no allPurpose fallback. Hydra reports a hidden proxy as visible, because purpose visibility isn't imaged. |
| Prim and material purposes per destination (9) | Default, proxy, render and guide prims: one guide explicitly visible, and one whose nearest opinion is `inherited`. A render prim hidden by `renderVisibility`, a mesh whose subsets the destinations bind differently, and a native instance with each purpose. The viewport shows exactly default, proxy and explicitly visible guide prims, and the render default and render prims, each once. Each destination's object has UsdShade's materials for its purpose, matched exactly. Prims shown in both with the same materials are one object; with different materials, two objects sharing one mesh, both with the right source and instance context. Blender's hide flags and object-linked slots match the plan, and every planned material is linked by an object (a proxy prim's `full` binding, which nothing displays, isn't planned). | The Phase B application ignored purpose. Hydra's graph resolves each purpose separately, but its bindings inside instances are unusable (the nested binding bug), so the core resolves them. |
| Normals, velocities, constant primvars, custom attributes (10) | Authored normals per point, per corner (indexed, with `primvars:normals` winning over the `normals` attribute) and per face are Blender's custom normals, and `corner_normals` match USD for every Blender corner, a left-handed mesh's reversed corners included. A catmullClark mesh's normals are ignored with a diagnostic. `velocities` are Blender's `velocity` attribute; `accelerations` stay a generic attribute; a primvar named `velocity` keeps the name. 16 constant primvars, one of each kind Blender holds, become ID properties on the object, matching USD's values under the plan's conversion. An int64 and an int64 array beyond 32 bits (both ways) are wrapped to their low 32 bits, with one warning each; each instance's object gets its instance root's tint and keeps its own gloss. Dropped attributes are listed exactly: three on a mesh, one on a placeholder, one inside a prototype (once per instance), none for unauthored, applied-schema, transform-op or subset-family attributes; adding and removing one updates an incremental capture. | UsdImaging passes only primvars and schema attributes to Hydra. The three constant primvars Blender can't hold (an asset path, a name over 63 bytes, the `proscenium_` prefix) are warned and not authored. Accelerations, the `velocity` name collision and the ignored normals are warned. |

**The nested-instance binding bug.** Every prototype level is re-rooted to the same placeholder path, `UsdImaging_NiPrototypeSceneIndex::GetPrototypePath()` (v26.03, and unchanged in `dev` at `5bc38c9`, from source reading). An inner instance root's binding to a material in the enclosing prototype is therefore re-rooted into the inner prototype.
- In the fixture, Moss's binding names a prim that doesn't exist, and Bark's names the inner prototype's own Bark: a different material, with no diagnostic.
- With `strongerThanDescendants` on the inner root, Hydra applies the strength but keeps the broken path. Both are known-gap checks.
- **The core doesn't use Hydra's flattened bindings.** The filter records UsdShade's binding for each prim. Inside a prototype, that covers everything the prototype authors. The core adds only what lies at or above each instance root: a strong binding there wins; otherwise the prototype's own binding; otherwise the instance root's.
- All 360 copies match UsdShade.

**Collection bindings: two gaps, covered since Phase E by a workaround for OpenUSD #3690** ([below](#collection-bindings-inside-instances-workaround-for-openusd-3690)).
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

### Time-sampled data detection (M1b Phase D)

**Settled with the user (2026-10-13): the core evaluates one time code per capture.** It doesn't ask Hydra what varies over an interval. A higher layer can cache several evaluated frames when a representation needs them.

The signal the milestone first proposed, `HdSampledDataSource::GetContributingSampleTimesForInterval`, is a motion-blur API. Its header (`hd/dataSource.h`, v26.03) defines the interval as "a shutter window of interest… relative to the current frame". It returns the sample times "such that the caller can reconstruct the signal over the shutter window", and may return boundary samples outside the window. It returns false when the value "is uniform across the shutter window". Blender computes its own motion blur, so a Blender display has no shutter window to ask about.

An ad hoc query over frame ranges, since removed, behaved as that contract says. It reported:
- the bracketing samples, beyond the window, for attribute values;
- the window's ends for flattened transforms and skinned points;
- nothing for a zero-width window at a sample frame.

It also reported no visibility at all, Hydra's own or an instancer's mask. Those are motion-blur semantics, not a frame-range variance detector, so they aren't recorded as gaps.

The `animation` case (`cases/animation.usda`, 6 checks) checks what per-frame capture needs instead. Each prim varies in one kind of value or in none, with samples at 1 and 3 (held values also at 2):
- points, including equal samples and a single sample;
- static prims one and two levels under an animated ancestor, and an instance under one;
- visibility: a prim's own, an ancestor's, and an instance root's ancestor's;
- topology;
- primvar values, and indices alone;
- subset indices;
- animated `guideVisibility`;
- HermiteCurves;
- a computed extent;
- one skinned mesh.

**Status: passes on all three platforms.** All 125 correctness checks pass in the bpy wheel and the Blender 5.2.2 binary on macOS arm64, Windows x64 and Linux x64, with the same findings everywhere ("Hydra bridge" workflow, [run 38636577232](https://github.com/scottdmilner/proscenium/actions/runs/38636577232), commit `4ae78fb`, 2026-10-14). The loading (42; 43 on Windows) and prototype (20) checks pass in the same run, and no build has a compiler warning. Since that run, warnings posted while a bridge is built reach its first capture, and bindings without `MaterialBindingAPI` get their own warning: 128 checks pass in both hosts on all three platforms (bindings 10, instances 19), with the same printed warnings everywhere and no compiler warnings ([run 38642723300](https://github.com/scottdmilner/proscenium/actions/runs/38642723300), commit `a1c8b80`).

- **Direct USD is the oracle.** `ValueMightBeTimeVarying` on every authored attribute a value depends on reports exactly the values built to vary (one check). Those attributes include ancestors' transform ops and visibility, purpose visibility, primvar indices, subset indices, and the bound skeleton's animation. Like everything else here, it reports two equal samples as varying and a single sample as not (one check).
- **Time-change dirties are exact.** At 1 → 1.5 → 2 → 3, each change dirties exactly the varying values (one check), with coarse locators for transforms and visibility (`xform`, `visibility`). That covers:
  - visibility, as the instancer's `instancerTopology/mask` for the instance copy;
  - instance transforms, as the instancer's `hydra:instanceTransforms`;
  - the filter's computed extent;
  - the skeleton's resolved transforms beside the skinned points.

  Equal samples are dirtied too. This is the change discovery per-frame capture relies on.
- **Values at each time.** At 1, 1.5, 2, 3 and back at 1, the plan from a full capture and from an incremental capture matches USD (two checks). That covers:
  - transforms and visibility;
  - points, with Body's skinned points matching UsdSkel's `ComputeSkinnedPoints`;
  - topology, and per-face materials from animated subsets;
  - primvars with animated values or indices, and constant primvars as object properties;
  - the guide's visibility in the viewport;
  - placeholder bounds from the computed extent.

  The skinned check holds only because every transform in the scene is identity, so skeleton space is the mesh's local space.

**Two filter bugs found and fixed:**
- **Animated purpose visibility was read at default time.** The filter read authored `guideVisibility` (and proxy and render visibility) with `Get()`, which reads the default value and ignores time samples (found by reading the code). It now hands out UsdImaging's attribute data sources (`UsdImagingDataSourceAttributeNew`) on its own stage globals. These read at the graph's time and flag themselves as time-varying, so a time change dirties them. In a mutation run that read the opinion once, at the earliest time, the values check failed (Aid visible at 2).
- **Animated subset indices were never dirtied** (measured). UsdImaging's subset data source reads them at the current time but never flags them as time-varying, so an incremental capture kept the previous subset assignment. The filter now flags a subset whose `indices` might vary. In a mutation run without that flag, the dirties check failed, and so did the incremental check when run alone (wrong at 2 and 3).

**Other findings:**
- **USD's family verdict covers default time.** `UsdGeomSubset::ValidateFamily` checks the default value as well as every sample. A partition authored only as time samples is rejected ("Number of unique indices at time DEFAULT does not match the element count"). Seen ad hoc before the fixture's subsets gained defaults.
- **Skeletons are drawn as hidden guides.** UsdSkelImaging images a Skeleton as a bone mesh with guide purpose, so the plan has a hidden object for it.
- **Skinning inputs stay on the mesh.** UsdSkel's primvars on the skinned mesh are planned as data: `skel:jointIndices` and `skel:jointWeights` as attributes, and `skel:geomBindTransform` as an object property, though skinning has already consumed them.
- **The filter rebuilds more than it needs to on a time change.** It rebuilds a prim's facts whenever Hydra or its own flags dirty it, though only computed extents hold a value that goes stale (measured ad hoc with a temporary counter: 16 rebuilds per change on this scene; an ad hoc build that invalidated only on extent and points dirties rebuilt 3, with every check passing). Not changed. Phase E imports one frame only, so its cost is left for M4.

#### For M4: evaluating frames

The "Time-sampled data representation" row compares per-time-code snapshots with animation data. What M1b establishes for it:
- **Each frame is one capture.** Capture at a time code gives values that match USD at that time. A time change dirties exactly what varies, so an incremental capture copies only that (measured ad hoc on this scene: 25 of 40 prims per change, and none for a repeat of the same time).
- **Caching several frames is a layer above capture.** For a baked or keyed representation, that layer evaluates the frames it needs and keeps what changed. Two sources can tell it what changed:
  - **The dirties between successive captures.** These are exact here, including visibility and values Hydra computes (flattened and instance transforms, skinned points). Equal samples are dirtied anyway, so dirtied values may be unchanged; comparing values, or array identity, settles it.
  - **Direct USD**, when a representation needs authored keys rather than evaluated frames: `GetTimeSamplesInInterval` on the attributes a value depends on, for example to key held visibility exactly on its samples. The core must then know each value's dependencies, including what the imaging chain computes (a cube's `size` behind its generated points, a skeleton's animation behind skinned points). Hydra's adapters already encode those dependencies.
- **Not needed:** Hydra's interval query, which answers a motion-blur question.
- **Untested:** value clips, splines, point instancers, animated material parameters, skinning beyond one linear-blend skin with identity transforms, and the cost of capturing every frame of a range at scale (Phase E measures one frame only).

### Measurements (M1b Phase E)

Blender's USD importer (`bpy.ops.wm.usd_import`) against the prototype, importing one time code. Run on the reference hardware (M1 Max, 32 GB, macOS 26.5.1, AC power) in the Blender 5.2.2 binary (`d13f752e3b9c`), 2026-10-14, with the planner building meshes in parallel and the [OpenUSD #3690 workaround](#collection-bindings-inside-instances-workaround-for-openusd-3690) in place. Reproduce with:

```sh
uv run python tools/feasibility/hydra_bridge/build.py
uv run python tools/feasibility/hydra_bridge/measure/run.py   # stress scenes and ALab, about 6 minutes
```

The full statistics, with ranges and per-stage tables, go to `build/hydra-bridge/measure/summary.md` (not committed).

**CI.** The harness runs on one small scene (instances-100, every mode) on macOS, Windows and Linux; all runs completed in [run 38676508604](https://github.com/scottdmilner/proscenium/actions/runs/38676508604) (commit `b0bb4ce`), and again in [run 38677751979](https://github.com/scottdmilner/proscenium/actions/runs/38677751979) (commit `06dd5e9`), where Linux and Windows report no live heap and macOS reports it. CI's numbers aren't recorded. In both runs, all 131 correctness checks pass in both hosts on all three platforms (bindings 13, instances 19), with the loading (42; 43 on Windows) and prototype (20) checks, and no compiler warnings.

**Method:**
- **Runs.** Each run is a fresh binary process with factory startup and an empty scene. There are three runs per scene and mode, alternating, with the OS file cache warm. Figures below are medians, and the ranges are in the summary. Apart from scenes under 0.1 s, the widest range came from a sequence's first run: 1.56 s against a 0.41 s median, for the default importer on mesh-2048.
- **Run-to-run variation.** Between runs of the whole set, the matched importer took 3.23 s, 3.45 s and 3.24 s on ALab, so ratios are taken within one run.
- **Sampling.** A parent process samples the run every 10 ms with psutil: resident memory, CPU time and threads, plus the physical footprint on macOS (Activity Monitor's figure), which is the counter reported here. The child marks each stage boundary with:
  - its CPU time;
  - its lifetime peak footprint;
  - its **live heap**: bytes malloc has handed out and not taken back (`malloc_zone_statistics`).
- **Baseline.** Memory is relative to the run's empty process: 130 MB for the importer, and 139 MB for the prototype, which has already imported the module and `pxr`.
- **Importer configurations:**
  - **defaults**;
  - **matched**: every purpose and invisible prims imported; no UsdPreviewSurface conversion, unit scaling, lights, cameras, curves, points, volumes or skeletons (`measure/child.py`);
  - **expanded**: matched, with scene instancing off.
- **ALab** is imported at time 1004 through a measurement entry point (`measure/alab_entry.py`). It is a root layer over `entry.usda` that deactivates the 111 prims the prototype doesn't translate: 51 lights, 33 NurbsCurves, 21 PointInstancers, 5 `ALAudio` prims and 1 camera. Three RectLights inside native-instance prototypes (6 copies) can't be deactivated from a stronger layer and remain.

**Initial synchronization**, from opening the file to the first depsgraph evaluation (wall time and peak footprint):

| Scene | Content | Importer defaults | Importer matched | Importer expanded | Prototype | Prototype vs matched |
|---|---|---|---|---|---|---|
| mesh-64 | 1 mesh, 4,225 points | 0.05 s, 2 MB | 0.05 s, 2 MB | 0.03 s, 1 MB | 0.05 s, 2 MB | about the same |
| mesh-2048 | 1 mesh, 4.2M points, face-varying UVs | 0.41 s, 826 MB | 0.37 s, 799 MB | 0.35 s, 835 MB | 1.07 s, 1,330 MB | 2.89× time, 1.67× memory |
| prims-10000 | 10,000 cubes, 2 materials | 1.16 s, 516 MB | 1.14 s, 528 MB | 1.13 s, 521 MB | 1.68 s, 860 MB | 1.48×, 1.63× |
| instances-1000 | 1,000 instanced clusters of 10 instanced leaves (1,089-point grids); 2 materials bound at the cluster roots | 0.13 s, 30 MB | 0.14 s, 30 MB | 2.43 s, 1,944 MB | 0.76 s, 335 MB | not the same work (below) |
| animation | a deforming 66k-point grid and 1,000 animated cubes | 0.21 s, 101 MB | 0.16 s, 105 MB | 0.19 s, 107 MB | 0.19 s, 99 MB | 1.18×, 0.94× |
| ALab | the measurement entry point | 4.72 s, 1,543 MB | 3.24 s, 1,798 MB | 5.26 s, 3,092 MB | 3.50 s, 3,112 MB | 1.08×, 1.73× |

**On ALab both sides build the same geometry.**

| | Meshes | Vertices | Materials | Objects |
|---|---|---|---|---|
| Matched importer | 3,945 | 7,615,582 | 801 | 6,832 (1,417 collection instances) |
| Prototype | 3,946 (one is a placeholder's bounds) | 7,615,590 | 806 | 7,018 |

The default importer is slower than the matched one because it also builds 5,074 shader nodes and 1,611 images.

**Prototype stages on ALab:**

| Stage | Wall | Cores | Live heap at end |
|---|---|---|---|
| Stage open | 0.58 s | 2.2 | 95 MB |
| Bridge construction | 0.41 s | 5.4 | 140 MB |
| Capture (including the #3690 workaround's 0.04 s) | 0.46 s | 8.0 | 656 MB |
| Planning | 0.24 s | 5.9 | 1,560 MB |
| Transfer | 0.06 s | 1.0 | 1,564 MB |
| Construction | 1.55 s | 3.8 | 2,938 MB |
| First evaluation | 0.08 s | 2.5 | 3,028 MB |

The Hydra stages (bridge construction through transfer) take 1.15 s; Blender construction and evaluation take 1.62 s. CPU time for the whole synchronization:
- matched importer: 14.0 s, in 3.24 s of wall time (4.3 cores on average);
- prototype: 14.7 s, in 3.50 s (4.2 cores).

**Against Phase F's performance criterion** (ALab, matched importer; tentative here, made final unchanged by the user in Phase F), all three parts hold:
- time: 1.08×, within 2×;
- peak memory: 1.73×, within 2×;
- the Hydra stages (1.15 s) take less time than Blender construction (1.62 s).

They held only after planning went parallel: with serial planning, the Hydra stages took 2.12 s against 1.91 s (time 1.43×, memory 1.76×).

**Findings:**
- **Planning.** In the first run of the set it was serial: one core in every scene, and the largest Hydra stage on ALab (1.20 s) and on the large mesh (0.62 s of the prototype's 1.01 s). Capture and bridge construction were already parallel.
  - **Where planning's time went**, from timers in the planner (medians of three runs of a serial build, when ALab's planning took 1.36 s):

    | Part | ALab | mesh-2048 |
    |---|---|---|
    | Building meshes (`BuildMesh`), one at a time | 1.30 s (3,945 meshes) | 0.62 s |
    | — USD's topology validation (`PxOsdMeshTopology::Validate`) | 0.55 s | 0.30 s |
    | — finding the faces Blender would delete | 0.28 s | 0.16 s |
    | — primvars to attributes | 0.31 s | 0.06 s |
    | — the corner layout | 0.12 s | 0.08 s |
    | — material slots, and the bridge's own range checks | 0.04 s | 0.02 s |
    | Objects for every drawn copy, with materials and diagnostics | 0.02 s | 0.00 s |
    | Reading the records (already parallel) | 0.03 s | 0.00 s |

    For one large mesh, half the time is USD's validation, which the bridge calls as a single function.
  - **Meshes are now built in parallel** (`Planner::BuildMeshes`). Everything that adds to the plan still runs afterwards in prim order: meshes, objects, materials, diagnostics and the instance resolver's cache.

    From two runs of all modes, both before the #3690 workaround:

    | | ALab planning | ALab sync | Hydra stages | 4.2M-point mesh planning |
    |---|---|---|---|---|
    | Serial | 1.20 s (1.0 core) | 4.61 s | 2.12 s | 0.62 s |
    | Parallel | 0.26 s (5.7 cores) | 3.69 s | 1.27 s | 0.61 s |

    - **Other scenes** were unchanged within their ranges.
    - **The threads contend.** Mesh building's time, summed over threads, rose from 1.30 s to 2.00 s. This is recorded for the production core under [For production planning](#for-production-planning-m8).
    - **The plan is unchanged.** All 128 correctness checks pass. On ALab, a canonical digest of the plan is the same for the committed serial planner and for the new code, on one thread (`PXR_WORK_THREAD_LIMIT=1`) and on all threads. The digest covers every object with its mesh contents and materials, plus the diagnostics, in an order-free form.
  - **The plan's order varies between processes,** even on one thread and with the committed planner, though its content doesn't (ad hoc, ALab). The cause was not investigated.
  - **Duplicate meshes:** ALab's 3,945 plan meshes hold 3,369 distinct contents (same digest), so content deduplication would remove 576 more meshes (ad hoc).
- **The prototype's extra peak is what the bridge holds while Blender data is built.**
  - On ALab the live heap is 3,031 MB after synchronization. Releasing the bridge, its snapshot and the plan frees 1,453 MB; the harness drops all three together. Dropping the stage frees 82 MB more, and deleting the Blender data frees the remaining 1,460 MB.
  - By stage, capture adds 516 MB of live heap (the snapshot) and planning adds 904 MB (the plan).
  - The harness keeps the plan until release, though construction no longer needs it. Dropping it earlier would lower what is retained (inferred, not measured).
- **Freed memory isn't returned at once.** After deleting each run's data, the live heap is back to 4–37 MB on every scene, on both sides, so neither side was found to leak. The footprint can stay high: on mesh-2048 it was 1,240 MB with 4 MB of live heap. So retained memory is judged by live heap. The finding was ad hoc, in the wheel: with the bridge released on ALab, the live heap was back to within 12 MB of the opened stage, while in three runs the footprint stayed 67–570 MB above it.
- **Depsgraph evaluation.**
  - The importer evaluates the depsgraph inside its operator: requesting the evaluated depsgraph afterwards added nothing (ad hoc, in the wheel, on prims-10000).
  - On the same scene, the prototype's construction added 138 MB of live heap and its first evaluation 397 MB, together comparable to the importer's 500 MB.
  - Evaluated copies hold their memory until the next evaluation. Deleting ALab's imported data left 1.7 GB of live heap until a depsgraph update, and 27 MB after one (ad hoc), so the harness evaluates after deleting.
- **Scene instancing in the importer drops materials bound at or above an instance root** (measured on instances-1000 and on the 100-cluster smoke scene).
  - **What it builds.** With instancing on (defaults and matched), the importer builds 1 mesh and 1,010 collection instances, but no materials. With it off (expanded), it honors the bindings, building 10,000 meshes in 2.43 s and 1,944 MB. The prototype honors them with 2 meshes, one per material variant, shared by 10,000 objects (0.76 s, 335 MB).
  - **Why** (from the Blender 5.2.2 source):
    - An instance becomes an empty that instances a collection (`USDInstanceReader`, created in `usd_reader_stage.cc` when `support_scene_instancing` is on). The collection is built once per USD prototype from `UsdStage::GetPrototypes()`.
    - A mesh in that collection resolves its material on the prototype's own prim (`compute_bound_material` in `usd_reader_mesh.cc`, through `ComputeBoundMaterial`). Under `/__Prototype_N`, the instance root and its ancestors aren't on the prim's path, so their bindings are never seen.
    - Nothing on the instancing empty carries a material.
    - USD shares one prototype among instances whose roots bind different materials, so one collection couldn't show both in any case.
  - **Checked ad hoc in the wheel.** With the smoke scene's binding moved onto the leaf mesh inside the asset, the instancing importer imported the material and assigned it.
- **Sharing at scale** (carried in from Phase C). ALab's plan has 3,945 meshes for 6,679 composed mesh copies, the same count as the instancing importer's meshes. The expanded importer builds 6,679 meshes and peaks 1.29 GB higher than matched.
- **The filter's per-prim USD queries** run while the bridge is built, as the graph first reads each prim.
  - On ALab: 9,011 fact builds take 0.52 s of CPU, summed over threads, out of the stage's 2.16 s. Resolving bindings for each material purpose takes 0.34 s of that.
  - On prims-10000: 0.95 s of 1.09 s, of which bindings take 0.75 s.
  - The family verdict, dropped-attribute scan and computed extents take at most 0.07 s on any scene.
  - Times come from timers in the filter (`src/fact_timings.*`), not a profiler.
- **Blender construction.** The prototype's per-object work runs on one core: 0.63 s for 10,000 objects in prims-10000, and 0.32 s on instances-1000. Large meshes construct on 5 cores (mesh-2048).
- **Animation is left live by the importer.** It adds Mesh Sequence Cache modifiers and Transform Cache constraints (1 and 1,000 on the animation scene; 355 and 10 on ALab), which read USD when the frame changes. The prototype's result is static at the imported time. Frame changes are not measured.

**Not measured:**
- Windows and Linux: CI runs the harness on one small scene only, to keep it working, and records no numbers.
- Cold-cache opens; the wheel host.
- Frame changes, and the filter's rebuilds on a time change (left for M4).

The memory counters for Windows (working set, peak working set) and Linux (resident set) are implemented but haven't been checked against another tool. **The live heap is read on macOS only in the Blender binary.** Blender's release builds replace malloc with TBB's proxy on Linux and Windows x64 (`WITH_TBB_MALLOC_PROXY`, `build_files/cmake/config/blender_release.cmake`), which glibc's `mallinfo2` doesn't see: it read 0 MB throughout on CI. The harness therefore reports no live heap there, and none on Windows, whose C runtime has no such call. The bpy wheel turns the proxy off (`bpy_module.cmake`), so `mallinfo2` would apply in a wheel run on Linux (not measured).

#### Collection bindings inside instances (workaround for OpenUSD #3690)

Phase C's two collection gaps broke the prototype's contract to resolve bindings as USD does, so Phase E adds a workaround in the core (with the user, 2026-10-14). It is labeled in the code as a workaround for [OpenUSD #3690](https://github.com/PixarAnimationStudios/OpenUSD/issues/3690) (open, "Missing material binding on propagated prototype"). The collection outside an instance shares #3690's cause; no separate upstream issue was found for it.

- **What it does** (`src/copy_bindings.*`):
  - **Detection.** At capture, after the graph advances, the core finds the instances that a binding collection reaches: its membership includes the instance root or a path below it, or it uses a path expression, which is assumed to reach anywhere. Membership is evaluated in the namespace where the collection is authored, instance proxies included.
  - **Resolution.** For those instances only, UsdShade resolves every imageable prim and subset on its instance-proxy path, for allPurpose, preview and full (`ComputeBoundMaterials`, in parallel).
  - **Planning.** The planner takes those answers for those copies, mapping each USD material to the Hydra material that draws it. Every other copy keeps the per-prototype resolution, which matches UsdShade there.
  - **Cost control.** A first pass visits each unique prim once, the stage's and each prototype's, and stops when no prim binds a collection.
  - **Caching.** The result is cached in the source-info filter until a binding or collection edit, or a resync.
- **Checks** (bindings case, 13 checks; was 10):
  - The collection on `Inside/Blade` binds it and not `Outside/Blade`, as UsdShade does.
  - `KitA` and `KitB` each bind their own `Bark`, as UsdShade does.
  - The workaround covers exactly the reached instances (Inside, KitA, KitB).
  - After a collection edit, an incremental capture moves the binding from Inside to Outside.
  - A known-gap check asserts that Hydra's own bindings still miss these: Green only on `Loose`, `Bark` nowhere. It stops reproducing when Blender's USD carries a fix, and the workaround can then go.
- **Mutation runs.** Each new check failed when the behavior it guards was removed:
  - workaround off: the first check fails;
  - never recomputed after edits: the edit check fails;
  - no scoping: the coverage check fails, reaching Outside and Rigged too.

  The instances case's 19 checks passed in all three runs. All 131 correctness checks pass in the wheel and the binary (macOS).
- **Cost** (ad hoc, in the wheel, medians of three captures):

  | Scene | Capture | The workaround | Copies resolved |
  |---|---|---|---|
  | instances-1000, no binding collection | 0.012 s | 0.001 s | 0 |
  | instances-1000, with a collection on `/World` reaching all 1,000 instances | 0.209 s | 0.185 s | 21,000 |
  | ALab, no binding collection | 0.488 s | 0.044 s (the first pass, over about 23,000 unique prims) | 0 |

  Planning time was unchanged. In the recorded harness run, the workaround took 0.044 s of ALab's 0.46 s capture in the binary.
- **Limits:**
  - Only USD's three material purposes are covered. Another purpose keeps the per-prototype resolution.
  - A path-expression collection sends every instance through per-copy resolution.
  - Every incremental capture after a binding or collection edit recomputes the whole result.

#### For production planning (M8)

What the prototype's planner leaves for a production core to address:
- **Parallel mesh building contends for something** (measured, cause not investigated). With meshes built in parallel on ALab, the time inside `BuildMesh`, summed over threads, rose from 1.30 s to 2.00 s (1.71 s in the recorded run):

  | Part | Serial | Parallel |
  |---|---|---|
  | Primvars | 0.31 s | 0.71 s |
  | Layout | 0.12 s | 0.21 s |
  | Deleted faces | 0.28 s | 0.35 s |
  | USD's validation | 0.55 s | 0.68 s |

  The timers sum each call's wall time (`steady_clock`), not CPU time, so waiting and preemption count. Causes to rule out:
  - **the allocator:** every primvar gathers into a new array, after building a per-element source table (`SourceElements`, 8 bytes per element);
  - **first-touch page faults** on those fresh arrays, and memory bandwidth;
  - **slower cores:** the M1 Max's two efficiency cores run slower than its eight performance cores.

  A production core should profile the parallel pass, for example with Instruments' Time Profiler and System Trace, before tuning it. Reusing buffers, and skipping the source tables when the layout is the identity, are candidates.
- **One large mesh is still built on one thread.** Half of it is USD's validation, a single call. The M1b plan's Phase E log lists the options.

### Distribution (M1b Phase F)

The bridge shipped as users would get it from a GitHub release: Proscenium's extension zip for one platform, installed from disk into the Blender binary. Reproduce with:

```sh
uv run python tools/feasibility/hydra_bridge/build.py
uv run python tools/feasibility/hydra_bridge/distribution.py package   # build/hydra-bridge/dist/proscenium-0.1.0-<platform>.zip
uv run python tools/feasibility/hydra_bridge/distribution.py install
```

- **The zip.** `distribution.py package` copies `src/proscenium`, adds the module and its `build.json` to `core/`, and sets the manifest's `platforms` to this platform alone. The extension CLI from the bpy wheel then validates the copy, builds it with `--split-platforms` (which names the zip for the platform), and validates the zip. This is a test zip: `tools/build_extension.py`, the product build, doesn't take the bridge. Its six files are the extension's four, the module and `build.json`; it bundles no USD.
- **Three sessions of the Blender binary**, sharing one empty user directory (`BLENDER_USER_RESOURCES`), without `--factory-startup` so preferences carry over:
  1. **Install.** A copy of the zip naming another platform is refused ("This platform (macos-arm64) isn't one of (windows-x64)"; the operator still reports `FINISHED`, so the check is that nothing was installed). The real zip installs into `user_default`, Install from Disk's repository, and is enabled; enabling doesn't load the compiled module. Preferences are saved. 7 checks.
  2. **A new session.** The extension is enabled from the saved preferences and loaded at startup. `bl_ext.user_default.proscenium.core._hydra_bridge` loads from the installed package, and the loading checks (42) and prototype checks (20) pass against it. Disabling turns the extension off and leaves the compiled module imported, as Python never unloads one; re-enabling imports the same module object, which still captures. 8 checks.
  3. **Uninstall,** in a session where the compiled module was never loaded, removes the installed files and disables the extension. 6 checks.
- **Results.** macOS arm64 (reference hardware, Blender 5.2.2 binary, 2026-10-14): all pass. **Windows x64 and Linux x64: pending** the workflow's `distribution` jobs, which install the zip each build job uploads on a fresh runner with no build tree.
- **Untested:**
  - a download through a browser and a release page (macOS quarantine; the probe installs a locally built file);
  - updating or uninstalling while the module is loaded, which a Windows file lock may refuse (inferred), and an update to a different build in the same session, whose module name and converters are already registered (research §6);
  - Blender versions other than 5.2.2, and `blender_version_max`, which the zip doesn't set yet.

### Limits and next gates

The prototype and correctness checks use small bespoke scenes. Untested:
- animated values beyond the animation case: value clips, splines, point instancers, animated material parameters, and skinning under non-identity transforms or instancing;
- deformation other than one linear-blend skin (blend shapes, dual quaternions, several influences per point);
- dropping UsdSkel's primvars from a skinned mesh's planned data;
- translating point instancers (they are placeholders);
- performance on Windows and Linux, with a cold file cache, and across frame changes (Phase E measured macOS only, one time code per run);
- a keyless UsdImaging adapter in place of the filter on Linux and Windows. On macOS it can't be manufactured: `libusd_ms` doesn't export the `type_info` of the adapter factory base class, so its `dynamic_cast` rejects a factory from another binary (ad hoc, M1b plan's Hydra-native review);
- layer muting, sublayer edits and variant switches in the edits case (ad hoc probes passed);
- animated unimaged prims inside a prototype;
- primvars with `elementSize > 1`: the bridge doesn't read elementSize (UsdImaging passes it through), so their counts fail validation and they're reported invalid;
- non-unit authored normals in rendering, and whether Blender's `velocity` expects USD's per-second units;
- texCoord3f and constant texCoords;
- a real Tf error during capture: only a warning has been exercised.

Zero-copy transfer is also measured separately by the `buffer_transfer` probe.

Not tested: Windows arm64 and other unsupported platforms, other Blender builds, the installed extension lifecycle
beyond [Distribution](#distribution-m1b-phase-f)'s, selection mapping, stage-setting fidelity, threading beyond the parallel read passes of capture and planning,
undo/save/reopen, correctness on production-scale data (ALab is measured for cost only, on macOS), or
memory/performance regressions.

`release()` is explicit. A production binding would call it when its source is
released, to preserve the caller-release contract in
[In-Memory Sources](../spec/source-access.md#in-memory-sources). The bridge's native
objects and lazily queried scene indices are not persisted Blender state.

Native loading holds on all three platforms for this module, and the prototype's correctness,
measurements and distribution are recorded. On that evidence M1b adopted Hydra, with a C++ core
(Phase F of the [M1b plan](../plans/M01b-evaluation-gate.md#phase-f-log), and
[DECISIONS.md](../DECISIONS.md) "Evaluation front end and core language").

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
