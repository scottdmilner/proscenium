# Runtime Feasibility Record (M1)

Evidence for the [M1](../milestones/M01-runtime.md) stop/go gate, plus later milestones' probes ([Buffer transfer](#buffer-transfer) for M1b, [Copy routes](#copy-routes-m3) for M3) and M4's [measurements](#measurements-m4-phase-c). Each finding is produced by a probe in `tools/feasibility/` and reproduced with:

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
| macOS arm64 | **Go.** All 108 checks pass in all three runtimes (2026-10-19, including the M1b `buffer_transfer` and M3 `copies` probes). |
| Windows x64 | **Go.** All 108 checks pass in all three runtimes (2026-10-19, including M3's `copies` probe). The [compiled Hydra bridge](#compiled-hydra-bridge) passes in both hosts. |
| Linux x64 | **Go.** All 108 checks pass in all three runtimes (2026-10-19, including M3's `copies` probe). The [compiled Hydra bridge](#compiled-hydra-bridge-1) passes in both hosts. |

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

**Undo from a state changed since the last push** (M5, 2026-11-06; the bpy wheel, Blender 5.2.2):
- **The case:** a collection linked in the scene before two pushes, then a new object linked into it without a push, then `ed.undo`. It reads freed memory: the depsgraph Blender builds around the undo reads an object's animation data (`BKE_fcurves_id_cb`, from `is_object_visibility_animated`) after the object is freed.
- **Where it crashed:** it segfaulted in CI on Linux and Windows. On macOS it passed unless freed memory was scribbled over (`MallocScribble=1 MallocPreScribble=1`), and then it segfaulted every time.
- **Variants:** the same object created but linked nowhere, and pushed changes followed by an undo, didn't crash.
- **The explanation:** Blender's undo reuses the datablocks it believes unchanged since the last step, and a change made since without a push isn't seen. This is an inference from these cases.
- **What it means:** with a window every operator pushes a step, so an undo starts from a pushed state. Tests undo only from one: one that checks an operation pushed no step pushes the current state first (`tests/support/undo.py`, `undo_unpushed`).

### In-memory source candidates

Tested the design-note candidate from [Source Stages](../spec/source-access.md#source-stages): a private stage per binding over the caller's root and session layers. It was opened with `Usd.Stage.OpenMasked(root, session, resolverContext, mask, load)` under `BlockStageCaches`. The caller's settings were then reproduced with `MuteAndUnmuteLayers` and `SetInterpolationType`.

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

The question is whether the on-disk state can be composed without touching shared layers ([Layer State and Reloading](../spec/source-access.md#layer-state-and-reloading)). The test scene had dirty edits in sublayer, reference, payload-nested, and absolute-path layers. All candidates left the shared layers untouched.

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

### Copy routes (M3)

Added for M3 (`probe_copies.py`), as evidence for [Copied Bindings](../spec/source-access.md#copied-bindings). The probe's base file holds one binding. Three datablocks carry an ID-property record, and each record holds the binding identity (a string) and one ID pointer:
- the scene, pointing at the destination collection;
- the destination collection, pointing back at the scene;
- the managed object in that collection, pointing at the destination.

The base file also holds a **file-level index**. It is an ID-property record mapping the binding identity to its destination by ID pointer. The probe puts one on each of two candidate hosts outside the binding's datablocks:
- a Text with a fake user;
- an unlinked collection with a fake user.

Nothing points at either host.

Each route starts from the base file and copies the binding. The probe then records, saves, reopens, and records again:
- every datablock whose record carries the identity, with its pointers;
- every index host;
- the scene/collection pairs whose records point at each other ("pairs" below; the base file has one);
- tagged objects whose tag names a collection other than the one they are in.

Checks hold what D2 builds on, on every route that ran:
- the tagged datablocks by kind;
- the pair count;
- that the index still names only the original;
- that the records are unchanged by the save and reopen.

The facts are identical in all three runtimes.

| Route | What the copy holds | Pairs |
|---|---|---|
| Full-copy scene (`scene.new(type='FULL_COPY')`) | Copies of the scene, the collection, and the object. Every pointer in a copy is rewritten to point at the copies. | 2 |
| Linked-copy scene (`LINK_COPY`) | A new scene sharing the collection. Its record points at the shared collection, and that collection still points at the original scene. | 1 |
| `Collection.copy()`, with the copy linked into the scene | A copy of the collection, sharing the original's objects. Its record still points at the original scene, and the shared object's tag names the original collection. | 1 |
| Append collection (`wm.append`, and `libraries.load(link=False)`) | The collection, its object, and the scene its record points at. Pointers among the appended datablocks point at each other. | 2 |
| Append scene (`wm.append`) | The scene, its collection, and the object, with pointers as in appending the collection. | 2 |
| Record assigned in Python (`new[key] = old[key]`) | A copy of the group: changing the copy leaves the source unchanged. Its pointers are kept, so they point at the originals. | 1 |
| Link collection (`libraries.load(link=True)`) | The linked collection, its object, and its scene, all from the library. Pointers among the linked datablocks point at each other. | 2 |
| Duplicate the managed object (`object.duplicate`) | A duplicate object whose tag still points at the original destination. | 1 |

- **Duplicating the destination collection is covered only in part.**
  - `Collection.copy()` is a shallow copy: the copy shares the original's objects. It stands in for a shallow duplicate such as Outliner > Duplicate Linked, which was not run or compared with it.
  - Outliner > Duplicate Collection, which by Blender's manual also duplicates the objects under the Duplicate Data preferences, was not run either. In background mode, in the wheel and in the binary, it fails with "No collection selected". It reads the outliner's selection from the outliner's tree, and Blender builds that tree only when it draws the outliner. Like other windowed behavior, it is untested ([Future Work](#future-work)).
  - *Inference, not tested.* The full-copy route rewrites pointers among the datablocks copied together, and keeps pointers to the rest. If a deep duplicate behaves the same way, its collection copy would point at the original scene and form no new pair, while its object copies would name the collection copy. The objects' tags and the collections' records would then disagree.
- **An ID pointer in a record makes its target a dependency of append and link.** Appending or linking the collection also brought in the scene its record points at. As a control, the same collection with no scene pointer brought in no scene, both appended and linked.
- **Pointers in records hold users.**
  - The destination has 1 user without records, and 5 with them: its scene link, plus the scene's record, the object's tag, and the two index entries.
  - Once unlinked from the scene, it keeps 4 users and survives save and reopen, so a record pointer keeps an unlinked destination in the file.
  - The scene's user count is 1 with or without the collection's pointer to it.
- **Removing the destination clears the pointers.**
  - After `bpy.data.collections.remove`, the scene's and object's pointers and both index entries hold `None`, before and after save and reopen.
  - So the index can hold an entry with no destination, but not a pointer to a removed one.
- **Names.** On every route, the original datablocks keep their names.
  - Local copies get a `.001` suffix where a name clashes. The control appends `Dest` into a file without one, and it keeps its name.
  - Linked datablocks keep their names and differ only by library.
- **The index is never copied by the routes in the table.**
  - On each of them, each host remains the only index of its kind, and still names the original destination, before and after save and reopen. That includes the routes that copy both sides of the pair.
- **Appending the index host itself.**
  - Appending the other file's Text or collection host brings in its binding, through the host's pointer, and gives a second index naming the appended destination.
  - Each appended host has no fake user and no users, so the save drops it. After reopening, one index remains, naming the original.
- **The window manager can't host the index.**
  - Its ID properties aren't saved with the file.
  - Opening another file with `load_ui=False` keeps the session's window manager, and the record with it. With `load_ui=True`, the opened file's window manager replaces it.
- **For the canonical-candidate rule (D2).**
  - On the routes that copy one side of the pair, exactly one pair still points at each other: the linked-copy scene, `Collection.copy()`, and the Python assignment.
  - On the routes that copy both sides together, each copy is a pair of its own: the full-copy scene, append, and link. So ID pointers alone don't tell the original from the copy there.
  - Only names and libraries differ on those routes, and ownership rules exclude display names as identifiers ([Ownership and Lifecycle](../spec/lifecycle.md#ownership-and-lifecycle)).
  - The file-level index on a Text or an unlinked collection named the original pair on every route in the table, including those.

Not probed:
- a user deleting an index host, or clearing its fake user;
- library overrides of a linked collection, a common production route that also copies ID properties;
- other Duplicate Data preferences.

Scope:
- one binding with one managed object, and one index entry;
- raw ID properties, not registered property groups;
- the factory-default Duplicate Data preferences;
- background mode only;
- macOS, Windows, and Linux. The probe's facts are identical on all three, in every runtime ("Feasibility" workflow, [run 39330194131](https://github.com/scottdmilner/proscenium/actions/runs/39330194131), 2026-10-19).

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
`tools/blender_deps.py` (the bridge's `prepare_deps.py` until M3 moved it, unchanged in
logic) reads that release's git tag (`v5.2.2`) from a shallow, treeless
clone of `blender.git` and takes the precompiled-library revisions from its `lib/`
submodule pointers. The resolved tag, commit, and revisions are cached in
`build/blender-deps/blender-<tag>.json`. `build.py` checks that the installed bpy wheel's version
is the locked one, from its metadata. The probe then checks in each host that
`bpy.app.build_hash` is the tag's commit (`d13f752e3b9c`) recorded in `build.json`. So
headers, link input, and test hosts come from one release.

On the first build `blender_deps.py` makes a blobless sparse checkout of the
platform's library repo under the gitignored `build/blender-deps/<repo>/`. A warm build
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
  - **The plan's order varies between processes,** even on one thread and with the committed planner, though its content doesn't (ad hoc, ALab). See [Plans from separate processes](#plans-from-separate-processes).
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

### Measurements (M4 Phase C)

The object baseline's synchronization and updates against M4's provisional budgets ([M4 plan](../plans/M04-prototypes.md), settled item 4), recorded as baselines, not gates. Run on the reference hardware (M1 Max, 32 GB, macOS 26.5.1, AC power) in the Blender 5.2.2 binary (`d13f752e3b9c`), 2026-10-28. Reproduce with:

```sh
uv run python tools/feasibility/hydra_bridge/build.py
uv run python tools/feasibility/hydra_bridge/measure/run.py --scenes updates alab --modes importer-matched --scenarios all
```

The full statistics go to `build/hydra-bridge/measure/summary.md` (not committed).

**Method:** as in [M1b Phase E](#measurements-m1b-phase-e), with these differences:
- **Runs:** each scene first gets one unrecorded warmup run of the matched importer and of the prototype, for the file cache and the loader. Then come three runs of each mode, alternating. Figures are medians, with ranges.
- **Update modes:** each is a fresh synchronization followed by one scenario from `measure/scenarios.py`:
  - the scenario's edit;
  - an incremental capture, planning, and the plan diff;
  - the update by that diff (`update.py`), under the repoint policy: preparation, publication, and retirement;
  - a depsgraph evaluation.

  The update's time is those steps, without the edit.
- **Coexisting memory:** the most footprint above the level just before preparation, until retirement ends, while both generations' data exist.
- **Scenarios** (acceptance.md, Performance), each target chosen from the plan:
  - an unchanged refresh;
  - a translation of the first mesh object outside instances;
  - the points of the instanced mesh with the most copies;
  - a constant input of the material in the most slots outside instances;
  - the next time code;
  - every payload unloaded, or loaded into a stage opened without them.

  The initial scenario also saves the file uncompressed.
- **ALab's shared-geometry edit:** instance contents take no session-layer opinion, so this edit changes the layer that defines the mesh, in memory only; no layer is saved.
- **Generated scenes:** `updates-N` (`measure/stress.py`) has N native copies of a two-mesh, two-material asset behind one payload; N cubes outside instances, alternating between the materials; and a grid whose topology changes between time codes 1 and 2. They give 301, 3,001, and 30,001 objects.
- **Not measured:**
  - undo overhead: in background mode Blender pushes no undo steps;
  - cold source acquisition: dropping the OS file cache needs root;
  - the interaction functions (M4 C4);
  - the replace policy (B6 measured both).

**Budgets:**

| Budget (provisional) | ALab | updates-100 | updates-1000 | updates-10000 |
|---|---|---|---|---|
| Initial synchronization, at most 1.5× the matched importer's time | 1.09× | 1.27× | 1.20× | **4.37×** |
| Initial synchronization, at most 2× its peak memory | 1.56× | 0.74× | 1.49× | 1.24× |
| Unchanged refresh, no slower than initial synchronization | 0.15× | 0.04× | 0.07× | 0.03× |
| Transform update, at least 10× faster than a full rebuild | **5.3×** | 10.3× | **3.5×** | **8.8×** |
| Shared-geometry update, likewise | **6.0×** | **8.4×** | **2.9×** | **7.7×** |
| Material update, likewise | **6.8×** | **7.2×** | **2.9×** | **7.0×** |

The ratios are of medians; the full rebuild is the prototype's initial synchronization in the same set.

**ALab** (7,018 objects; synchronization 3.823 s (3.336–4.004 s), the matched importer 3.501 s (3.190–3.615 s); peak 2,829 MB (2,828–2,829) against 1,808 MB (1,803–1,812)):

| Scenario | Update s | Capture s | Planning s | Diff s | Prepare s | Publish s | Retire s | Evaluate s | Coexisting MB | Objects created / repointed / retired IDs |
|---|---|---|---|---|---|---|---|---|---|---|
| unchanged | 0.556 (0.436–0.653) | 0.024 (0.024–0.026) | 0.325 (0.284–0.355) | 0.091 (0.070–0.114) | 0.053 (0.050–0.181) | 0.005 (0.004–0.006) | 0.002 (0.002–0.010) | 0.002 (0.002–0.016) | 25 (19–33) | 0 / 0 / 0 |
| transform | 0.721 (0.577–0.767) | 0.022 (0.021–0.027) | 0.366 (0.355–0.433) | 0.123 (0.074–0.144) | 0.057 (0.049–0.137) | 0.005 (0.005–0.006) | 0.013 (0.010–0.021) | 0.067 (0.057–0.074) | 23 (23–27) | 2 / 0 / 2 |
| shared-geometry | 0.636 (0.515–0.715) | 0.025 (0.024–0.026) | 0.353 (0.315–0.377) | 0.100 (0.052–0.211) | 0.052 (0.046–0.053) | 0.006 (0.005–0.008) | 0.011 | 0.060 (0.058–0.060) | 22 (21–23) | 0 / 169 / 1 |
| material | 0.561 (0.549–0.790) | 0.024 (0.023–0.027) | 0.338 (0.332–0.453) | 0.076 (0.056–0.136) | 0.049 (0.047–0.060) | 0.008 (0.007–0.009) | 0.012 | 0.062 (0.061–0.096) | 19 (16–22) | 0 / 244 / 1 |
| time-step | 1.701 (1.694–2.032) | 0.087 (0.083–0.125) | 0.429 (0.390–0.439) | 0.106 (0.094–0.126) | 0.644 (0.593–0.803) | 0.010 (0.008–0.010) | 0.398 (0.360–0.462) | 0.087 (0.077–0.096) | 62 (60–73) | 695 / 0 / 1,051 |
| payload-unload | 1.573 (1.482–1.579) | 0.904 (0.870–0.931) | 0.006 | 0.004 (0.003–0.004) | 0.002 | 0.019 (0.018–0.021) | 0.582 (0.556–0.616) | 0.028 (0.023–0.030) | 0 (0–0) | 0 / 0 / 11,185 |
| payload-load | 2.963 (2.717–2.966) | 0.921 (0.835–0.925) | 0.258 (0.245–0.263) | 0.001 | 1.670 (1.521–1.673) | 0.021 (0.020–0.023) | 0.011 (0.010–0.012) | 0.076 (0.075–0.084) | 1,073 (1,069–1,077) | 7,018 / 0 / 0 |

Time 1004 to 1005 changes 695 objects' transforms or points, with 355 new meshes. The diff finds no repointable objects, so each changed object is replaced. The file saves to 1,059 MB uncompressed in 0.842 s (0.532–0.864 s).

**Against size** (each updates-N scene, and ALab between them by object count):

| Scene | Objects | Importer sync s | Sync s | Construction s | Unchanged s | Transform s | Its evaluation s | Material s |
|---|---|---|---|---|---|---|---|---|
| updates-100 | 301 | 0.063 (0.062–0.091) | 0.079 (0.044–0.080) | 0.008 | 0.003 | 0.008 (0.007–0.010) | 0.004 (0.004–0.005) | 0.011 (0.009–0.011) |
| updates-1000 | 3,001 | 0.273 (0.258–0.330) | 0.327 (0.312–0.350) | 0.097 (0.094–0.099) | 0.022 (0.021–0.025) | 0.092 (0.092–0.093) | 0.068 (0.064–0.068) | 0.114 (0.112–0.120) |
| alab | 7,018 | 3.501 (3.190–3.615) | 3.823 (3.336–4.004) | 1.612 (1.497–1.787) | 0.556 (0.436–0.653) | 0.721 (0.577–0.767) | 0.067 (0.057–0.074) | 0.561 (0.549–0.790) |
| updates-10000 | 30,001 | 2.009 (1.981–2.058) | 8.776 (8.219–8.790) | 6.680 (6.267–6.743) | 0.231 (0.224–0.231) | 0.993 (0.992–1.064) | 0.761 (0.760–0.800) | 1.249 (1.223–1.310) |

| Scene | Objects added or removed | Payload load s | Its preparation s | Payload unload s | Its retirement s |
|---|---|---|---|---|---|
| updates-100 | 200 | 0.023 (0.022–0.027) | 0.006 | 0.015 (0.014–0.020) | 0.002 |
| updates-1000 | 2,000 | 0.265 (0.255–0.266) | 0.096 (0.095–0.102) | 0.169 (0.167–0.182) | 0.056 (0.054–0.057) |
| alab | 7,018 | 2.963 (2.717–2.966) | 1.670 (1.521–1.673) | 1.573 (1.482–1.579) | 0.582 (0.556–0.616) |
| updates-10000 | 20,000 | 27.061 (26.534–28.687) | 25.281 (24.757–26.744) | 20.174 (19.561–20.315) | 16.890 (16.328–17.033) |

The files save to 1.3, 8.0, and 74.5 MB uncompressed.

**Findings:**
- **Blender inserts each new datablock into a list sorted by name,** and the cost grows with how far from the end it lands. Ad hoc probes, in the same binary, created empties in batches of 1,000:
  - names created in sort order (zero-padded): 15–20 ms per batch throughout;
  - reversed: rising to 782 ms per batch by 15,000;
  - random: rising to 354 ms per batch.

  The same held for mesh objects and `Object.copy()`. Only objects slowed: 10,000 meshes in the file didn't. Plain numbered names (`O_9999`, `O_10000`) went from about 12 ms to about 500 ms per batch at 10,000 objects, where their sort order stops matching creation order. Blender's own `.NNNN` suffixes behave the same way. The baseline names each object for its prim, so `updates-10000`'s 10,000 each of `Mesh`, `Body`, and `Lid` cross that point; ALab's names are varied.
  - **Measured variant** (ad hoc, a scratch copy of `apply.py` naming each object with its zero-padded plan index first, three runs per mode on the same scenes):
    - construction fell from 6.680 s to 1.064 s (1.055–1.139 s) on `updates-10000`, putting synchronization at 3.294 s (3.107–3.419 s), 1.64× the importer's 2.009 s;
    - on ALab, construction took 1.428 s (1.337–1.489 s) against 1.612 s; synchronization's run-to-run spread between the two sets is as large as the difference;
    - preparing the payload load still took 11.474 s (9.378–13.311 s) on `updates-10000`, since the loaded objects' plan indices come before those already in the file.

    The names users see are M6's design, which must create objects so that their names land at the end of the list. This also applies to batching such as Geometry Nodes instancing, which changes which objects are created at all.
- **The depsgraph's evaluation after an update grows with the scene,** whenever objects were linked, unlinked, or repointed: 4 ms at 301 objects, 68 ms at 3,001, 67 ms on ALab, and 761 ms at 30,001. An unchanged refresh writes nothing to Blender, and its evaluation takes 2 ms on ALab and on `updates-10000`.
- **Retirement grows faster than the IDs it removes:** 0.056 s for 2,001 at 3,001 objects, 0.582 s for 11,185 on ALab, and 16.890 s for 20,001 at 30,001 objects. Names don't cause it: the variant's retirement was the same, 16.749 s. The cause wasn't investigated.
- **Planning and the diff cost more inside an update than alone:**
  - on ALab, planning took 0.33–0.43 s in updates against 0.25 s in the initial synchronization;
  - the diff took 76–123 ms here, against 38 ms in the bpy wheel ([M4 plan](../plans/M04-prototypes.md), C1).

  Not investigated. Together they are most of every small update on ALab.
- **Coexisting memory** for ALab's small updates is 19–25 MB, and 62 MB for the time step. Loading every payload builds the whole display beside an almost empty one: 1,073 MB.

#### Interaction at scale (M4 Phase C)

The baseline's interaction functions after a synchronization, in the same environment (2026-10-28). Reproduce with `measure/run.py --scenes updates alab --modes interaction`.

**Method** (`measure/interaction_timing.py`): each process synchronizes, then times each operation in process with a monotonic clock. Each operation is repeated 20 times, or 5 for whole-browser and whole-assembly ones, and takes its median. The tables give the median and range of those medians over three processes, after one unrecorded warmup per scene.
- **The pick:** a viewport element inside the deepest instance context.
- **The box selection:** every viewport element under the top-level prim with the most of them; on ALab that is `/root`, kind `assembly`, with 1,886 elements.
- **The chain,** as the contract has it:
  - `select_targets` at the prim level and at the `component` and `assembly` levels;
  - `highlight_targets` (`component` for the pick, `assembly` for the box selection);
  - `apply_selection`, timed with the depsgraph update it triggers;
  - `read_blender_selection`;
  - `selection_from_blender` at each level.

  The box selection's `resolve_pick` is one call per element.
- **The other payload policy:** the universe without payloads comes from a capture after unloading every payload.
- **Budgets:** the provisional ones are 50 ms for each function on a single pick or entry and 250 ms on a whole-assembly selection, with their Blender updates ([M4 plan](../plans/M04-prototypes.md), settled item 4).

| | updates-100 | updates-1000 | ALab | updates-10000 |
|---|---|---|---|---|
| Objects | 301 | 3,001 | 7,018 | 30,001 |
| Universe, payloads loaded | 305 | 3,005 | 2,020 | 30,005 |
| Universe, no payloads | 204 | 2,004 | 0 | 20,004 |
| Stage browser prims | 310 | 3,010 | 2,962 | 30,010 |
| Stage browser prims, with instance proxies | 610 | 6,010 | 38,197 | 60,010 |
| Children of the widest prim | 100 | 1,000 | 178 | 10,000 |
| Viewport elements in the box selection | 301 | 3,001 | 1,886 | 30,001 |

ALab's payloads hold all of its displayed content, so without them nothing is displayed.

| Operation (ms) | Repeats | updates-100 | updates-1000 | ALab | updates-10000 |
|---|---|---|---|---|---|
| derive the universe | 20 | 0.104 (0.093–0.127) | 1.290 (1.276–1.298) | 1.884 (1.864–2.206) | 19.122 (18.363–19.939) |
| `displayed`, every prim | 5 | 0.382 (0.259–0.421) | 3.577 (3.064–3.599) | 8.381 (7.944–8.981) | 36.087 (35.697–42.060) |
| `displayed`, with instance proxies | 5 | 0.658 (0.638–0.804) | 6.813 (6.679–7.021) | 135.080 (134.669–137.192) | 81.783 (80.886–85.461) |
| expand the widest prim | 20 | 0.254 (0.241–0.265) | 2.703 (2.625–2.973) | 0.823 (0.748–0.837) | 32.323 (31.515–32.947) |
| pick: `resolve_pick` | 20 | 0.001 | 0.001 | 0.001 | 0.001 |
| pick: `select_targets`, prim level | 20 | 0.003 | 0.002 | 0.005 | 0.002 |
| pick: `select_targets`, component | 20 | 0.003 | 0.003 | 0.005 (0.005–0.006) | 0.003 |
| pick: `select_targets`, assembly | 20 | 0.003 | 0.003 | 0.007 (0.006–0.007) | 0.003 |
| pick: `highlight_targets` | 20 | 0.001 | 0.001 | 0.003 | 0.001 |
| pick: `apply_selection`, with the depsgraph update | 20 | 0.594 (0.556–0.622) | 9.984 (9.957–10.120) | 12.258 (12.210–12.301) | **129.475 (125.632–131.329)** |
| pick: `read_blender_selection` | 20 | 0.140 (0.137–0.150) | 1.448 (1.398–1.937) | 4.036 (4.008–4.382) | 22.590 (22.031–24.704) |
| pick: `selection_from_blender`, prim level | 20 | 0.001 | 0.001 | 0.001 | 0.001 |
| pick: `selection_from_blender`, component | 20 | 0.002 | 0.002 | 0.002 | 0.002 |
| pick: `selection_from_blender`, assembly | 20 | 0.002 | 0.002 | 0.003 (0.002–0.005) | 0.002 |
| box: `resolve_pick`, per element | 5 | 0.225 (0.221–0.225) | 2.322 (2.290–2.430) | 1.917 (1.649–1.921) | 32.189 (28.483–35.264) |
| box: `select_targets`, prim level | 5 | 0.543 (0.528–0.898) | 5.498 (5.413–5.593) | 9.478 (9.010–10.821) | 72.594 (71.416–73.056) |
| box: `select_targets`, component | 5 | 0.725 (0.698–0.935) | 7.340 (7.041–8.495) | 13.047 (12.342–13.135) | 96.808 (94.137–104.429) |
| box: `select_targets`, assembly | 5 | 0.701 (0.681–0.729) | 7.132 (7.036–7.647) | 14.277 (13.944–15.061) | 95.723 (92.386–112.540) |
| box: `highlight_targets` | 5 | 0.290 (0.277–0.301) | 3.114 (3.062–3.512) | 15.863 (15.526–16.114) | 42.927 (41.558–47.298) |
| box: `apply_selection`, with the depsgraph update | 5 | 0.491 (0.476–0.606) | 9.545 (9.200–11.580) | 12.642 (12.167–12.703) | 122.474 (121.890–136.204) |
| box: `read_blender_selection` | 5 | 0.150 (0.145–0.171) | 1.942 (1.480–2.033) | 4.159 (4.107–4.580) | 23.259 (22.781–25.991) |
| box: `selection_from_blender`, prim level | 5 | 0.053 (0.050–0.060) | 0.516 (0.502–0.708) | 0.438 (0.416–0.567) | 6.218 (6.136–8.597) |
| box: `selection_from_blender`, component | 5 | 0.224 (0.223–0.227) | 2.746 (2.585–3.016) | 2.379 (2.018–2.872) | 32.324 (31.245–37.427) |
| box: `selection_from_blender`, assembly | 5 | 0.226 (0.224–0.230) | 2.721 (2.597–2.766) | 4.977 (4.340–5.426) | 30.456 (30.456–36.391) |

**Findings:**
- **On ALab every function is within its budget.** A pick's slowest function is `apply_selection` with its depsgraph update, 12.3 ms, against 50 ms. A box selection's slowest is `highlight_targets`, 15.9 ms, against 250 ms. The box selection's chain from Blender's selection back to Blender takes about 38 ms in all: `read_blender_selection`, `selection_from_blender` at the assembly level, `highlight_targets`, and `apply_selection`.
- **Kind promotion's share** of `selection_from_blender` on ALab's box selection: 1.9 ms at the component level and 4.5 ms at the assembly level, over 0.4 ms at the prim level.
- **The universe is small beside the display:** ALab's 7,018 objects are 2,020 universe prims, since instance contents are not in it. Deriving it takes 1.9 ms on ALab and grows with the display: 19.1 ms at 30,001 objects.
- **The whole stage browser** takes 8.4 ms on ALab without instance proxies. With them, 38,197 paths, it takes 135 ms, about 3.5 µs a path. Expanding one prim is a fraction of that.
- **Mirroring a selection grows with the display:** a pick's `apply_selection` takes 129 ms at 30,001 objects, over the budget. In an ad hoc probe in the same binary, with 30,000 objects in one collection:
  - the depsgraph update after one `select_set` took 102 ms (91–108 ms) by itself;
  - `apply_selection`, which sets every managed object's selection, took 26 ms, 9 ms of it collecting the managed objects.

  `read_blender_selection` likewise reads every managed object: 23 ms at 30,001.

#### Ownership lookup after undo (M4 Phase C)

The first ownership lookup after an undo or redo, with the baseline's display as a binding's manifest, in the same environment (2026-10-28). Reproduce with `measure/run.py --scenes updates alab --modes ownership`.

**Method** (`measure/ownership_timing.py`):
- **The manifest:** the child applies the display into a binding's destination, made through M3's API, and writes its manifest with `ownership_index.set_manifest`. There is one entry per object, shear parent, placeholder mesh, mesh, and material. An object's entry covers its source and uses its mesh and materials; a mesh's or material's covers its users' sources.
- **The undo steps:** with global undo on, it pushes a step, then five times moves one object, pushes a step, undoes it, and redoes it.
- **The lookups:** after each undo and redo it times `ownership_index.ownership()` of an object no step changed, found by name before the clock starts, then again, cached. Each undo and redo dropped the bindings' state, so each first lookup rebuilt it: `rebuild_count` changed three times per undo or redo in every run.
- **Statistics:** three processes per scene after a warmup; each process's median of its repeats, as a median and range over the processes.

| Operation (ms) | Repeats per run | updates-100 | updates-1000 | ALab | updates-10000 |
|---|---|---|---|---|---|
| Manifest entries | | 306 | 3,006 | 11,185 | 30,006 |
| build the manifest | 1 | 3.878 (0.953–7.681) | 12.464 (11.978–12.565) | 37.516 (28.914–42.367) | 96.384 (88.286–107.658) |
| `set_manifest` | 1 | 2.017 (1.921–3.178) | 17.105 (16.908–27.657) | 58.463 (56.344–59.863) | 166.580 (164.135–172.193) |
| ownership after the write | 1 | 0.251 (0.250–0.256) | 2.419 (2.358–3.093) | 9.759 (9.513–10.196) | 25.479 (25.423–26.877) |
| undo push | 6 | 1.179 (1.156–1.219) | 8.568 (8.530–8.616) | 48.529 (46.509–48.971) | 96.234 (93.331–96.363) |
| undo | 5 | 9.588 (9.254–9.602) | 87.753 (87.696–87.855) | 350.961 (341.752–363.524) | 1,056.177 (1,041.535–1,074.516) |
| redo | 5 | 9.379 (9.098–9.616) | 86.511 (85.831–88.356) | 355.716 (334.683–357.616) | 1,036.296 (1,017.067–1,066.851) |
| **first ownership after undo or redo** | 10 | 1.116 (1.108–1.119) | 11.045 (10.958–11.194) | **43.886 (43.845–45.447)** | **158.042 (156.328–163.547)** |
| cached ownership | 10 | 0.004 | 0.006 | 0.010 (0.010–0.011) | 0.012 (0.011–0.012) |

**Findings:**
- **Against the 50 ms budget:**
  - ALab's median first lookup is under it, at 43.9 ms, about 39 ms per 10,000 entries;
  - each ALab run had one lookup at 85–90 ms, over it;
  - 30,006 entries take 158 ms.

  M3 measured 21–35 ms per 10,000 resources in the bpy wheel ([M3 plan](../plans/M03-bindings.md), D8).
- **The outliers are mostly garbage collection.** In one more ALab run, nine of ten first lookups took 42.6–43.8 ms and one 97.8 ms. With Python's garbage collector off for the loop (ad hoc, two runs), all twenty took 37.4–40.4 ms, but one 59.9 ms. So the rebuild's allocations set off a full collection now and then, and the collector costs about 5 ms of a typical rebuild.
- **Blender's undo** at this scale takes about 350 ms on ALab and 1.05 s at 30,001 objects, an undo push 49 ms and 96 ms: an undo step's own cost, beside the lookup that follows it.

### Measurements (M4 Phase D)

Phase D's batched display (`batch.py`, Geometry Nodes instances; [M4 plan](../plans/M04-prototypes.md), D1–D4) against the object baseline, both measured in the same session, in the environment of [Phase C](#measurements-m4-phase-c) (2026-10-28, AC power throughout). Reproduce with:

```sh
uv run python tools/feasibility/hydra_bridge/build.py
uv run python tools/feasibility/hydra_bridge/measure/run.py --scenes updates alab \
    --modes prototype importer-matched interaction --scenarios all --representation batched
uv run python tools/feasibility/hydra_bridge/measure/run.py --scenes updates alab \
    --modes prototype importer-matched interaction --scenarios all --out build/hydra-bridge/measure-d5-objects
# Batching only large groups, on ALab, with the baseline again (2026-10-29)
uv run python tools/feasibility/hydra_bridge/measure/run.py --scenes alab --modes prototype importer-matched \
    interaction --scenarios all --repeats 3 --representation batched --batch-minimum 5 --out build/hydra-bridge/measure-min5
# likewise with --batch-minimum 20 (measure-min20), and --representation objects (measure-min-objects)
```

The full statistics go to the `summary.md` in each of those directories under `build/hydra-bridge/` (not committed).

**Method:** as in Phase C and [C4](#interaction-at-scale-m4-phase-c), with these differences:
- **The batched display:** `--representation batched` applies the plan with `batch.py`, updates it with `batch_update.py`, and mirrors selections with `batch_selection.py`. The interaction timing also times `pick_element` on what a ray cast at the picked copy returns.
- **A new scenario,** in both sets: a translation of the first instanced copy's outermost instance root, which moves one copy of each of its meshes (`instance-transform`). Phase C's transform scenario moves a mesh object outside instances, which on `updates-N` is the morph grid, an object in both representations.
- **Two fixes before the final runs,** both found by these measurements. Every figure below is from after them.
  - `batch_update.prepare` rebuilt its set of kept objects once per object, quadratic in the objects a batched display keeps (3,633 on ALab).
  - Both representations read each copy's object color by indexing the record's `Vt` array from Python, about 48 µs per record (ad hoc, ALab). They now read the converted ID-property values. On ALab that was about 0.34 s of the baseline's construction, which Phase C's figures include.
- **String primvars:** batches leave them out, so they never split a group. The first sets ran with copies grouped also by their strings' values, which groups every scene here the same (ALab's 657 batches either way, ad hoc), and puts each batch's strings on its prototype.
- **Batching only large groups:** `--batch-minimum N` batches only groups of at least N copies, and keeps smaller ones as objects; the first sets batch every group of two or more. ALab ran at minimums of 5, the smallest at which a batch has fewer objects than its copies, and 20, with the baseline again, in one session of 3 repeats each. A first run of those three sets, in that order, had every update stage of the first two slower, the native capture and diff included, which don't depend on the representation; an ad hoc rerun of two scenarios in the reverse order showed no such difference, so those sets were rerun in full and only the rerun is reported.
- **Not measured:** the ownership mode (C5), which writes the baseline's manifest; the replace policy; undo.

**Grouping** (each plan's batches as `batch.py` forms them):

| Scene | Plan objects | Batches | Instances | Blender objects, batched | Blender objects, baseline |
|---|---|---|---|---|---|
| updates-100 | 301 | 3 (150, 100, 50) | 300 | 13 | 301 |
| updates-1000 | 3,001 | 3 | 3,000 | 13 | 3,001 |
| updates-10000 | 30,001 | 3 (15,000, 10,000, 5,000) | 30,000 | 13 | 30,001 |
| ALab | 7,018 | 657 (382 of 2 copies; at most 77) | 3,385 | 6,261 | 7,018 |
| ALab, minimum 5 | 7,018 | 169 | 2,244 | 5,450 | 7,018 |
| ALab, minimum 20 | 7,018 | 30 | 1,012 | 6,126 | 7,018 |

A batch was three carriers and a prototype, so it had fewer objects than its copies only from 5 copies up ([D14](#carriers-per-selection-state) gives an unselected batch one carrier). 6,997 of ALab's 7,018 copies show in one destination only (C1 and D2), and its largest groups are of 77 copies. The `updates-N` scenes' batches are all larger than 20, so a minimum up to 20 doesn't change them.

**Budgets** (ratios of medians, each against the matched importer and the full rebuild of its own set; baseline in brackets):

| Budget (provisional) | ALab | updates-100 | updates-1000 | updates-10000 |
|---|---|---|---|---|
| Initial synchronization, at most 1.5× the importer's time | 0.90× [0.88×] | 1.15× [1.41×] | 0.76× [1.27×] | 0.62× [**4.01×**] |
| Initial synchronization, at most 2× its peak memory | 1.56× [1.55×] | 0.67× [0.84×] | 0.63× [1.45×] | 0.50× [1.25×] |
| Unchanged refresh, no slower than initial synchronization | 0.16× [0.14×] | 0.07× [0.05×] | 0.14× [0.07×] | 0.20× [0.02×] |
| Transform update, at least 10× faster than a full rebuild | **6.2×** [**6.3×**] | **8.7×** [**9.6×**] | **7.0×** [**3.6×**] | **4.7×** [**8.6×**] |
| Instance-transform update, likewise | **5.9×** [**5.8×**] | **8.5×** [**7.8×**] | **5.6×** [**3.1×**] | **3.7×** [**7.0×**] |
| Shared-geometry update, likewise | **6.2×** [**5.9×**] | 11.8× [**8.1×**] | **6.5×** [**3.3×**] | **4.6×** [**7.6×**] |
| Material update, likewise | **6.1×** [**6.2×**] | 12.6× [**7.1×**] | **6.8×** [**3.2×**] | **4.2×** [**6.8×**] |

**updates-10000** (30,001 objects; medians with ranges, seconds unless marked):

| | Batched | Baseline |
|---|---|---|
| Initial synchronization (importer 2.242 / 2.034) | 1.386 (1.372–1.397) | 8.145 (8.114–8.397) |
| Its construction | 0.120 (0.114–0.120) | 6.204 (6.201–6.389) |
| Peak MB (importer 1,111 / 1,093) | 557 (556–558) | 1,367 (1,359–1,373) |
| `.blend` MB, uncompressed | 3.1 | 71.1 |
| Unchanged refresh | 0.284 (0.276–0.285) | 0.199 (0.195–0.214) |
| Transform | 0.297 (0.297–0.312) | 0.947 (0.938–0.947) |
| Instance transform | 0.372 (0.361–0.442) | 1.169 (1.099–1.336) |
| Shared geometry | 0.300 (0.299–0.306) | 1.077 (1.073–1.201) |
| Material | 0.326 (0.286–0.335) | 1.199 (1.150–1.279) |
| Time step | 0.306 (0.264–0.323) | 0.946 (0.917–0.988) |
| Payload unload | 3.126 (2.877–3.551) | 19.189 (18.978–19.688) |
| Payload load | 1.118 (1.003–1.200) | 27.063 (26.213–27.210) |
| Each small update's preparation | 0.162–0.178 | 0.076–0.104 |
| Each small update's evaluation | 0.001–0.003 | 0.711–0.868 |
| Pick: `pick_element`, a batch of 15,000, ms | 3.2 (3.2–3.5) | — |
| Pick: `apply_selection` with its depsgraph update, ms | 2.7 (2.6–2.7) | 119.1 (115.0–119.5) |
| Box selection of 30,001 elements: `apply_selection`, ms | 3.3 | 118.7 (115.5–120.7) |
| `read_blender_selection`, pick and box, ms | 6.3, 7.0 | 22.4, 23.7 |

**ALab** (7,018 objects):

| | Batched | Baseline |
|---|---|---|
| Initial synchronization (importer 3.134 / 3.133) | 2.824 (2.731–2.893) | 2.748 (2.700–2.833) |
| Its construction | 1.052 (0.990–1.067) | 1.030 (1.021–1.059) |
| Peak MB (importer 1,799 / 1,804) | 2,814 (2,806–2,815) | 2,797 (2,796–2,818) |
| Small updates (unchanged to material) | 0.457–0.483 | 0.393–0.477 |
| Their preparation | 0.074–0.075 | 0.044–0.047 |
| Their evaluation | 0.002–0.043 | 0.002–0.054 |
| Time step, payload unload, payload load | 1.184, 1.360, 2.247 | 1.247, 1.382, 2.208 |
| Pick: `apply_selection` with its depsgraph update, ms | 14.1 (13.7–17.6) | 11.3 (11.2–11.4) |
| Box selection of 1,886 elements: `apply_selection`, ms | 24.8 (24.7–25.4) | 11.4 (11.1–12.5) |
| `read_blender_selection`, pick and box, ms | 5.1, 5.2 | 3.7, 3.8 |

**ALab, batching only large groups** (one session; medians with ranges, seconds unless marked):

| | Minimum 5 | Minimum 20 | Baseline |
|---|---|---|---|
| Blender objects | 5,450 | 6,126 | 7,018 |
| Initial synchronization against the importer (budget 1.5×) | 0.85× | 0.88× | 0.87× |
| Its construction | 0.940 (0.929–0.964) | 0.966 (0.947–1.057) | 1.024 (1.021–1.046) |
| Its evaluation | 0.048 (0.047–0.049) | 0.055 (0.055–0.062) | 0.067 (0.064–0.079) |
| Peak memory against the importer (budget 2×) | 1.55× | 1.55× | 1.57× |
| Small updates (unchanged to material) | 0.416–0.492 | 0.427–0.498 | 0.403–0.506 |
| Their preparation | 0.070–0.072 | 0.071 | 0.043–0.047 |
| Their evaluation | 0.002–0.038 | 0.002–0.046 | 0.002–0.058 |
| Small updates against a full rebuild (budget 10×) | 5.4–6.1× | 5.4–6.1× | 5.4–6.3× |
| Time step, payload unload, payload load | 1.028, 1.252, 2.108 | 1.232, 1.311, 2.150 | 1.508, 1.558, 2.357 |
| Pick of a copy kept as an object: `apply_selection` with its depsgraph update, ms | 8.6 (8.5–11.8) | 8.4 (8.2–8.5) | 11.5 (11.4–12.6) |
| Box selection of 1,886 elements: `apply_selection`, ms | 15.5 (15.4–15.6) | 13.8 (13.2–14.1) | 11.7 (11.6–12.3) |
| `read_blender_selection`, pick and box, ms | 3.0, 3.1 | 2.5, 2.6 | 3.7, 3.8 |

**Findings:**
- **Batching removes Blender's per-object costs where copies batch.** At 30,001 objects, construction falls from 6.2 s to 0.12 s, the evaluation after an update from 0.71–0.87 s to 1–3 ms, and a selection's mirroring from 119 ms to 3 ms. Initial synchronization meets its budget there (0.62× the importer), and peak memory and file size halve or better.
- **Small updates still miss ten times faster than a full rebuild,** and by more than the baseline at 30,001 objects, though each takes about a third as long (0.28–0.37 s): the full rebuild fell further. Preparation is most of each, and in an ad hoc profile of one instance-transform update it was reading the plan's 30,001 records (52 ms) and regrouping them all in Python (110 ms), against 14 ms to build the two batches' new points. Grouping in the planner, or only what the diff changed, would remove most of it (not built).
- **`pick_element` grows with its batch:** 3.2 ms for a batch of 15,000, against 0.3 ms for 1,500.
- **On ALab, batching changes little.** Its 657 batches leave 6,261 objects, synchronization and small updates take within a few percent of the baseline, and mirroring a box selection takes twice as long, 24.8 ms against 11.4 ms; that wasn't profiled. Every ALab interaction stays within its budget.
- **Batching only large groups on ALab** leaves fewer objects than batching every group (5,450 at a minimum of 5), but changes little else. Against the baseline, initial synchronization's construction and evaluation are a little faster (by 60–80 ms and 10–20 ms), each small update's preparation is about 25 ms slower, and the small updates themselves are within their ranges. The ratios to a full rebuild are the same, so the budget is missed as much. A box selection's mirroring falls from 24.8 ms (every group, from the first sets) to 15.5 ms at 5 and 13.8 ms at 20, against the baseline's 11.7 ms, so it grows with the number of batches. The time step and payload changes are faster than the baseline's in this session, but this session's baseline was also slower than the first sets' (1.508 s against 1.247 s for the time step), so that isn't attributed to batching. The single pick in each set was of a copy kept as an object.
- **Payload changes at 30,001 objects** fall from 19–27 s to 1.1–3.1 s, since they add or retire three batches instead of 20,000 objects. The unload's remaining time is mostly its capture (about 3.0 s).
- **The single pick's copy:** each ALab set picked a different copy as the one inside the deepest instance context, which the timing chooses from the plan's order, the two baseline sets included. The plan's object order differs between processes, and its content doesn't ([Plans from separate processes](#plans-from-separate-processes)).

#### ALab with point instancers, and viewport frame time

Two further sets ([M4 plan](../plans/M04-prototypes.md), D6 and D7), in one session on 2026-10-29, on AC power throughout, in the environment above:

```sh
# ALab with its point instancers planned (D6), batched at minimums of 5 and 20, then the baseline
uv run python tools/feasibility/hydra_bridge/measure/run.py --scenes alab-instancers \
    --modes prototype importer-matched interaction --scenarios all --representation batched --batch-minimum 5 \
    --out build/hydra-bridge/measure-pi-min5
# likewise with --batch-minimum 20 (measure-pi-min20), and --representation objects (measure-pi-objects)
# Viewport frame time, in windows on the screen: batched with the importer, then the baseline
uv run python tools/feasibility/hydra_bridge/measure/run.py --scenes updates alab-instancers \
    --only updates-10000 alab-instancers --modes viewport importer-viewport --representation batched \
    --batch-minimum 5 --out build/hydra-bridge/measure-viewport-batched
# likewise with --modes viewport --representation objects (measure-viewport-objects)
```

**ALab with point instancers** (`alab-instancers`): ALab's measurement entry layer without deactivating its 21 point instancers, which the plan translates with `point_instancers` (D6), and which Blender's importer imports too, as 21 point-cloud objects with Geometry Nodes instancing. Its plan has 15,159 objects, 8,141 of them point-instanced, against `alab`'s 7,018. Its update scenarios are `alab`'s, except that `instance-transform` moves a native instance root, and `shared-geometry` edits the mesh with the most copies, which here is a point instancer's prototype (2,407 copies). The matched importer's time rose through the session, 3.685, 3.852, then 4.197 s, so differences between the sets of about 15% or less aren't attributed to the representation.

| | Minimum 5 | Minimum 20 | Baseline |
|---|---|---|---|
| Batches → Blender objects | 379 → 6,981 | 78 → 8,087 | 15,159 |
| Initial synchronization against the importer (budget 1.5×) | 1.09× | 1.23× | 1.47× |
| Its construction | 1.224 (1.207–1.247) | 1.297 (1.266–1.431) | 3.514 (3.244–3.580) |
| Peak memory against the importer (budget 2×) | 1.58× | 1.59× | 1.59× |
| Small updates (unchanged to material) | 0.61–0.75 | 0.72–0.86 | 0.62–0.81 |
| Their preparation | 0.18–0.19 | 0.19–0.21 | 0.10–0.13 |
| Small updates against a full rebuild (budget 10×) | 5.3–6.2× | 5.5–6.5× | 7.6–10.0× |
| Time step, payload unload, payload load | 1.468, 2.015, 3.392 | 1.775, 2.195, 3.435 | 2.577, 3.147, 5.706 |
| Pick of a copy kept as an object: `apply_selection` with its depsgraph update, ms | 12.1 (12.0–12.4) | 11.7 (10.6–11.9) | 23.2 (22.6–23.5) |
| Box selection of 1,886 elements: `apply_selection`, ms | 19.7 (19.6–20.0) | 18.7 (16.8–20.2) | 22.7 (22.4–23.6) |
| `read_blender_selection`, pick and box, ms | 6.0, 6.3 | 5.1, 4.9 | 11.1, 11.0 |

**Viewport frame time** (`--modes viewport importer-viewport`): the run's synchronization, then `viewport_timing.py` in a windowed Blender, its window 1,600 × 1,000 points and its 3D view 2,622 × 1,758 pixels, on an Apple M1 Max through Metal. The view is framed on everything, with nothing selected. Each frame turns the view a degree about Z and redraws the window with a swap, so every frame draws the scene, as orbiting does; a still view would redisplay its converged samples. The swap waits for the display's refresh, so no frame is shorter than 8.3 ms (120 Hz), and one at that floor can't be told from a faster one. Each run's median over 5 repeats of 20 frames, as a median and range over 3 runs, in ms:

| Orbiting frame | Batched (minimum 5) | Baseline | Importer |
|---|---|---|---|
| `updates-10000`, Solid | 8.5 (8.4–8.6), at the floor | 59.9 (58.1–59.9) | 71.0 (68.2–73.4) |
| `updates-10000`, Material Preview | 15.6 (15.5–15.6) | 77.1 (75.4–77.9) | 129.5 (126.8–131.1) |
| `alab-instancers`, Solid | 16.7 (15.9–16.9) | 30.7 (29.8–33.0) | 35.7 (35.7–38.4) |
| `alab-instancers`, Material Preview | 21.2 (20.6–22.2) | 34.4 (33.8–39.7) | 60.5 (59.7–64.0) |

The importer is a reference only: its matched options import no preview materials (no node trees), so its Material Preview shades something else. Each run's first frame and its wait for shader compilation were recorded too, but after each set's unrecorded warmup run, with the shaders already in the system's cache, so they aren't cold-start figures; Material Preview's wait was under 0.1 ms in every run.

**Findings:**
- **With its point instancers, ALab batches, and batching pays.** At a minimum of 5, its 15,159 plan objects become 6,981 Blender objects. Construction falls from 3.5 s to 1.2 s, and initial synchronization from 1.47× the importer's time, at its budget's edge, to 1.09×. A time step and the payload changes take about 40% less time, and a pick's mirroring and the reading of Blender's selection about half.
- **The viewport draws faster batched in every case measured:** at 30,001 objects, Solid orbits at the display's refresh against 59.9 ms, and Material Preview at 15.6 ms against 77.1 ms; on ALab with its point instancers, 16.7 ms against 30.7 ms, and 21.2 ms against 34.4 ms.
- **Small updates take as long either way,** about 0.6–0.8 s on ALab with its point instancers, so their ratio to the now faster full rebuild is lower batched: 5.3–6.2× against 7.6–10.0×, where the baseline's shared-geometry update just reaches 10×. A batched update's preparation is 60–80 ms slower; on `updates-10000` an ad hoc profile put that in reading and regrouping every plan record, and it wasn't profiled here.
- **A minimum of 5 did no worse than 20 anywhere,** and better in initial synchronization (1.09× against 1.23×, each against its own set's importer) and the time step (1.47 s against 1.78 s); the other differences are within the session's drift. At 20, 7,775 copies stay objects, against 5,465 at 5.
- **Not measured:** frame time on other GPUs or at other view sizes, other orbits or viewpoints, frames below the display's refresh, render (Cycles or EEVEE final renders), and the cold-start shader compilation.

#### Small updates without Python's whole-plan work

[M4 plan](../plans/M04-prototypes.md), D8: the bridge's module forms the batched display's groups (`plan.batch_groups`), and both representations' updates read only the plan records and meshes they build from (`plan.objects_at`, `plan.meshes_at`), where they read every record before. One session on 2026-10-29, on AC power throughout, 3 repeats of each mode:

```sh
uv run python tools/feasibility/hydra_bridge/measure/run.py --scenes updates alab-instancers \
    --only updates-10000 alab-instancers --modes prototype importer-matched --scenarios all \
    --representation batched --batch-minimum 5 --out build/hydra-bridge/measure-d8-batched
# likewise with --representation objects (measure-d8-objects)
```

The groups are those the Python grouping formed: on every scene measured here and the bridge's test fixtures, at minimums of 2, 5, and 20, the same keys, members, and order (ad hoc). In an ad hoc profile of one transform update, `batch_update.prepare` took 0.027 s on ALab with its point instancers and 0.017 s on `updates-10000`, against 0.18 s and 0.16 s before.

**Batched small updates** (seconds, medians; the earlier sets' in brackets, from other sessions: D5 for `updates-10000` and D7 for ALab with its point instancers):

| | `updates-10000` | ALab with point instancers |
|---|---|---|
| Unchanged refresh | 0.144 [0.284] | 0.585 [0.608] |
| Transform | 0.143 [0.297] | 0.503 [0.675] |
| Instance transform | 0.294 [0.372] | 0.748 [0.753] |
| Shared geometry | 0.202 [0.300] | 0.532 [0.646] |
| Material | 0.159 [0.326] | 0.507 [0.655] |
| Their preparation | 0.020–0.103 [0.163–0.178] | 0.026–0.037 [0.178–0.185] |
| Against a full rebuild (budget 10×), transform to material | 4.2–8.6× [3.7–4.7×] | 5.4–8.0× [5.3–6.2×] |

**Where a batched transform update's time goes now** (seconds): on `updates-10000`, capture 0.032, planning 0.083, diff 0.005, preparation 0.020, and Blender's publication, retirement, and evaluation 0.003; on ALab with its point instancers, capture 0.038, planning 0.309, diff 0.071, preparation 0.029, and Blender's 0.058.

**The baseline in the same session:** on `updates-10000`, its small updates take 0.88–1.19 s, most of it the depsgraph's evaluation (0.72–0.91 s), and its ratios are 7.1–9.6×. On ALab with its point instancers, they take 0.50–0.63 s, as the batched display's do, and its ratios reach the budget, 9.8–12.3×, since its full rebuild is the slower one: 1.65× the importer's time here, against the batched display's 1.08×.

**Findings:**
- **Python's whole-plan work is gone,** and with it most of preparation. On `updates-10000`, the unchanged refresh and the transform and material updates take about half as long, the shared-geometry update a third less, and the instance-transform update a fifth less. On ALab with its point instancers, the transform, shared-geometry, and material updates take 18–25% less, and the unchanged refresh and instance-transform update about as long, within the difference between sessions.
- **Planning is now most of each batched update:** 58% of a transform update on `updates-10000` and 61% on ALab with its point instancers, where the diff adds 14%. Both still rebuild and compare the whole plan, so no batched update reaches the budget; the closest are transform updates, at 8.6× and 8.0×.
- **An instance-transform update on `updates-10000` still rebuilds two batches' points whole** (15,000 and 10,000 instances), 0.10 s of preparation, though one copy of each moved.
- **The capture of an instance-transform edit** takes 0.08–0.12 s, against 0.03–0.04 s for the other edits. Not profiled.

#### Plans that reuse the previous plan's mesh builds

[M4 plan](../plans/M04-prototypes.md), D9, a probe of incremental planning: with `build_plan(snapshot, previous=plan)`, a mesh prim whose captured container, and its subsets', are the ones the previous plan built it from reuses that build (its mesh, content hash, diagnostics, and slots' prims). An incremental capture shares the container of every prim no notice named, so Hydra's own invalidation decides what is rebuilt. Everything else is planned as before, from the whole snapshot. One session on 2026-10-29, on AC power throughout, 3 repeats of each mode:

```sh
r() { uv run python tools/feasibility/hydra_bridge/measure/run.py --scenes updates alab-instancers \
    --only updates-10000 alab-instancers --modes prototype importer-matched --scenarios all "$@"; }
r --representation batched --batch-minimum 5 --out build/hydra-bridge/measure-d9-batched
r --representation batched --batch-minimum 5 --reuse-builds --out build/hydra-bridge/measure-d9-batched-reuse
r --representation objects --reuse-builds --out build/hydra-bridge/measure-d9-objects-reuse
```

`test_plan_diff.py`'s `test_reused_builds_give_the_same_plan` checks that a plan reusing builds equals the plan built from scratch in every field, after each of 14 chained edits on `F-APPEARANCE-CASES` and on the payload, nested-stress, and point-instancer fixtures, and that an unchanged refresh rebuilds no mesh. In an ad hoc mutation run, four of five single changes failed it: reusing regardless of the prim's container, or without a reused build's diagnostics, slots, or content hash. Comparing the subsets' containers survived, since Hydra recaptures a mesh prim whenever its subsets change, on the edits tested; it's kept.

**Small updates, without and with reuse** (seconds, medians):

| | `updates-10000`, batched | ALab with point instancers, batched | ALab with point instancers, objects |
|---|---|---|---|
| Unchanged refresh | 0.135 → 0.128 | 0.492 → 0.198 | 0.234 |
| Transform | 0.139 → 0.137 | 0.493 → 0.250 | 0.283 |
| Instance transform | 0.269 → 0.256 | 0.567 → 0.356 | 0.445 |
| Shared geometry | 0.187 → 0.182 | 0.531 → 0.242 | 0.329 |
| Material | 0.145 → 0.138 | 0.531 → 0.252 | 0.362 |
| Time step | 0.139 → 0.131 | 1.389 → 1.065 | 2.288 |
| A transform update's planning and diff | 0.079 and 0.005 → 0.077 and 0.005 | 0.299 and 0.066 → 0.113 and 0.013 | 0.140 and 0.013 |
| Against a full rebuild (budget 10×), transform to material | 4.3–8.4× → 4.5–8.4× | 6.8–7.9× → 10.6–15.7× | 13.4–21.1× |

The objects column is with reuse only; D8's objects set, from another session, took 0.50–0.63 s for these updates, at 9.8–12.3×. On `updates-10000`, the baseline's small updates with reuse take 0.85–1.16 s, most of it the depsgraph's evaluation (0.71–0.88 s), at 7.1–9.3×. Reuse doesn't change initial synchronization, which builds with no previous plan: 1.04–1.07× the importer's time batched on ALab with its point instancers, and 1.63× for the baseline, as in D8's session (1.65×).

**Where a batched transform update's time goes with reuse** (seconds): on ALab with its point instancers, capture 0.037, planning 0.113, diff 0.013, preparation 0.029, and Blender's publication, retirement, and evaluation 0.056; on `updates-10000`, capture 0.033, planning 0.077, diff 0.005, preparation 0.019, and Blender's 0.003. In an ad hoc profile of the planning that remains, reading every prim's record from the snapshot took 0.033 s on ALab with its point instancers and 0.025 s on `updates-10000`, and planning every object 0.027 s and 0.013 s.

**Findings:**
- **Reused builds put ALab with its point instancers within the small-update budget** in both representations: batched, its updates take about half as long, at 10.6–15.7×, and the baseline's reach 13.4–21.1×. Planning falls to 45% of a batched transform update, and the diff to a fifth of its time, since its unchanged meshes now share their arrays with the previous plan's.
- **`updates-10000` gains nothing:** its three meshes were never the cost. Its planning reads 30,017 prims and plans 30,001 objects either way, so its batched updates stay at 4.5–8.4×.
- **What remains of planning is per prim and per object,** read and planned again on every update. Reusing them too would need a table that shares its records with the previous plan's, and dependency tracking for what an object takes from other prims (its frame, its instance context, its materials), which mesh reuse doesn't need.
- **An instance-transform update** still misses the budget only on `updates-10000` (4.5×), where 0.094 s of preparation rebuilds the points of each batch a moved copy is in (D8).
- **Tested only on these edits and scenes:** whether Hydra recaptures every prim an edit affects, as reuse assumes, is checked by the oracle test on its edits, not in general.

#### Display colors under Solid shading's Attribute color

[M4 plan](../plans/M04-prototypes.md), D10: Solid shading's Attribute color (`shading.color_type = "VERTEX"`) shows each mesh's active color attribute, a point or corner one only (ad hoc renders: a face or instance attribute doesn't show). D10 measured this display:

- **Vertex and faceVarying** `displayColor` are point and corner attributes already, and each mesh's active color.
- **Uniform** `displayColor` is a corner attribute, each face's value on its corners ([D12](#uniform-display-colors-on-corners-only)).
- **Constant** `displayColor` is per copy. A mesh whose copies all share one holds it, with the copy's `displayOpacity` as alpha, as a point attribute named `displayColor`.
- **Any other copy** had a Geometry Nodes modifier that stored its own constant color on points, or removed the mesh's color from a copy without one, which Blender evaluates apart from its mesh's other copies. D13 removed these ([No per-copy display color workarounds](#no-per-copy-display-color-workarounds)), and decides held colors in the planner.

All are float colors. One session on 2026-10-29, on AC power in High Power mode throughout, 3 repeats of each mode, each pair running the previous commit's code (on its own build of the bridge) and then D10's:

```sh
r() { uv run python tools/feasibility/hydra_bridge/measure/run.py --scenes alab-instancers --reuse-builds "$@"; }
r --modes prototype --scenarios payload-load payload-unload --representation batched --batch-minimum 5 \
    --out build/hydra-bridge/measure-d10d-batched
r --modes viewport --representation batched --batch-minimum 5 --out build/hydra-bridge/measure-d10d-viewport-batched
# likewise with --representation objects (measure-d10d-objects, measure-d10d-viewport-objects)
```

`isolated/test_baseline.py` checks, on both representations and on `F-APPEARANCE-CASES` and `F-NESTED-STRESS`, that each copy's evaluated mesh has its display color as its active color attribute, on its interpolation's domain (corners for uniform), with a constant color's opacity as alpha. It also checks that only a copy whose constant color its mesh doesn't hold has a modifier. `isolated/test_update.py` checks that after each edit, each copy shows what a fresh application shows, with a fresh application's modifiers on the meshes the update builds. A mesh the update keeps keeps the color its copies shared when it was built. In an ad hoc mutation run, 13 of 14 single changes failed them. The survivor leaves out tagging an object for evaluation when its modifier's inputs change: no update changes an existing modifier's inputs, since an object's color is set only when it is created.

**ALab with its point instancers, the previous commit → D10** (medians):

| | Objects | Batched |
|---|---|---|
| Display color modifiers | 0 → 5 | 0 → 5, beside the batches' 1,137 |
| Building the display, s | 3.28 → 3.36 | 1.26 → 1.28 |
| First evaluation, s | 0.085 → 0.086 | 0.064 → 0.055 |
| Peak memory during synchronization, MB | 3,398 → 3,496 | 3,313 → 3,465 |
| Solid, orbiting frame, ms | 30.0 → 29.9 | 16.6 → 16.4 |
| Material preview, orbiting frame, ms | 34.2 → 34.7 | 20.4 → 20.4 |
| Payload load and unload updates, s | 5.86 and 3.12 → 5.55 and 3.08 | 3.53 and 2.10 → 3.37 and 2.05 |

In an ad hoc count of the plan, 2,345 of ALab's 3,393 meshes hold their copies' constant color (3.65M points), and 341 hold a uniform one on corners (4.25M corners). Together they are about 126 MB of float colors, against the 98–152 MB that peak memory rose.

**The other ways measured** (same harness, against the previous commit's code in the same session):
- **A modifier on every copy with a constant or uniform color**, on AC power: 7,734 modifiers as objects. Solid's orbiting frames took 24% longer in both representations, and material preview's 33% as objects and 24% batched. Peak memory rose 150–240 MB.
- **Uniform colors through the modifier, constant colors held by meshes**, on battery in High Power mode: 1,518 modifiers as objects, 1,513 of them for uniform colors, on copies holding 3.05M points. Solid's orbiting frames took 7% longer, and material preview's 22% as objects and 9% batched.
- **8-bit colors** (`BYTE_COLOR`) for `displayColor` and its copies, on AC power in High Power mode: frame times as the previous commit's, and peak memory 13–55 MB higher, but building the display took 0.70 s longer batched and 1.44 s as objects. Blender converts each element of an 8-bit color attribute, at about 60 ns, from linear floats or from sRGB alike, against 2 ns for a float color (ad hoc), and ALab writes about 10.8M.

**Findings:**
- **Every display color shows under one setting at about the previous cost,** apart from memory: frame times, construction, evaluation, and updates are within the runs' ranges, and peak memory rises about 100–150 MB, the colors the meshes hold.
- **A modifier on a copy costs it its mesh's sharing in the viewport.** Each modified copy is evaluated as its own mesh, which by the frame times and memory measured costs a whole mesh's evaluation and drawing per copy, not just its colors. Not measured directly.
- **Colors only shown are still floats:** 8-bit colors held ALab's added peak memory to 13–55 MB, in another session, at about 60 ns an element to write, 0.6 s for ALab's 10.8M.
- **The extra attribute** is ordinary Blender data that detach keeps: a mesh's held constant color shows in the attribute list.
- **Measured only on ALab,** where one mesh has copies with differing constant colors, and only these viewpoints and view size. A scene whose copies of one mesh mostly differ in constant color would need a modifier on most of them.

#### Uniform display colors on corners only

[M4 plan](../plans/M04-prototypes.md), D12: a uniform `displayColor` or `displayOpacity` is a corner attribute, each face's value on its corners, without the face attribute D10 kept beside it. One session on 2026-10-30, on AC power in High Power mode, 3 repeats, each pair running the previous commit's code (on its own build of the bridge) and then D12's:

```sh
r() { uv run python tools/feasibility/hydra_bridge/measure/run.py --scenes alab-instancers --reuse-builds --repeats 3 "$@"; }
r --modes prototype --representation batched --batch-minimum 5 --out build/hydra-bridge/measure-d12-batched
r --modes prototype --representation objects --out build/hydra-bridge/measure-d12-objects
```

**ALab with its point instancers, the previous commit → D12** (medians, with ranges):

| | Objects | Batched |
|---|---|---|
| Building the display, s | 3.89 (3.88–4.06) → 3.78 (3.71–3.80) | 1.46 (1.39–1.75) → 1.67 (1.53–1.70) |
| First evaluation, s | 0.098 (0.096–0.125) → 0.114 (0.088–0.132) | 0.078 (0.063–0.090) → 0.091 (0.089–0.102) |
| Peak memory during synchronization, MB | 3,509 → 3,494 | 3,476 → 3,473 |

- **Peak memory falls 2–15 MB,** against the face attribute's 17 MB: ALab's uniform display colors are about 1.07M faces of float colors (D10's count).
- **The times are within the runs' ranges,** which were wider in this session than in D10's. The viewport's frame time wasn't measured: Solid shading shows the same corner attribute as before.

#### No per-copy display color workarounds

[M4 plan](../plans/M04-prototypes.md), D13: D10 showed a copy's constant display color, where its mesh held another or none, with a Geometry Nodes modifier. Two ways were compared ad hoc: D10's modifiers, and a plan setting, since removed, that gave such copies meshes of their own, one per color, each holding its copies' color on every point. Neither was adopted (with the user): a copy whose color its mesh's other copies don't share shows it as its object color, and Solid shading's Attribute color shows none for it. One session on 2026-10-30, on AC power in High Power mode, 3 repeats, `measure/run.py --reuse-builds --repeats 3 --modes prototype viewport`, objects and batched at a minimum of 5. The modifier sets ran first, then the split sets.

The generated scenes (`measure/stress.py`, `colors`) have 1,000 native instances of one unbound 32×32 grid mesh (1,089 points), each root with a constant `displayColor`: `colors-1000` gives each copy its own, `colors-1000-palette-8` one of 8 in turn.

**The comparison, medians** (objects, then batched):

| Scene | | Modifiers | Split |
|---|---|---|---|
| ALab with its point instancers | synchronization, s | 6.83; 4.49 | 6.26; 4.04 |
| | peak memory, MB | 3,473; 3,432 | 3,492; 3,433 |
| | Solid, orbiting frame, ms | 30.7; 16.7 | 30.4; 16.5 |
| | Material preview, orbiting frame, ms | 35.5; 20.4 | 34.6; 20.2 |
| `colors-1000-palette-8` | meshes; modifiers | 1; 1,000 objects, 8 batched | 8; none |
| | peak memory, MB | 62; 19 | 52; 21 |
| | Solid, first frame, ms | 93; 7.6 | 8.2; 8.4 |
| | Material preview, orbiting frame, ms | 10.5; 8.3 | 8.3; 8.3 |
| `colors-1000` | meshes; modifiers | 1; 1,000 | 1,000; none |
| | synchronization, s | 0.17; 0.16 | 0.34; 0.31 |
| | peak memory, MB | 56; 64 | 191; 199 |
| | Solid, first frame, ms | 97; 92 | 168; 161 |
| | Material preview, orbiting frame, ms | 10.5; 10.5 | 9.7; 9.7 |

Solid's orbiting frames were at the display's refresh (8.33 ms) in every generated case. On `colors-1000-palette-8` batched, the batches already split copies by color, so the modifiers are on the 8 prototypes.

- **Where a mesh's copies share a few colors, splitting is cheaper:** a few meshes instead of a modifier per copy, and no copy evaluated apart.
- **Where every copy has its own color, splitting costs memory and time to build,** since each color is a whole mesh, where a modifier's copy shares its mesh's arrays (an inference from the memory measured). Drawing is no slower.
- **ALab can't tell them apart:** only one of its meshes has copies of differing colors.

**The decision measured:** no modifiers and no split meshes, with each mesh's held color decided by the planner, against the previous commit (D12's, on its own build of the bridge) on ALab, and against the comparison's modifier sets on the generated scenes, in the same session:

```sh
r() { uv run python tools/feasibility/hydra_bridge/measure/run.py --reuse-builds --repeats 3 --modes prototype viewport "$@"; }
r --scenes alab-instancers --representation objects --out build/hydra-bridge/measure-d13r-alab-objects
r --scenes colors --representation objects --out build/hydra-bridge/measure-d13r-colors-objects
# likewise batched (--batch-minimum 5)
```

| Scene | | Previous (modifiers) | D13 |
|---|---|---|---|
| ALab with its point instancers | display color modifiers | 5; 5 beside the batches' 1,137 | none |
| | building the display, s | 3.49; 1.30 | 3.27; 1.18 |
| | synchronization, s | 6.55; 4.32 | 6.11; 4.14 |
| | peak memory, MB | 3,459; 3,452 | 3,476; 3,451 |
| | Solid, orbiting frame, ms | 30.4; 16.4 | 28.9; 16.5 |
| | Material preview, orbiting frame, ms | 32.5; 20.2 | 33.1; 19.6 |
| `colors-1000` | Solid, first frame, ms | 97; 92 | 14; 8.1 |
| | Material preview, orbiting frame, ms | 10.5; 10.5 | 8.3; 8.3 |
| | peak memory, MB | 56; 64 | 53; 50 |
| `colors-1000-palette-8` | Solid, first frame, ms | 93; 7.6 | 11; 8.9 |
| | Material preview, orbiting frame, ms | 10.5; 8.3 | 8.3; 8.3 |

The ALab frame times and peak memory are within the runs' ranges. On the generated scenes, Material Preview's frames are now at the display's refresh.

**Findings:**
- **Without per-copy workarounds, the display costs what D10's held colors do,** and nothing per copy whose color differs from its mesh's other copies.
- **Under Solid shading's Attribute color, such a copy shows none of its own:** on ALab 5 copies of one 76-point mesh. Solid shading's Object color and Material Preview show it.

#### Carriers per selection state

[M4 plan](../plans/M04-prototypes.md), D14: a batch has a carrier for each selection state its points hold, so an unselected batch has one, against D3's three carriers per batch. One session on 2026-10-30, on AC power in High Power mode, 3 repeats, the previous commit's code (on its own build of the bridge) and then D14's, batched:

```sh
r() { uv run python tools/feasibility/hydra_bridge/measure/run.py --reuse-builds --repeats 3 --representation batched \
    --modes prototype interaction viewport --scenarios instance-transform "$@"; }
r --scenes alab-instancers --batch-minimum 5 --out build/hydra-bridge/measure-d14-alab-after
r --scenes updates --only updates-10000 --out build/hydra-bridge/measure-d14-updates-after
```

The interaction timing clears the selection before each mirroring, so a mirroring creates the carriers it needs.

**Medians, three carriers → D14:**

| | ALab with its point instancers (minimum 5) | `updates-10000` |
|---|---|---|
| Blender objects | 6,981 → 6,223 | 13 → 7 |
| Carriers | 1,137 → 379 | 9 → 3 |
| Building the display, s | 1.23 → 1.19 | 0.038 → 0.040 |
| First evaluation, s | 0.067 → 0.051 | 0.002 → 0.002 |
| Peak memory during synchronization, MB | 3,428 → 3,404 | 562 → 562 |
| Solid, orbiting frame, ms | 16.6 → 15.1 | 8.6 → 8.3 |
| Material preview, orbiting frame, ms | 21.0 → 18.6 | 14.5 → 14.9 |
| A pick's `apply_selection`, with the depsgraph update, ms | 13.1 → 10.4 | 2.4 → 2.8 |
| A box selection's `apply_selection`, ms | 19.0 → 27.0 | 3.1 → 3.3 |
| `read_blender_selection`, ms | 6.1 → 3.8 | 6.0 → 3.7 |
| Instance-transform update: preparation, evaluation, s | 0.032, 0.041 → 0.034, 0.037 | 0.098, 0.001 → 0.097, 0.001 |

Synchronization was 3.98 s (3.83–5.78) and 4.17 s (3.93–4.32) on ALab, within each other's range.

**Findings:**
- **Unselected batches cost one carrier,** which on ALab removes 758 objects and shortens the orbiting frames by 9–12%.
- **A selection that spans many batches creates their carriers,** so a box selection's mirroring is slower, within its budget (250 ms). A single pick's is faster, since it evaluates fewer carriers.

**Batch minimums with per-state carriers** (the same session, batched, medians; the transform scenario at a minimum of 5 in a run of its own):

```sh
r --scenes alab-instancers --batch-minimum 3 --scenarios instance-transform transform --out build/hydra-bridge/measure-d14-alab-min3
```

| ALab with its point instancers | 5 | 3 | 2 |
|---|---|---|---|
| Batches; Blender objects | 379; 6,223 | 600; 5,896 | 1,040; 5,896 |
| Synchronization, s | 4.17 | 4.03 | 4.16 |
| Peak memory during synchronization, MB | 3,404 | 3,438 | 3,439 |
| Solid, orbiting frame, ms | 15.1 | 14.2 | 13.9 |
| Material preview, orbiting frame, ms | 18.6 | 17.9 | 17.7 |
| A pick's `apply_selection`, ms | 10.4 | 11.3 | 42.8 (14.0–43.8) |
| A box selection's `apply_selection`, ms | 27.0 | 34.6 | 70.4 |
| Transform and instance-transform updates against a full rebuild | 16.6×, 11.3× | 16.4×, 11.4× | 16.0×, 12.2× |

- **A minimum of 3 removes 327 more objects than 5,** for shorter frames and a little longer mirroring, within the budgets.
- **A minimum of 2 removes none more than 3,** since a batch of two copies is two objects, and its 440 more batches put a pick's mirroring near its budget.

#### Plans from separate processes

Plans of one scene from separate processes can order their records differently, and hold the same content (M4 Phase D, D11).

- **The check:** `isolated/test_plan_diff.py::test_separate_processes_plan_the_same_content` plans `F-APPEARANCE-CASES`, `F-NESTED-STRESS`, and the point-instancer scene in four processes each. It compares a digest of each plan's content in any order: each object with its mesh's and materials' content in place of their indices, the meshes, the materials with their sources sorted, the diagnostics, and the universe.
- **A shared mesh's name depended on the order.** The check first failed intermittently on `F-APPEARANCE-CASES`: a mesh that two prims share was named after whichever the planner reached first. It now takes the least of its uses' names. With that change reverted, the check failed in each of three runs.
- **On ALab with its point instancers** (ad hoc, three processes of the Blender binary, at default time): every process planned 15,157 objects with the same content digest, and each in a different order.
- **The likely cause** is that the planner keys some maps by `SdfPath`'s hash, which differs between processes. This is inferred from the code, not isolated.

### Playback of time-sampled data (M4 Phase E)

M4 Phase E's representations of time-sampled data ([M4 plan](../plans/M04-prototypes.md), E2–E7) played back in the same session: E2's per-time-code snapshots (with moves), and the cached display with its meshes' samples as attributes (E3–E5) or in a USD file read by Mesh Sequence Cache modifiers (E6), each as the object baseline and batched at a minimum of 3. Run on the reference hardware (M1 Max, 32 GB, macOS 26.5.1, AC power) in the Blender 5.2.2 binary (`d13f752e3b9c`), 2026-11-02, three runs each in fresh processes. Reproduce with:

```sh
uv run python tools/feasibility/hydra_bridge/build.py
uv run python tools/feasibility/hydra_bridge/measure/playback.py --repeats 3 --check
# The sequence caches on ALab, writing what the reader alters
uv run python tools/feasibility/hydra_bridge/measure/playback.py --scenes alab --approaches sequence --repeats 3 \
    --check --lossy --out build/hydra-bridge/playback-lossy
```

Each run builds the display at the scene's first frame, sets each later frame in turn (its first visit), then sets every frame again (a revisit), and saves the `.blend` uncompressed. The scenes are ALab with its point instancers, 1004 to 1057; the harness's `animation` scene (frames 1 to 24 of a 66k-point deforming grid and 1,000 moving cubes); and `scatter-10000`, a point instancer of 10,000 points over four 16 × 16 grids, frames 1 to 24, every point moving every frame, 5% switching prototype each frame, and one prototype deforming. With `--check`, each cached display matched fresh plans at its second, middle, and last frames, after the timings, in every run. On ALab the sequence caches refuse meshes holding `st` on points, which Blender's reader gives back on corners, at the first frame after the build; with `--lossy` they write them anyway (`st` as a vertex float2, a display color without its opacity), and then six display colors differ from fresh plans at each frame checked, their opacity lost.

Medians over the three runs, with their range: a frame's first visit and a revisit are each run's median, and the heap is its live heap once every frame has been visited, above the empty scene's.

| ALab | Build (s) | First visit (s) | Revisit (ms) | Heap (MB) | `.blend` (MB) |
|---|---|---|---|---|---|
| Snapshots, objects | 5.60 (5.23–6.14) | 0.79 (0.78–0.82) | 799 (769–816) | 3,064 | 1,171 |
| Snapshots, batched | 3.39 (3.32–3.39) | 0.53 (0.52–0.55) | 529 (520–562) | 2,991 | 1,139 |
| Attributes, objects | 5.61 (5.55–6.04) | 0.37 (0.36–0.40) | 10.1 (10.0–10.7) | 3,567 | 1,534 |
| Attributes, batched | 3.53 (3.47–3.70) | 0.38 (0.37–0.39) | 10.2 (10.2–10.6) | 3,561 | 1,502 |
| Sequence, objects (lossy) | 6.29 (5.61–6.50) | 0.43 (0.41–0.47) | 26.5 (20.7–34.8) | 6,517 | 1,198, and 295 of USD |
| Sequence, batched (lossy) | 3.83 (3.49–3.93) | 0.43 (0.42–0.43) | 23.6 (21.5–26.2) | 6,511 | 1,166, and 295 of USD |

| Scatter | Build (s) | First visit (s) | Revisit (ms) | Heap (MB) | `.blend` (MB) |
|---|---|---|---|---|---|
| Snapshots, objects | 0.36 (0.36–0.37) | 1.30 (1.27–1.34) | 1,346 (1,337–1,359) | 308 | 27 |
| Snapshots, batched | 0.06 | 0.052 (0.052–0.055) | 51.7 (49.6–52.6) | 16 | 1 |
| Attributes, objects | 0.48 (0.47–0.49) | 4.09 (3.72–4.12) | 212 (212–223) | 1,628 | 449 |
| Attributes, batched | 0.11 | 0.33 (0.32–0.33) | 0.5 (0.4–0.7) | 59 | 33 |
| Sequence, objects | 0.47 (0.45–0.52) | 3.76 (3.51–4.19) | 216 (216–224) | 1,572 | 437 |
| Sequence, batched | 0.12 (0.12–0.14) | 0.33 (0.31–0.33) | 0.5 (0.5–0.6) | 59 | 33 |

| `animation` | Build (s) | First visit (s) | Revisit (ms) | Heap (MB) | `.blend` (MB) |
|---|---|---|---|---|---|
| Snapshots, objects | 0.09 | 0.076 (0.073–0.077) | 73.1 (71.7–75.5) | 64 | 9 |
| Snapshots, batched | 0.06 | 0.038 | 37.5 (36.7–38.0) | 36 | 7 |
| Attributes, objects | 0.11 | 0.089 (0.088–0.090) | 3.9 (3.8–4.1) | 129 | 45 |
| Attributes, batched | 0.08 | 0.042 | 0.2 | 60 | 26 |
| Sequence, objects | 0.12 | 0.096 | 10.0 (9.9–10.2) | 225 | 28, and 20 of USD |
| Sequence, batched | 0.09 | 0.048 | 6.7 (6.7–7.0) | 156 | 8, and 20 of USD |

- **A revisit** is a step through the update path for snapshots, so it costs as much as a first visit, and for the cached display no synchronization at all: on ALab, 10 ms against 0.53 to 0.80 s, and a revisit of the sequence caches 24 to 27 ms, as each varying mesh is read from USD at each frame change.
- **A first visit** of the cached display on ALab took 0.37 to 0.43 s, against a snapshot step's 0.79 s as objects and 0.53 s batched. On the scatter, where every track moves every frame, a snapshot step is faster than caching the frame: 1.30 s against 4.09 and 3.76 s as objects, and 52 ms against 0.33 s batched; each revisit costs a step again. In the cached display the first visit after the build is the slowest (in the first of the three runs: 11.4 s and 10.5 s for the scatter's objects, attribute and sequence caches, against 5.4 s and 4.7 s for the next slowest; 1.0 to 1.6 s on ALab, against 0.4 to 0.8 s).
- **Memory:** snapshots hold one frame, so the least heap and the smallest `.blend`. On ALab once filled, the attribute caches held about 500 MB more heap than snapshots, and the sequence caches about 2,950 MB more than the attribute caches (not broken down), with a USD file of 295 MB beside the `.blend`, which took 2.7 and 2.3 s to save (objects, batched). Batched, the scatter's cached display holds 59 MB against 1.6 GB as objects.
- **Not measured:** viewport frame time while playing, and Linux and Windows.

### Batch minimum (M4 Phase F)

The smallest group of copies that the display batches ([M4 plan](../plans/M04-prototypes.md), F2), measured through the cached display with attribute caches (E3–E5), as objects and batched, in the environment of [Playback of time-sampled data](#playback-of-time-sampled-data-m4-phase-e) (2026-11-02, AC power), three runs each in fresh processes. Reproduce with:

```sh
uv run python tools/feasibility/hydra_bridge/measure/playback.py --approaches attributes --repeats 3 --check --frames 24 \
    --scenes groups-1 groups-2 groups-3 groups-4 groups-5 groups-6 groups-8 groups-10 groups-12 groups-20 \
    --batch-minimum 2 --out build/hydra-bridge/playback-groups
# Real scenes, as objects, then batched at each minimum (2, 3, 5, 8 for ALab only, and 10)
uv run python tools/feasibility/hydra_bridge/measure/playback.py --approaches attributes --repeats 3 --check --frames 24 \
    --scenes alab alab-objects SCENE.usd ... --representations objects --out build/hydra-bridge/playback-real-objects
uv run python tools/feasibility/hydra_bridge/measure/playback.py --approaches attributes --repeats 3 --check --frames 24 \
    --scenes alab alab-objects SCENE.usd ... --representations batched --batch-minimum 5 --out build/hydra-bridge/playback-real-min5
```

`groups-N` (`measure/stress.py`) is 6,000 copies of 4 × 4 grids, in groups of N copies of equal content, unlike any other group's, every copy moving every frame, frames 1 to 24: the worst case for batches, whose points cache every copy's transform each frame. The real scenes are ALab with and without its point instancers, Pixar's Kitchen set (`Kitchen_set_instanced.usd`), the OpenPBR Shader Playground (`ShdrPlygrnd_OpenPBR.usda`), and Intel's Moore Lane (`4004MooreLane_Assembly.usda`), each visited for at most 24 frames after its first. Every cached display matched fresh plans at its checked frames, but one Moore Lane mesh in every run, as objects and batched alike: its primvar `custom_normal` takes the name of Blender's custom normals, and Blender alters what is written to it.

Medians over the three runs; a frame's first visit and a revisit are each run's median, and the heap is the live heap once every frame has been visited.

| Group size | Build (s), objects / batched | First visit (s) | Revisit (ms) | Heap (MB) | Blender objects |
|---|---|---|---|---|---|
| 1 | 0.84 / 0.82 | 0.52 / 0.53 | 33.7 / 33.8 | 712 / 711 | 6,000 / 6,000 |
| 2 | 0.68 / 1.01 | 0.59 / 0.44 | 39.1 / 71.5 | 639 / 656 | 6,000 / 3,000 |
| 3 | 0.65 / 0.70 | 0.58 / 0.37 | 32.2 / 46.6 | 616 / 488 | 6,000 / 2,000 |
| 4 | 0.64 / 0.60 | 0.52 / 0.34 | 30.2 / 34.6 | 606 / 406 | 6,000 / 1,500 |
| 5 | 0.62 / 0.56 | 0.53 / 0.36 | 31.3 / 28.1 | 599 / 356 | 6,000 / 1,200 |
| 6 | 0.67 / 0.54 | 0.53 / 0.31 | 31.5 / 23.4 | 594 / 319 | 6,000 / 1,000 |
| 10 | 0.60 / 0.45 | 0.52 / 0.27 | 30.0 / 12.7 | 584 / 253 | 6,000 / 600 |
| 20 | 0.61 / 0.41 | 0.53 / 0.26 | 30.3 / 6.5 | 577 / 204 | 6,000 / 300 |

| ALab with its point instancers | Build (s) | First visit (s) | Revisit (ms) | Heap (MB) | Blender objects |
|---|---|---|---|---|---|
| Objects | 6.15 | 0.37 | 8.3 | 3,333 | 15,159 |
| Batched, minimum 2 | 3.73 | 0.40 | 10.8 | 3,368 | 4,845 |
| Minimum 3 | 4.28 | 0.39 | 8.7 | 3,326 | 5,286 |
| Minimum 5 | 3.58 | 0.36 | 7.4 | 3,303 | 5,842 |
| Minimum 8 | 3.92 | 0.38 | 7.4 | 3,292 | 6,734 |
| Minimum 10 | 3.60 | 0.35 | 6.7 | 3,289 | 7,159 |

- **Where batching pays:** from groups of 5, a batch costs less than its copies as objects in every measure. Batches of 2 and 3 cost more to revisit, the cost of playing a cached frame (71.5 and 46.6 ms against 39.1 and 32.2 ms), and those of 2 more to build; groups of 4 are about even. On ALab, every minimum builds faster than objects (3.6–4.3 s against 6.2 s), and from 5 each revisits faster too.
- **Where it doesn't matter:** on ALab without its point instancers (7,018 copies), the Kitchen set (1,788, groups up to 174), the Shader Playground (346), and Moore Lane (707, groups up to 18), no minimum differs consistently from objects: their figures move both ways between minimums, mostly within their runs' spread, as few of their copies are in groups.
- **Not measured:** viewport frame time, selection on the cached display's batches, copies that hold still, and other hardware.

#### Moana Island at scale

Disney's Moana Island scene (`island/usd/island.usda`, 16 GB) exhausted this machine's 32 GB through the bridge when opened whole (by the user), so it was surveyed one element at a time, each in a child process killed past 8 GB of resident memory (ad hoc, one run). Every element is a native instance of a prototype, and its point instancers hold about 31 million instances, 23.0 million in `isBeach` alone. The bridge plans each point instance as a copy (D6): the elements small enough to plan with their instances took about 13 KB of resident memory per planned copy, meshes included (`isBayCedarA1`: 219,005 copies at a 2.9 GB peak), so the whole island's instances would need hundreds of GB. `isDunesB` (65,228 prims, 5.5 million mesh points) passed 8 GB even with its point instancers left out, for a cause not investigated. So scenes of millions of point instances can't be planned instance by instance at all; their batches would need to come from an instancer's arrays without a record per instance.

### Lookups without the bindings' cache (M5 Phase S)

Whether the bindings' in-memory state ([Undo and Runtime State](../spec/lifecycle.md#undo-and-runtime-state)) is needed at scale: lookups without it, against it, with the baseline's display as a binding's manifest, in the environment of [Phase E](#measurements-m1b-phase-e) (Apple M1 Max, Blender 5.2.2 binary, 2026-11-06). The cache was removed after this measurement (DECISIONS.md "Binding records read when called"), so the rows with it can't be measured again; `measure/run.py --scenes updates alab --modes uncached --repeats 3 --out build/hydra-bridge/measure-uncached` now times the runtime's own lookups, which are the rows without it.

**Method** (`measure/uncached_timing.py`):
- **The manifest:** written as C5 writes it ([Ownership lookup after undo](#ownership-lookup-after-undo-m4-phase-c)), one binding's, so every file has one binding.
- **With the cache:** `ownership_index.ownership()` of one object, and of 1,000; the first `ownership()` after `state.invalidate()`, as after an undo; and `binding_configs.find_binding()`.
- **Ownership without the cache, by scan:** every binding record and every manifest read through `configs` and `manifests`, then the claims on the object.
- **Ownership without the cache, by users:** `bpy.data.user_map(subset=...)` of the objects, the collections holding binding records among their users (a manifest's pointer is a user), and a scan of those manifests' stored entries for the pointers; of one object, and of 1,000 at once, as a box select asks. Each way without the cache gave the cache's claims, checked in every run, for the one object and each of the 1,000.
- **A binding lookup without the cache:** every collection's binding records and the index read, and `canonical_candidate.decide` for the identity.
- **The manifest read whole**, as a synchronization without the cache would read it.
- **Statistics:** three processes per scene after a warmup, ten repeats each; each process's median, as a median and range over the processes.

| Operation (ms) | updates-100 | updates-1000 | ALab | updates-10000 |
|---|---|---|---|---|
| Manifest entries | 306 | 3,006 | 11,185 | 30,006 |
| cached ownership, one | 0.002 | 0.002 | 0.002 | 0.002 |
| cached ownership, 1,000 (301 in updates-100) | 0.504 | 1.703 | 1.628 | 1.676 |
| **first ownership after the state is dropped** | 1.373 | 13.112 | **52.452 (51.803–56.938)** | **158.076 (152.137–188.141)** |
| **no cache, ownership by scan** | 1.025 | 10.813 | 42.904 (41.757–46.175) | **127.973 (126.092–133.235)** |
| no cache, ownership by users, one | 0.131 | 1.377 | 9.139 (8.548–9.959) | 22.135 (21.926–22.680) |
| no cache, ownership by users, 1,000 at once (301) | 0.760 | 3.540 | 11.515 (11.148–13.516) | 25.881 (25.473–28.446) |
| cached binding lookup | 0.003 | 0.003 | 0.003 | 0.003 |
| no cache, binding lookup by scan | 0.013 | 0.013 | 0.013 | 0.013 |
| no cache, the manifest read whole | 1.014 | 11.179 | 43.232 (41.214–44.528) | 123.835 (119.076–124.418) |

**Findings:**
- **Ownership by scan needs the cache at scale:** it costs about what rebuilding the cache does, over the 50 ms interaction budget at 30,006 entries and near it on ALab, so a cache that answers it from memory is needed if ownership is looked up that way.
- **Ownership by users fits the budget without a cache** on every scene measured: 9 ms on ALab and 22 ms at 30,006 entries for one object, and 12 ms and 26 ms for 1,000 at once. It grows with the file, since `user_map` walks every datablock; these files hold the display and little else (11,188 datablocks of the kinds counted on ALab), so a file with more unmanaged content costs more, which wasn't measured. Against the cache's microseconds it suits a lookup per operation, such as a pick or a box select, not one per redraw.
- **A binding lookup needs no cache with one binding:** 13 µs without it. More bindings weren't measured in the binary; in the bpy wheel, ad hoc, a scan with 100 bindings took 0.52 ms.
- **The first lookup after an undo is over budget on ALab here,** 52 ms against C5's 43.9 ms in the same environment, where each first lookup also followed a real undo; ownership by users is cheaper than it at every scale measured.

### The undo step of a synchronization (M5 Phase F)

What the one undo step a published synchronization pushes ([Undo and Runtime State](../spec/lifecycle.md#undo-and-runtime-state)) holds, for M5's full rebuild, with the baseline's display (`apply.py`) standing in for M7's, in the environment of [Phase E](#measurements-m1b-phase-e) (Apple M1 Max, 32 GB, Blender 5.2.2 binary, 2026-11-06). Reproduce with `measure/undo_memory.py --scenes updates alab --exclude updates-10000 --repeats 3`.

**Method** (`measure/undo_memory.py`), in a fresh background process per run, with global undo on:
- **The steps:** the display is built and a step pushed, as after a first synchronization; then three times one object is moved and a step pushed; then four times the whole display is rebuilt from the same plan, the one it replaces removed in one `batch_remove`, the depsgraph evaluated, and a step pushed, as after synchronizing again. Then one undo and one redo, timed.
- **The memory:** the heap in use (`memory.py`), read around each push, and around each rebuild with its push. A control run per scene does the same with global undo off, pushing nothing.
- **Statistics:** three processes per scene and setting; each process's median over its steps, as a median and range over the processes. Blender's preferences as found: 32 undo steps, no memory limit.
- **Left out:** `updates-10000`, whose first rebuild hadn't finished removing the display it replaced after 11 minutes, with the time in `batch_remove` (sampled); removal's cost is Phase F's F2.

| Measure | updates-100 | updates-1000 | ALab |
|---|---|---|---|
| Objects; objects, meshes, and materials | 301; 306 | 3,001; 3,006 | 7,018; 11,185 |
| Heap of the built display (MB) | 9 | 85 | 1,340 (1,339–1,343) |
| `.blend`, uncompressed (MB) | 1 | 8 | 1,117 |
| A push after moving one object (MB) | 0.0 | 0.1 | 4.5 |
| A push after a rebuild (MB) | 1 | 8 | 58 |
| **A rebuild and its push, undo on (MB)** | 1.0 | 8.8 (8.6–8.9) | **1,195 (1,195–1,195)** |
| A rebuild, undo off (MB) | 0.1 | 0.7 (0.7–0.8) | 0.0 (−0.9–0.0) |
| Heap after every step, undo on / off (MB) | 15 / 9 | 136 / 88 | 6,228 / 1,338 |
| A push after a rebuild (ms) | 1 | 5 (4–7) | 77 (65–79) |
| Undo; redo (ms) | 10; 9 | 88; 97 | 272 (261–277); 236 (222–238) |

Two variants on ALab, one process each, without the control: with 2 undo steps, the rebuilds' growth was 1,191, 1,194, −15, and 8 MB; with a 2,048 MB undo memory limit and 32 steps, 1,195, 1,198, 1,156, and 1,185 MB, the heap after every step 6,184 MB.

**Findings:**
- **A full rebuild's step holds about the display's size:** 1.2 GB on ALab, about its uncompressed `.blend` (1.1 GB), and 8.8 MB against 8 MB on `updates-1000`; with undo off a rebuild leaves nothing. On ALab the push itself grew the heap by only 58 MB, and the rest of the growth came at the rebuild before it, which grew 1.14 GB with undo on and nothing with it off. That a step shares the replaced meshes' arrays, so removing them frees nothing while it lives, is an inference: it fits the 2-step variant, whose growth stopped once the oldest step was dropped.
- **A step that keeps its datablocks is small:** moving one object pushed 4.5 MB on ALab, so a step grows with the datablocks a synchronization replaces, not with the display.
- **Only the step count bounds it:** at Blender's default of 32 steps, synchronizing ALab again 32 times would hold about 38 GB, more than this machine's memory (an extrapolation: five steps were measured). The undo memory limit didn't bound it in the variant measured, which is consistent with the limit counting only a step's own data, about 58 MB here.
- **Pushing, undoing, and redoing are fast** beside a rebuild: 77 ms to push after ALab's 12 s rebuild, and 0.27 s to undo.
- **Not measured:** a windowed Blender, Linux and Windows, batched displays, and more than five steps.

### The shared removal's cost (M5 Phase F)

What `removal.remove_unused`, which disposal, retirement, and a cleanup retry share, costs at scale, with the baseline's display (`apply.py`) standing in for M7's, in the environment of [Phase E](#measurements-m1b-phase-e) (Apple M1 Max, Blender 5.2.2 binary, global undo on, 2026-11-06). Reproduce with `measure/removal_cost.py --scenes updates alab --repeats 3`.

**Method** (`measure/removal_cost.py`), in a fresh background process per run:
- **The file:** the display built twice, as a synchronization again holds it before retirement, the published one and the prepared one. Each removal is from the published one, its objects unlinked from their collection first, as publication unlinks them.
- **The cases:** one call of `batch_remove` with one new empty, ten times; units of 1 and 100 objects through `remove_unused`; a unit of 100 objects one of which fails, injected by wrapping the module's `_batch_remove`, through `remove_unused`, which halves the failing call, and through one call per datablock after it, which the removal made before this phase; and the rest of the display through `remove_unused`, each level's call timed by the wrapper. `bpy.data.user_map` of the same datablocks is timed before each.
- **Statistics:** three processes per scene; each case as a median and range over them. On `updates-100` the units take every object, so its rest is only the meshes and materials.

| Case (ms) | updates-100 | updates-1000 | ALab | updates-10000 |
|---|---|---|---|---|
| Datablocks in the file (objects, meshes, materials) | 612 | 6,012 | 22,370 | 60,012 |
| One call of one empty | 0.1 | 1.3 | 13.2 (12.5–17.9) | 25.6 (25.2–28.7) |
| `user_map` of one object; of the rest of the display | 0.2; 0.1 | 1.6; 2.2 | 11.0; 13.9 | 17.2; 23.9 |
| One object | 0.3 | 2.7 | 27.6 (23.1–29.8) | 46.5 (44.7–48.6) |
| 100 objects, one call | 1.3 | 33.5 (26.0–36.7) | 148 (126–150) | 837 (791–1,008) |
| 100 objects, one failing: halving, 15 calls | 1.4 | 42.2 (32.8–45.8) | 205 (189–206) | 1,010 (962–1,139) |
| 100 objects, one failing: one call each after it, 101 calls | 4.8 | 128 (119–147) | 1,356 (1,234–1,440) | 3,461 (2,697–3,924) |
| **The rest of the display, 2 calls** | 0.3 (7 datablocks) | 167 (2,707) | **4,981 (3,930–5,309)** (10,886) | **83,554 (77,616–90,304)** (29,707) |

Ad hoc probes, one run each in the same binary: of 30,000 objects, removing 1,000 took 1.7 to 2.1 s whether they were linked or unlinked, and whether they shared one mesh or each had its own; in a file of only 32,000 objects with their meshes, removing them all took 3.4 s.

**Findings:**
- **A call costs more the more the file keeps:** 13 ms for one empty on ALab and 26 ms at 60,012 datablocks, as M4 found (about 20 ms), and 100 objects 0.15 s and 0.84 s. Across these cases a call's time is roughly proportional to the datablocks it removes times those left in the file, at 30 to 100 ns a pair, an inference from these points: removing nearly everything is cheap (3.4 s for 32,000), and retiring a full display while its replacement is in the file is not.
- **A full rebuild's retirement** took 5.0 s on ALab, about 0.46 ms per datablock, as M4's retirement of the whole display (5.57 s), and 84 s at 29,707 datablocks. Splitting a level into more calls wouldn't lower it if the cost is per pair; removing less, as M7's incremental updates do, would.
- **`user_map` is small** beside the removal: 11 to 14 ms on ALab, 17 to 24 ms at 60,012 datablocks.
- **Halving a failing call** found the one failure among 100 objects in 15 calls, 205 ms on ALab, where one call per datablock took 101 calls and 1,356 ms, since each pays a call's cost. The removal halves since this phase.
- **Not measured:** a windowed Blender, whose event loop may clear what a background process accumulates between calls; Linux and Windows; batched displays.

### The product's synchronization, step by step (M5 Phase F)

Where a synchronization's and a cache call's time goes in the product, against M5's stub application layer, in the environment of [Phase E](#measurements-m1b-phase-e) (Apple M1 Max, Blender 5.2.2 binary, global undo on, 2026-11-06). Reproduce with `measure/synchronization_profile.py --scenes updates alab --repeats 3`.

**Method** (`measure/synchronization_profile.py`), in a fresh background process per run:
- **The calls:** a binding made and attached through the API, then `synchronize` at the scene's time code, `synchronize` again at it (a full rebuild retiring the first generation), and `cache` at the next three time codes. The API pushes its undo step as with a window (`_pushes_undo` patched true).
- **The steps:** each module function the transaction and cache call reach their steps through, wrapped and timed; a time includes the steps it calls.
- **The display:** the stub's placeholders, an object and a bounds mesh for each prim the core's minimal path captures (731 on ALab, against the bridge's 7,018 objects), so this measures M5's own work around evaluation and application, not M7's display.
- **Statistics:** three processes per scene, each step as a median and range over them. The machine's load average was under 4 when the runs began.

| Step (ms) | updates-1000 | ALab | updates-10000 |
|---|---|---|---|
| Placeholders; manifest entries | 1,001; 3,003 | 731; 2,193 | 10,001; 30,003 |
| **Synchronize** | **240 (239–245)** | **1,023 (972–1,048)** | **2,684 (2,678–2,722)** |
| `acquire`; `plans` (the core's capture, M6's) | 16; 67 | 140; 768 | 171; 760 |
| `prepare` (the stub, M7's) | 106 | 67 | 1,060 |
| `publish`, its manifest write included | 13 | 10 | 158 |
| Undo push | 37 | 27 | 516 |
| **Synchronize again** | **229 (227–231)** | **836 (833–851)** | **9,431 (9,414–10,981)** |
| Manifest read; `plans`; `prepare` | 7; 54; 99 | 5; 712; 71 | 72; 712; 7,851 |
| `publish`; `retire` (`user_map` in it) | 18; 3.9 (0.9) | 12; 2.6 (0.5) | 208; 53 (15) |
| Undo push | 48 | 32 | 530 |
| **Cache, three time codes** | **278 (276–292)** | **999 (984–1,026)** | **3,237 (3,228–3,318)** |
| Manifest reads (2); `plans`; `key_time_codes` (the stub) | 15; 63; 174 | 11; 839; 125 | 239; 827; 1,887 |
| `set_manifest_entries` | 30 | 23 | 413 |

**Findings:**
- **M5's own steps are a small part on ALab:** reading and writing the manifest, publication, retirement, and the records, 10 to 40 ms in each call, and the undo push 27 to 32 ms. The core's capture is 75 to 85% of each call there, and the stub's application most of the rest.
- **The plan's tuples were read once per placeholder:** each read of `Plan.resources` builds the tuple anew, converting every resource, and the stub read it several times a placeholder, so `prepare` and `key_time_codes` grew with the square of the plan. Read once per plan, `prepare` on `updates-1000` fell from 760 to 105 ms, a synchronization from 897 to 250 ms, and a cache call from 937 to 296 ms (one process each, before and after).
- **Synchronizing `updates-10000` again** spent 7.9 s in the stub's `prepare`, against 1.1 s the first time: its placeholders are named for their prims, which collide while the old display is still in the file, as M4 found of object names ([its findings](#measurements-m4-phase-c)). M7's objects are named too.
- **At 30,003 manifest entries,** the manifest's whole write is 124 to 150 ms, a read 72 ms, a cache call's two reads 239 ms and its update by entry 413 ms, and the undo push 0.5 s. The update read the manifest again; it now takes the one the cache call read, so a call reads it once (not measured since).
- **Not measured:** M7's display, a windowed Blender, Linux and Windows.

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
- **Results: all pass on macOS arm64, Windows x64 and Linux x64** in the Blender 5.2.2 binary ("Hydra bridge" workflow, [run 38686507163](https://github.com/scottdmilner/proscenium/actions/runs/38686507163), commit `c8141d0`, 2026-10-15). There, each build job packages its zip, and a `distribution` job installs it on a fresh runner with no build tree. Every platform has the same stage counts (7, 8 and 6). The installed module passes the loading checks (42; 43 on Windows) and the 20 prototype checks, and loads only the host's USD library (`libusd_ms.dylib`, `libusd_ms.so`, `blender.shared/usd_ms.dll`). The same run passes every other job: 131 correctness checks per host on all three platforms, with no compiler warnings. The macOS run was first made locally on the reference hardware (2026-10-14).
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
[Source Stages](../spec/source-access.md#source-stages). The bridge's native
objects and lazily queried scene indices are not persisted Blender state.

Native loading holds on all three platforms for this module, and the prototype's correctness,
measurements and distribution are recorded. On that evidence M1b adopted Hydra, with a C++ core
(Phase F of the [M1b plan](../plans/M01b-evaluation-gate.md#phase-f-log), and
[DECISIONS.md](../DECISIONS.md) "Evaluation front end and core language").

## Windows x64

**Go.** All 55 checks pass in all three runtimes ("Feasibility" workflow, [run 38032882242](https://github.com/scottdmilner/proscenium/actions/runs/38032882242), `windows-latest`, 2026-10-10). Apart from paths and timings, every recorded fact matches macOS except those below.

M3's `copies` probe ("Feasibility" workflow, [run 39330194131](https://github.com/scottdmilner/proscenium/actions/runs/39330194131), 2026-10-19): all 108 checks pass in all three runtimes, and the probe's facts are identical to macOS's. The other probes' facts from that run were not compared.

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
  - **For M3's [Layer State and Reloading](../spec/source-access.md#layer-state-and-reloading):** a refresh that relies on non-forced reloads can miss a save made within a second of the previous read on Windows. Forced reloads or another change test avoid it; M3 decides.
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

M3's `copies` probe ("Feasibility" workflow, [run 39330194131](https://github.com/scottdmilner/proscenium/actions/runs/39330194131), 2026-10-19): all 108 checks pass in all three runtimes, and the probe's facts are identical to macOS's. The other probes' facts from that run were not compared.

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
