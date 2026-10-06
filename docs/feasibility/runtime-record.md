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
| OS | macOS 26.5.1 |
| Blender | 5.2.2 LTS, build hash `d13f752e3b9c`, build date 2026-09-15 |
| `bpy` wheel | 5.2.2, same build hash |
| Embedded Python | 3.13.13 (binary: Blender's bundled interpreter; wheel: uv-managed CPython 3.13.13) |
| OpenUSD | 0.26.3 (`pxr` bundled in both; exactly one `pxr` package on `sys.path` and no other USD distribution installed, checked in each runtime) |
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

## Windows x64

Pending: fill in from the CI artifacts `windows-*` once the workflow runs (Phase B).

## Linux x64

Pending: fill in from the CI artifacts `linux-*` once the workflow runs (Phase B).

## Future Work

- Windowed (UI-mode) behavior: handler timing, undo with a window manager, and viewport interaction. Out of scope for this project.
