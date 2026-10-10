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
| macOS arm64 | **Go.** All 49 checks pass in all three runtimes. |
| Windows x64 | Pending: CI run (Phase B). |
| Linux x64 | Pending: CI run (Phase B). |

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
  - An immediate second rewrite was also detected without `force`. This was on APFS with nanosecond mtimes; other filesystems are pending CI.
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

## Compiled Hydra bridge — macOS arm64

**Verdict: feasible on the tested Blender 5.2.2 / USD 0.26.3 build.** A standalone
Python extension links to Blender's installed `libusd_ms.dylib`, receives the
caller's `Usd.Stage` directly, and consumes Hydra scene indices. The same compiled
module passes **27 checks in the bpy wheel and 27 in the Blender binary**, both
in fresh background processes. This is a local feasibility result, not adoption
of Hydra or qualification of a distributable bridge on all platforms.

### Build and reproduction

Source: [`tools/feasibility/hydra_bridge/`](../../tools/feasibility/hydra_bridge/).
Run on macOS arm64 with Blender 5.2.2 installed:

```sh
uv run python tools/feasibility/hydra_bridge/build.py
uv run python tools/feasibility/hydra_bridge/run.py
```

The bridge has its own `pyproject.toml` using **scikit-build-core** and a
`CMakeLists.txt`. The wrapper invokes `uv build --wheel`, extracts the module from
the resulting wheel into `build/hydra-bridge/` for the probes, and audits its
linkage. The wheel is a local feasibility artifact, not the extension distribution.
The main extension still builds only through `tools/build_extension.py`.

To build just the bridge wheel directly:

```sh
uv build tools/feasibility/hydra_bridge --wheel --out-dir build/hydra-bridge/wheels
```

Use `--config-setting cmake.define.BLENDER_APP=/path/to/Blender.app` with `uv build`,
or `--blender-app /path/to/Blender.app` with the wrapper, to select another bundle.
The bridge remains restricted to macOS arm64 and Python 3.13.

CMake automatically downloads a sparse dependency checkout under the bridge's
gitignored `external/blender-deps/` directory on the first build. It uses the macOS dependency revision pinned by
[Blender v5.2.2](https://github.com/blender/blender/tree/v5.2.2/lib):
`a76ef917b4849ba2b1b1deb1a643e131a884a63b` from
[`lib-macos_arm64`](https://projects.blender.org/blender/lib-macos_arm64).
Only USD, TBB, and Python include directories are selected. Dependency libraries
are not linked or shipped. Subsequent builds verify and reuse the pinned checkout
without Git network access. The source distribution excludes `external/` and
build output; the wheel contains the module and package metadata only.

The scikit-build-core conversion was verified with version 1.1.1 and CMake 3.31.1:
a cold build fetched the headers, and a second build succeeded with `UV_OFFLINE=1`
and Git's `protocol.allow=never`. The wheel's extracted module passed all 27
checks again in both runtimes. Cached build files live under the bridge's
`build/{wheel_tag}/`; isolated build environments may still cause recompilation.

- Compiler: Apple clang 17.0.0 (`clang-1700.6.3.2`), C++17, arm64.
- Headers: Blender's generated USD headers, TBB headers, and Python 3.13 headers.
- USD namespace in headers and installed library:
  `pxrBlender_v26_03__pxrReserved__`. Stock upstream headers without Blender's
  configuration would not have this namespace.
- The module uses USD's internal `pxr_boost::python` implementation and the
  host's existing USD Python converters. No separate Boost.Python is linked.
- Link target: `/Applications/Blender.app/Contents/Resources/lib/libusd_ms.dylib`.
  The resulting load command is `@rpath/libusd_ms.dylib`; no absolute Blender path
  or dependency-checkout rpath is embedded in the module.
- Python symbols use macOS dynamic lookup. A post-build `nm` audit verifies that
  all **99 imported Blender-USD symbols** bind explicitly to `libusd_ms`, rather
  than relying on that fallback.
- Import order tested: load Blender and the USD Python modules before importing
  the bridge. Other import orders are not qualified.

`build.json` records the `uv build` command, wheel/module paths, dependency revision,
load commands, and symbol imports. CMake's build directory holds its compiler
configuration. `wheel.json` and `binary.json` record passed checks and loaded
USD paths; the accompanying logs and process records include subprocess exits.
Both processes exit successfully after the checks, including shutdown. Each
gets a temporary Blender user directory and a temporary copy of the USD fixture.
Blender startup requires access to macOS Metal even in background mode; the
successful runs were outside the execution sandbox.

### What passed

- **Shared runtime:** exactly one `libusd_ms` is loaded in each process, from
  `bpy/lib/` in the wheel and `Blender.app/Contents/Resources/lib/` in the binary.
  The same extension binary works with each host's library. No second USD build
  is loaded.
- **Stage exchange:** a Python-created file-backed stage round-trips through C++
  with the same stage and root-layer identity. Unsaved root-layer and session
  opinions are visible. An anonymous stage also round-trips; the bridge retains
  it after the caller releases its Python reference.
- **Hydra access:** `UsdImagingCreateSceneIndices` constructs a live chain.
  Explicit cube/sphere conversion configuration is followed by
  `HdFlatteningSceneIndex` with `HdFlattenedDataSourceProviders`.
- **Mesh extraction:** triangle topology and points match the authored fixture;
  point arrays arrive through the existing `Vt.Vec3fArray` converter.
- **Implicit geometry:** a cube becomes a mesh with eight points, six quads, and
  the expected dimensions. Sphere conversion is configured but not exercised.
- **Inherited state:** the triangle receives its parent's translation; an edit
  to ancestor visibility changes the effective visibility read from the chain.
- **Time:** default-time values, interpolated values at time 2 between samples
  1 and 3, and a return to default time match the fixture. Time changes produce
  dirty notices; an immediate capture at the same time produces no notices.
- **Live edits:** changing points in Python changes values read through the
  retained chain and emits a dirty notice. Adding/removing a prim changes both
  the queried inventory and the corresponding notifications.
- **Lifetime:** an earlier point array remains unchanged after a later source
  edit and disposal of the bridge. Twenty repeated construction/capture/disposal
  cycles complete; this is not a leak or memory-growth measurement.
- **Source preservation:** initial capture leaves root/session layer text
  unchanged, and the source file is never saved. Deliberate source edits in the
  probe are caller actions, not bridge actions.
- **Instancing smoke check:** native instance inputs produce at least one Hydra
  instancer. Instance transforms, counts, nested contexts, and appearance are
  not validated by this check.

### Limits and next gates

This probe reads a small subset of Hydra data; it does not create Blender display
objects, render images, implement source correspondence, or establish performance
budgets. Array retention is demonstrated for one points array; zero-copy transfer
and general snapshot immutability are not established. The observer records event
kinds and paths, not dirty-locator coverage or complete dependency correctness.

Not tested: Windows/Linux linking and packaging, other Blender builds, installed
extension lifecycle, materials, deformation, point instancers, nested instancing,
selection mapping, stage-setting fidelity, invalid input recovery, threading,
undo/save/reopen, production-scale data, or memory/performance regressions.

The prototype owns a strong stage reference. A production binding would need
explicit lifetime handling to preserve the caller-release contract in
[In-Memory Sources](../spec/source-access.md#in-memory-sources). Its native
objects and lazily queried scene indices are not persisted Blender state.

The next gate is [M1b](../milestones/M01b-evaluation-gate.md): cross-platform
native loading against each supported Blender distribution, followed by an
end-to-end prototype for the intended snapshot contract. The current Python-only
implementation decision remains unchanged pending those results and M1b's
recorded decision.

## Windows x64

Pending: fill in from the CI artifacts `windows-*` once the workflow runs (Phase B).

## Linux x64

Pending: fill in from the CI artifacts `linux-*` once the workflow runs (Phase B).

## Future Work

- Windowed (UI-mode) behavior: handler timing, undo with a window manager, and viewport interaction. Out of scope for this project.
