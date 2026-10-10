# Hydra 2.0 core (Hd / Hdsi / Hf) for a non-rendering USD→Blender consumer

Research date 2026-10-09. Scope: `pxr/imaging/hd`, `pxr/imaging/hdsi`, `pxr/imaging/hf`, and the
`pxr/usdImaging/usdImaging` pieces a consumer of `UsdImagingCreateSceneIndices` touches.

## Labels

- **[v26.03 `path:line`]**: read in an OpenUSD v26.03 checkout (`pxr/...`). This is
  what Blender 5.2 ships. Paths are relative to `pxr/`.
- **[dev `path:line`]**: read in the dev clone (commit `5bc38c9`, 2026-10-07).
- **[guide `line`]**: the in-tree copy of the Hydra Getting Started Guide,
  `extras/imaging/docs/hydra_getting_started_guide.dox` in v26.03. It matches what
  https://openusd.org/release/api/_page__hydra__getting__started__guide.html renders.
- **[docs URL]**: fetched from openusd.org.
- **[inferred]**: my reasoning from the code. Nothing was compiled or run for this report.
- **[bridge `line`]**: `tools/feasibility/hydra_bridge/bridge.cpp` in the project.

---

## 0. Findings about the existing bridge

These came up while checking the code against the questions. Each is detailed in a later section.

1. **The bridge flattens twice.** `UsdImagingCreateSceneIndices` already contains an
   `HdFlatteningSceneIndex` that uses `UsdImagingFlattenedDataSourceProviders()`. The
   `UsdImagingNiPrototypePropagatingSceneIndex` inserts it for the main scene and for every
   prototype [v26.03 `usdImaging/usdImaging/niPrototypePropagatingSceneIndex.cpp:104-113,205-209`;
   header diagram `niPrototypePropagatingSceneIndex.h:80-90`]. The bridge's second
   `HdFlatteningSceneIndex(implicit, HdFlattenedDataSourceProviders())` [bridge 55] mostly gives the
   same results, because flattened xforms carry `resetXformStack=true` and the second pass returns
   them early [v26.03 `imaging/hd/flattenedXformDataSourceProvider.cpp:86-97,126-133`]. It still
   adds a second per-prim cache and a second dirty-propagation pass. The terminal index already
   holds flattened xform, visibility, purpose, primvars (constant ones inherited), coordSysBinding,
   USD material bindings and model/geomModel [v26.03
   `usdImaging/usdImaging/flattenedDataSourceProviders.cpp:25-67`;
   `imaging/hd/flattenedDataSourceProviders.cpp:25-44`].
2. **Without `HdDependencyForwardingSceneIndex`, some dirties are lost.** For example,
   `HdsiImplicitSurfaceSceneIndex` (toMesh) declares in `__dependencies` that
   `primvars/points/primvarValue` depends on the `cube`/`sphere`/... locator. Its own
   `_PrimsDirtied` just forwards [v26.03 `imaging/hdsi/implicitSurfaceSceneIndex.cpp:86-110,1695-1704`].
   So when a cube's `size` changes, only the `cube` locator is dirtied, never `points`, unless a
   dependency-forwarding scene index runs downstream. In-tree, only Storm adds one, through its
   plugin [v26.03 `imaging/hdSt/dependencyForwardingSceneIndexPlugin.cpp:20-41`].
3. **`HdNoticeBatchingSceneIndex::Flush()` does nothing here.** Batching is off by default
   (`_batchingEnabled(false)`) [v26.03 `imaging/hd/noticeBatchingSceneIndex.cpp:18,40,123-131`],
   and the bridge never enables it, so the `Flush()` call [bridge 68] has no effect.
4. **`Snapshot(None)` reads default values.** It calls `SetTime(UsdTimeCode::Default())`, so every
   `UsdAttributeQuery::Get` reads the *default* value, not a time sample [v26.03
   `usdImaging/usdImaging/dataSourceAttribute.h:48-53`]. Every
   `GetContributingSampleTimesForInterval` then returns false
   [`dataSourceAttribute.h:80-84`; `dataSourcePrim.cpp:426-430`]. The stage scene index's initial
   time is numeric 0.0, not Default [v26.03 `usdImaging/usdImaging/stageSceneIndex.h:149` +
   `usd/usd/timeCode.h:75`].
5. **The observer misses the initial population.** The bridge attaches its observer after
   `UsdImagingCreateSceneIndices` has already called `SetStage` (by default the stage is set after
   the chain is built [v26.03 `usdImaging/usdImaging/sceneIndices.cpp:40-48,304-308`]), and observers
   receive no notices for prims that already exist [v26.03 `imaging/hd/sceneIndex.h:66-71`]. The
   bridge's full traversal makes up for this.
6. **Tf errors raised during a bridge call reach neither Python nor the caller.** The module uses
   raw `PXR_BOOST_PYTHON_MODULE`, not `TF_WRAP_MODULE`. Only the Tf module processor wraps calls in
   a `TfErrorMark` and turns errors into Python exceptions [v26.03 `base/tf/pyModule.cpp:142-181`].
   See §8.
7. Points are read through `HdPrimvarSchema::GetPrimvarValue()`. This flattens indexed primvars
   today, but the header warns the behavior "might be conformed to simply return the primvarValue
   data source". Use `GetFlattenedPrimvarValue()` [v26.03 `imaging/hd/primvarSchema.h:79-110`].

---

## 1. Core model

### Scene index and prim

- `HdSceneIndexPrim` is `{TfToken primType; HdContainerDataSourceHandle dataSource;}`. A prim
  exists **if and only if `dataSource` is non-null**, even when the type or container is empty
  [v26.03 `imaging/hd/sceneIndex.h:24-34,86-98`]. In v26.03, `operator bool` is implicit. In dev it
  is `explicit` [dev `imaging/hd/sceneIndex.h` diff], so code that must compile against both should
  write `prim.IsDefined()` or `bool(prim.dataSource)`.
- `GetPrim(path)` and `GetChildPrimPaths(path)` are pure virtual and "expected to be threadsafe".
  Traversal from `/` must give exactly the existing prims, and must agree with the flattened stream
  of PrimsAdded/PrimsRemoved notices [v26.03 `imaging/hd/sceneIndex.h:86-109`]. The guide says the
  same, and adds that unreachable prims return an empty type and a null data source [guide 135-140].
- Helpers: `GetDataSource(path, locator)` [v26.03 `imaging/hd/sceneIndex.h:111-120`],
  `HdSceneIndexPrimView` for depth-first iteration with `SkipDescendants` [v26.03
  `imaging/hd/sceneIndexPrimView.h:21-40`], and `SystemMessage` sent to all upstream indices.
  dev rewrote `SystemMessage` as a de-duplicated graph walk that also enters encapsulated scenes
  [dev `imaging/hd/sceneIndex.cpp` diff].
- `HdSceneIndexNameRegistry` lets you register a scene index by name for debugging tools [v26.03
  `imaging/hd/sceneIndex.h` (end of file)].

### Data sources ([v26.03 `imaging/hd/dataSource.h`])

| Type | API | Notes |
|---|---|---|
| `HdDataSourceBase` | none | Handles are `std::shared_ptr`. `Cast` is `dynamic_pointer_cast` (`:42-44`). |
| `HdContainerDataSource` | `GetNames()`, `Get(name)` | Both "expected to be threadsafe". The implementation does any cache invalidation (`:91-119`). The static `Get(container, locator)` returns null on a missing element or a non-container midway (`dataSource.cpp:20-52`). |
| `HdVectorDataSource` | `GetNumElements()`, `GetElement(i)` | Threadsafe by contract (`:123-143`). |
| `HdSampledDataSource` | `GetValue(Time shutterOffset)`, `GetContributingSampleTimesForInterval` | `Time` is `float` and relative to the current frame. The held type should be the same at every offset (`:147-183`). |
| `HdTypedSampledDataSource<T>` | `GetTypedValue(Time)` | (`:187-201`) |
| `HdBlockDataSource` | none | Equivalent to a null child. It is used for shadowing in overlays (`:204-217`). |

- **Retained** sources (`HdRetainedContainerDataSource`, `HdRetainedSampledDataSource`,
  `HdRetainedTypedSampledDataSource<T>`, `HdRetainedSmallVectorDataSource`) hold values. Their
  `GetContributingSampleTimesForInterval` always returns **false** [v26.03
  `imaging/hd/retainedDataSource.h:122-127,158-163`].
  `HdRetainedTypedMultisampledDataSource` holds real samples (`:198-254`).
- **Overlay**: `HdOverlayContainerDataSource` lazily composes containers, and earlier ones are
  stronger. `OverlayedContainerDataSources(a, b)` skips the wrapper when one side is null [v26.03
  `imaging/hd/overlayContainerDataSource.h:14-51`].
- **Lazy**: `HdLazyContainerDataSource` forwards to a container that a thunk computes [v26.03
  `imaging/hd/lazyContainerDataSource.h:14-19`].
- **Editor**: `HdContainerDataSourceEditor` composes overrides at locators. `Finish()` returns a
  new handle each time, so a scene index that uses it must send dirties for the chain of
  containers (`__containerDataSource` sentinels) [v26.03
  `imaging/hd/containerDataSourceEditor.h:16-55`; `imaging/hd/dataSourceLocator.h:25-49`].
- **Invalidatable**: `HdInvalidatableContainerDataSource::Invalidate(locators)` is what the
  flattening index uses for partial invalidation [v26.03
  `imaging/hd/invalidatableContainerDataSource.h:17-22`].
- dev additions, not in v26.03: `HdVisitSampledDataSourceType` and `HdCopySampledDataSourceType`
  for type dispatch, `std::allocate_shared` in `New`, and a protected `HdBlockDataSource` ctor
  [dev `imaging/hd/dataSource.h` diff]. Do not use them if the code must build against 26.03.

### Locators ([v26.03 `imaging/hd/dataSourceLocator.h`])

- A locator is a short token path, such as `primvars/points/primvarValue` (`:52-57`).
- `HdDataSourceLocatorSet` is **closed under descendancy**: containing `x` means containing every
  `x/...`. A set holding the empty locator is the universal set (`:236-249`). `Intersects(loc)` is
  true when a generator is a prefix of `loc` or the other way round. `Contains(loc)` is true when a
  prefix of `loc` is a generator. `Intersection(loc)` gives the members under `loc` (`:316-368`).
- `__containerDataSource` (`HdDataSourceLocatorSentinelTokens->container`) means "refetch this
  container handle" even if its contents did not change (`:23-49`). The flattening index honors it
  at the prim level [v26.03 `imaging/hd/flatteningSceneIndex.cpp:525-537`].

### Schemas

- `HdSchema` is a typed view over a container. Missing fields return null, and the caller supplies
  the defaults [v26.03 `imaging/hd/schema.h:19-25`]. `_GetTypedDataSource<T>(name)` returns null on
  a **type mismatch**, through `T::Cast` (`:47-53`). A wrong-typed field therefore looks like an
  absent one.
- Generated accessors in v26.03:
  - `HdXformSchema::GetFromParent(prim.dataSource).GetMatrix()` / `GetResetXformStack()`
    [v26.03 `imaging/hd/xformSchema.h:63-95`].
  - `HdMeshSchema::GetTopology()` → `HdMeshTopologySchema` (faceVertexCounts/Indices/holeIndices/
    orientation), `GetSubdivisionScheme`, `GetSubdivisionTags`, `GetDoubleSided`
    [v26.03 `imaging/hd/meshSchema.h:79-130`].
  - `HdPrimvarsSchema::GetPrimvarNames()` / `GetPrimvar(name)` → `HdPrimvarSchema` with
    `GetPrimvarValue` (flattens indexed), `GetIndexedPrimvarValue` + `GetIndices`,
    `GetFlattenedPrimvarValue`, `GetInterpolation`, `GetRole`, `GetColorSpace`, `GetElementSize`
    [v26.03 `imaging/hd/primvarsSchema.h:77-118`; `primvarSchema.h:79-132`; `primvarSchema.cpp:133-148`].
  - `HdMaterialBindingsSchema::GetMaterialBinding()` / `GetMaterialBinding(purpose)` →
    `HdMaterialBindingSchema::GetPath()` [v26.03 `imaging/hd/materialBindingsSchema.h:72-75`;
    `materialBindingSchema.h:64`].
  - `HdInstancerTopologySchema::GetPrototypes()`, `GetInstanceIndices()` (vector of int arrays),
    `GetMask()`, `GetInstanceLocations()`, `ComputeInstanceIndicesForProto(path)` [v26.03
    `imaging/hd/instancerTopologySchema.h:115-147`].
  - `HdInstancedBySchema::GetPaths()` / `GetPrototypeRoots()` [v26.03
    `imaging/hd/instancedBySchema.h:94-127`].
  - Every schema has `GetDefaultLocator()` for matching dirty locators.
- Visibility semantics: Hydra visibility is tri-state, where an absent value means inherited.
  UsdImaging maps `invisible` to a retained `false` and `inherited` to null. Visibility therefore
  cannot vary across a shutter window [v26.03 `usdImaging/usdImaging/dataSourcePrim.cpp:57-90`].
- Schema field docs: [docs https://openusd.org/release/api/_page__hydra__prim__schemas.html]
  (xform/visibility/purpose "produced during flattening", primvarValue vs indexedPrimvarValue,
  instancerTopology prototypes/instanceIndices/mask).

---

## 2. Filtering scene indices, laziness and caching

### Base classes

- `HdFilteringSceneIndexBase` exposes `GetInputScenes()`. `HdEncapsulatingSceneIndexBase` is a
  mix-in for graph viewers [v26.03 `imaging/hd/filteringSceneIndex.h:28-103`].
- `HdSingleInputFilteringSceneIndexBase` observes its input through an inner `_Observer`.
  Subclasses implement `_PrimsAdded/_PrimsRemoved/_PrimsDirtied`, and the base turns renames into
  removed+added [v26.03 `imaging/hd/filteringSceneIndex.h:116-190`; `filteringSceneIndex.cpp:63-74`].
  `_GetInputSceneIndex()` is never null; a fallback is used [`filteringSceneIndex.h:150-156`].
- Several filters skip work when nobody observes them, for example
  `if (!_IsObserved()) return;` [v26.03 `imaging/hdsi/implicitSurfaceSceneIndex.cpp:1699-1701`].

### Merging, prefixing, encapsulating, caching

- `HdMergingSceneIndex` is the only multi-input index. It overlays the data sources of prims that
  appear in several inputs, and earlier inputs are stronger. `activeInputSceneRoot` is an
  optimization [v26.03 `imaging/hd/mergingSceneIndex.h:22-68`].
- `HdPrefixingSceneIndex` re-roots an input under a prefix [v26.03
  `imaging/hd/prefixingSceneIndex.h:18-29`].
- `HdMakeEncapsulatingSceneIndex` is only a forwarding wrapper for debuggers, used when
  `HD_USE_ENCAPSULATING_SCENE_INDICES` is set (default false) [v26.03
  `imaging/hd/sceneIndexUtil.h:17-37`; `sceneIndexUtil.cpp:19-21`].
- `HdCachingSceneIndex` caches prim data sources and child paths in the same style as the
  flattening index [v26.03 `imaging/hd/cachingSceneIndex.h:23-80`]. The render index adds it at the
  terminal only when an env setting enables it [v26.03 `imaging/hd/renderIndex.cpp:236-238`].

### Laziness and caching in the chain this project uses

- **`UsdImagingStageSceneIndex` caches nothing.** Each `GetPrim` builds a fresh prim container
  through the adapters [v26.03 `usdImaging/usdImaging/stageSceneIndex.cpp:243-289`], and each child
  `Get` builds new data sources. For example, `UsdImagingDataSourceXform::Get(matrix)` returns a new
  `UsdImagingDataSourceXformMatrix` [v26.03 `usdImaging/usdImaging/dataSourcePrim.cpp:483-490`].
  Values are read from USD at the moment of `GetValue`, using the *live* stage-globals time [v26.03
  `dataSourceAttribute.h:41-66`; `dataSourcePrim.cpp:405-415`]. **A data source handle is a live
  view, not a snapshot.** [inferred from the cited code] An immutable snapshot needs values copied
  out (VtValue/VtArray, which are cheap COW copies), not handles.
- **`HdFlatteningSceneIndex` caches.** It keeps a `_PrimLevelWrappingDataSource` per queried
  prim in a `SdfPathTable _prims`. New entries first go to a tbb `_recentPrims` hash map, which is
  merged in on the next notice [v26.03 `imaging/hd/flatteningSceneIndex.cpp:334-383,572-581`].
  Each wrapper caches one flattened container per provider name through an atomic CAS cache, so
  concurrent queries get the same instance (`:22-89,243-279`). It also caches the input prim
  container (`:281-296`).
  - Invalidation: when a dirtied locator *contains* `xform` (or another flattened name), that
    cached container is dropped. A partial locator is passed to `Invalidate()` when the container
    supports it (`:153-185,466-538`).
  - Descendants: `_DirtyHierarchy` walks the cached subtree. It invalidates descendants and
    **emits extra DirtiedPrimEntries only for descendants that had cached flattened data**. It
    skips any subtree whose root had nothing cached (`:583-618`).
  - PrimsAdded drops cached wrappers for re-added paths and dirties cached descendants
    (`:392-436`).
  - PrimsRemoved erases subtrees, and a removal of `/` clears everything (`:438-464`).
- **Flattened providers** (`ComputeDirtyLocatorsForDescendants`):
  - xform → universal set; it composes `local * parent` and marks `resetXformStack=true`
    [v26.03 `imaging/hd/flattenedXformDataSourceProvider.cpp:71-142`].
  - visibility → universal. The local value wins if present, then the parent's, then `true`. The
    in-code comment says this is "not according to USD spec" [v26.03
    `imaging/hd/flattenedVisibilityDataSourceProvider.cpp:15-47`].
  - purpose → universal. It inherits only if the parent's `inheritable` is true, then falls back
    to `fallback` [v26.03 `imaging/hd/flattenedPurposeDataSourceProvider.cpp:15-51`].
  - primvars → inherits *constant*-interpolation primvars from ancestors and supports partial
    invalidation [v26.03 `imaging/hd/flattenedPrimvarsDataSourceProvider.cpp:22-301`].
  - coordSysBinding, USD `model`: overlay of local over parent, with no descendant expansion
    [v26.03 `imaging/hd/flattenedOverlayDataSourceProvider.cpp:13-27`].
  - UsdImaging adds material bindings (`usdMaterialBindings`) and geomModel [v26.03
    `usdImaging/usdImaging/flattenedDataSourceProviders.cpp:25-41`].
  - **Material bindings are not flattened by the Hd providers.** `HdFlattenedDataSourceProviders()`
    has no `materialBindings` entry [v26.03 `imaging/hd/flattenedDataSourceProviders.cpp:30-41`].
    In the UsdImaging chain, inherited bindings come from flattening `usdMaterialBindings` and then
    `UsdImagingMaterialBindingsResolvingSceneIndex`. That index "does not factor in collection
    bindings" [v26.03 `usdImaging/usdImaging/materialBindingsResolvingSceneIndex.h:17-21`].
- `HdDependencyForwardingSceneIndex` reads each prim's `__dependencies` (`HdDependenciesSchema`:
  dependedOnPrimPath, dependedOnDataSourceLocator, affectedDataSourceLocator). It re-emits dirties
  on the affected prims and locators, and keeps reverse maps in tbb containers [v26.03
  `imaging/hd/dependencyForwardingSceneIndex.h`; `dependencySchema.h`]. In-tree, `__dependencies`
  are declared by `hdsi` implicit surface, ext computations, light linking, coordSys, material
  override and primvar transfer, velocity motion, nurbs approximation, render settings, and
  UsdImaging render-settings flattening [grep over v26.03 `.cpp`]. The only in-tree instantiation
  is a renderer plugin (Storm) [v26.03 `imaging/hdSt/dependencyForwardingSceneIndexPlugin.cpp:46`].
  dev changed this file substantially (208-line diff); I did not review the change.
- `HdNoticeBatchingSceneIndex` is pass-through until `SetBatchingEnabled(true)`. It then queues
  contiguous runs by notice type with **no coalescing**, and `Flush()` replays them in order [v26.03
  `imaging/hd/noticeBatchingSceneIndex.cpp:35-58,121-153`]. Renames are not batched; the base class
  converts them first.

### What `UsdImagingCreateSceneIndices` builds (v26.03)

In order [v26.03 `usdImaging/usdImaging/sceneIndices.cpp:185-311`]:

1. `UsdImagingStageSceneIndex`
2. optional overrides callback
3. optional unloaded-draw-mode index
4. `UsdImagingExtentResolvingSceneIndex`
5. `UsdImagingPiPrototypePropagatingSceneIndex`
6. `UsdImagingNiPrototypePropagatingSceneIndex`, which internally adds flattening and the draw-mode
   callback at each instancing level
7. `HdNoticeBatchingSceneIndex` (`postInstancingNoticeBatchingSceneIndex`)
8. `UsdImaging_InstanceProxyPathTranslationSceneIndex`
9. `UsdImagingMaterialBindingsResolvingSceneIndex`
10. **all `UsdImagingSceneIndexPlugin`s**
11. `UsdImagingSelectionSceneIndex`
12. `UsdImagingRenderSettingsFlatteningSceneIndex`
13. optional encapsulation

After building the chain it calls `SetStage`.

**Not included:** `HdDependencyForwardingSceneIndex`, Hdsi material binding resolution (Storm adds
`HdSt_MaterialBindingResolvingSceneIndexPlugin` [v26.03 `imaging/hdSt/plugInfo.json:18-23`]),
implicit-surface conversion, and any caching index.

dev deprecates `UsdImagingCreateSceneIndices` in favor of an encapsulating `UsdImagingSceneIndex`
with insertion callbacks [dev `usdImaging/usdImaging/sceneIndices.h` diff;
`usdImaging/usdImaging/sceneIndex.h:32-75`].

**Instancing output layout.** Native instances are aggregated under generated instancer prims such
as `/…/UsdNiPropagatedPrototypes/<bindingsHash>/__Prototype_1/UsdNiInstancer` with
`UsdNiPrototype` below them. Instance prims become typeless with an `instance` data source, and
prototype content is flattened relative to the prototype root [v26.03
`usdImaging/usdImaging/niPrototypePropagatingSceneIndex.h:80-140`;
`niInstanceAggregationSceneIndex.cpp:38,894-903`]. **Terminal paths are therefore not USD paths for
instanced content.** `primOrigin/scenePath` holds the USD origin [v26.03
`usdImaging/usdImaging/dataSourcePrim.cpp:506,543`].

---

## 3. Observers and change tracking

### Notice semantics

[v26.03 `imaging/hd/sceneIndexObserver.h:38-172`; `imaging/hd/sceneIndex.h:173-214`]

- **PrimsAdded(path, type)**: may name a prim that already exists. That means **resync /
  type change**: refetch everything.
- **PrimsRemoved(path)**: hierarchical. The whole subtree is gone.
- **PrimsDirtied(path, locatorSet)**: **not hierarchical on paths** (children are not implied) but
  **hierarchical on locators** (`primvars` covers `primvars/color`).
- **PrimsRenamed(old, new)**: subtree rename. `ConvertPrimsRenamedToRemovedAndAdded` is provided,
  and single-input filters convert renames by default [v26.03 `imaging/hd/filteringSceneIndex.cpp:63-74`].
  `UsdImagingStageSceneIndex` never sends renames. Only a few indices do (render index adapter,
  switching, debugging, hdx task controller) [grep v26.03 `_SendPrimsRenamed`].
- The guide says on dirty: "Any caches containing a datasource handle for that attribute or any
  child attributes need to be cleared and re-fetched." [guide 126-132]

### Delivery mechanics

[v26.03 `imaging/hd/sceneIndex.cpp:17-173`]

- Delivery is synchronous, on the calling thread, to observers in registration order. Empty entry
  lists are not sent.
- `RemoveObserver` during delivery nulls the slot and compacts afterwards.
- Adding the same observer twice raises `TF_CODING_ERROR("Observer is already registered")`
  (`:45-55`).
- Observers are held as `TfWeakPtr`. An observer that dies without being removed is skipped.
- Notices are **not threadsafe**: "some observers expect it to be called from a single thread"
  [v26.03 `imaging/hd/sceneIndex.h:184,193,203,212`].

### Ordering guarantees

- Each `_Send*` call is atomic for its observers. No API orders notices *across* calls, but
  concrete producers do:
  - `UsdImagingStageSceneIndex::ApplyPendingUpdates` sends resync removals, then additions
    (`_ApplyPendingResyncs`), then one dirtied batch [v26.03
    `usdImaging/usdImaging/stageSceneIndex.cpp:631-748,750-791`].
  - The flattening index forwards Added and then sends a Dirtied batch for cached descendants
    (`flatteningSceneIndex.cpp:430-435`). For Dirtied, it appends descendant entries after the
    originals in one batch (`:561-569`).
- `HdsiPrimTypeNoticeBatchingSceneIndex` gives **consolidated** batches. It merges dirties per path,
  folds dirty into add, drops entries under later removals, and on `Flush` emits all removals and
  then add/dirty grouped by a type-priority functor. It is empty until the first `Flush` [v26.03
  `imaging/hdsi/primTypeNoticeBatchingSceneIndex.h:28-46`; `.cpp:239-251`]. The guide recommends it
  for Hydra-2-native consumers [guide 600-605]. I found no production user in v26.03.

### Where the stage scene index's changes come from

[v26.03 `usdImaging/usdImaging/stageSceneIndex.cpp`]

- It listens for `UsdNotice::ObjectsChanged` through `TfNotice::Register` (`:396-398`). The handler
  only **queues** the change:
  - resynced prim paths → `_usdPrimsToResync`
  - resynced property paths → `_usdPropertiesToResync`
  - info-only property changes → `_usdPropertiesToUpdate`
  - prim info-only changes resync the prim only if a *plugin* field changed
  - asset-path re-resolution invalidates recorded asset-path dependents
  (`:507-593`)

  Nothing is sent until `ApplyPendingUpdates()` (`:750-791`; header `stageSceneIndex.h:85-91`).
- Property changes become locators through each adapter's `InvalidateImagingSubprim`. A
  `stageSceneIndexRepopulate` result is promoted to a resync (`:793-875`). Tests confirm granular
  locators: a change yields material, `mesh/topology` and `primvars/points` dirties separately
  [v26.03 `usdImaging/usdImaging/testenv/testUsdImagingStageSceneIndex.cpp:351-386`].
- **A resync is a subtree remove plus re-add.** Removals are filtered to paths that are not
  re-added, so a surviving prim gets only an *Added* entry and must be treated as a full refresh
  (`:696-747`).
- Population follows the predicate `UsdPrimIsActive && !UsdPrimIsAbstract`, plus `UsdPrimIsLoaded`
  unless `includeUnloadedPrims`. **It does not require `IsDefined`**, so `over`s show up
  (PI-prototype overs are later made typeless). Instance proxies are never returned. USD prototypes
  are added under `/` (`:263-265,343-347,480-503`).

### Time changes

- `SetTime(t)` dirties **every (path, locatorSet) ever flagged time-varying**. It does nothing if
  `t` equals the current time and `forceDirtyingTimeDeps` is false [v26.03
  `usdImaging/usdImaging/stageSceneIndex.cpp:354-369,902-914`].
- Paths are flagged **only when a data source is constructed**, that is, when someone pulled it
  (`FlagAsTimeVarying` in the data source ctors) [v26.03 `dataSourceAttribute.h:229-243`;
  `dataSourcePrim.cpp:35-45,458-469`; `dataSourcePrimvars.cpp:290-326`;
  `dataSourceMesh.cpp:92-111`]. The test states: "If we haven't pulled on any data yet, nothing
  should be variable" [v26.03 `usdImaging/usdImaging/testenv/testUsdImagingStageSceneIndex.cpp:229-231`].
- The flagged map is **never pruned** except by `SetStage` (`_StageGlobals::Clear`) [v26.03
  `stageSceneIndex.cpp:879-886,963-972`; only `insert` and `clear` touch `_timeVaryingLocators`].
  The same holds in dev [dev `stageSceneIndex.cpp:1019-1100`]. **Dirties can therefore arrive for
  paths that no longer exist.** Consumers must ignore unknown paths, as
  `HdsiPrimManagingSceneIndexObserver` does [v26.03
  `imaging/hdsi/primManagingSceneIndexObserver.cpp:133-137`].
- A dirty on time change **does not mean the value changed**. Held frames and stepped curves are
  dirtied too. [inferred from `SetTime` iterating the whole map]

### What a dirty notice does and does not promise

- It promises that data at those locators *may* have changed, so cached handles and values there
  must be refetched [guide 126-132].
- It does **not** promise that:
  - (a) the value actually changed,
  - (b) descendants are dirtied (paths are not hierarchical); the flattening index adds descendant
    dirties itself, but **only for descendants whose flattened data was cached**
    [v26.03 `flatteningSceneIndex.cpp:597-614`],
  - (c) the path exists,
  - (d) dependents are dirtied, unless `HdDependencyForwardingSceneIndex` is in the chain (§2).

### Recommended pattern for a non-render consumer

[inferred, built on the cited mechanics]

1. Own the chain:

   ```
   UsdImagingCreateSceneIndices → (optional HdsiImplicitSurfaceSceneIndex)
     → HdDependencyForwardingSceneIndex → terminal
   ```

   Do not add a second flattening index.
2. Attach a recording observer to the terminal **before** population. Either build with the
   overrides callback, or call `stageSceneIndex->SetStage` yourself after attaching. Alternatively,
   attach late and do one full traversal as the baseline, as the bridge does.
3. A capture pass:
   - (a) `ApplyPendingUpdates()`
   - (b) `SetTime(t)`
   - (c) take the recorded Added/Removed/Dirtied set, coalesced per path: union the locators,
     fold Added over Dirtied, and drop entries under a Removed
   - (d) re-pull values **only** for affected prims and locators, and copy them out
   - (e) after any Added, re-pull the whole prim and the existence of its subtree

   `HdsiPrimTypeNoticeBatchingSceneIndex` can do the coalescing in step (c).
4. For incremental correctness, the consumer must pull everything it displays at least once. That
   is what registers time-varying paths and fills the flattening cache that drives descendant
   dirties. A consumer that pulls nothing gets no notices.
5. `HdsiPrimManagingSceneIndexObserver` is a ready-made "prim per path" manager. A factory creates
   `PrimBase` objects on Added, including prims that exist at construction. `Dirty` forwards to the
   prim, Removed erases by prefix, and Renamed is converted. It is single-threaded today [v26.03
   `imaging/hdsi/primManagingSceneIndexObserver.h:27-160`; `.cpp:45-170`]. It is a good shape for a
   C++ "display plan" layer.

---

## 4. Time and sampling

### Contract

[v26.03 `imaging/hd/dataSource.h:158-182`; guide 159-174]

- `GetValue(shutterOffset)`: the offset is *relative to the frame the producing scene index is
  set to*. The caller does not track the frame.
- `GetContributingSampleTimesForInterval(start, end, out)`:
  - **true** means "call `GetValue` at each returned offset to reconstruct the signal". Samples
    may lie outside `[start, end]` (bracketing), and callers should interpolate.
  - **false** means "uniform over the window; call `GetValue(0)`".
- The guide adds that consumers should call `GetValue` only at returned offsets or at 0. Other
  offsets: "behavior might be undefined" [guide 172-174; docs Getting Started URL].
- Merge helper: `HdGetMergedContributingSampleTimesForInterval` unions the inputs that return true
  and then filters through `HdGetContributingSampleTimesForInterval`. That filter keeps at most one
  sample before `start`, all samples in range, and stops at the first sample ≥ `end`. It returns
  **`numOutSamples > 1`** [v26.03 `imaging/hd/dataSource.cpp:69-113`;
  `imaging/hd/timeSampleArray.cpp:116-170`]. If no input returns true, it returns false.

### UsdImaging implementations

- **Attributes.** `UsdImagingDataSourceAttribute<T>` [v26.03 `dataSourceAttribute.h:68-126`]:
  - Returns false if the time is not numeric (Default) or
    `!UsdAttributeQuery::ValueMightBeTimeVarying()`.
  - Otherwise it takes `GetTimeSamplesInInterval(t+start, t+end)`, prepends or appends the
    bracketing samples (falling back to the interval edge), converts to float offsets, and
    returns `size > 1`.
  - Consequence: for a zero-width query `[0,0]` at a frame that lands **exactly on an authored
    sample**, the result is `[0]` and false. At a frame between samples it is true. [inferred by
    tracing `:86-125`]
- **Xform.** `UsdImagingDataSourceXformMatrix` [v26.03 `dataSourcePrim.cpp:417-450`]:
  - Returns false if `!TransformMightBeTimeVarying()` or the time is not numeric.
  - Otherwise it gets the samples in the interval, pads with the interval edges, and **always
    returns true**, even with a single sample.
- Both write through `outSampleTimes` **without a null check**
  [`dataSourceAttribute.h:120`; `dataSourcePrim.cpp:445`]. `HdGetMergedContributingSampleTimesForInterval`
  forwards `nullptr` to its inputs when its own `out` is null [v26.03 `dataSource.cpp:89-90`].
  **Passing `nullptr` ("just tell me if it varies") into any composed source over UsdImaging data
  will crash.** Always pass a vector. [inferred from the cited lines; not run]
- Time is held in `_StageGlobals::_time`, set by `UsdImagingStageSceneIndex::SetTime`. Every live
  data source reads it on each call [v26.03 `stageSceneIndex.cpp:897-907`;
  `dataSourceAttribute.h:48-51`].

### Flattened xform under an animated parent

`_MatrixCombinerDataSource` [v26.03 `imaging/hd/flattenedXformDataSourceProvider.cpp:16-67`]:

- Its `GetContributingSampleTimesForInterval` merges the **parent (already flattened) and local**
  matrices through `HdGetMergedContributingSampleTimesForInterval` (`:31-40`).
- `GetTypedValue(0)` returns a value **cached at construction** (`_cachedResultAt0`, `:27,50-52`).
  Other offsets compute `local(t) * parent(t)` live (`:59-60`).

Static mesh under an animated parent:

- **The child has no xformOps.** UsdImaging returns *no* xform container for prims without
  xformOps or resetXformStack [v26.03 `dataSourcePrim.cpp:724-736`]. The provider then returns the
  **parent's flattened container itself** (`flattenedXformDataSourceProvider.cpp:112-116`). Its
  matrix is the parent's `UsdImagingDataSourceXformMatrix` or combiner, so it **reports
  time-varying** exactly as the parent does.
- **The child has static xformOps.** The combiner merges and reports true whenever the parent
  reports varying samples in the queried window. It reports false for a zero-width window: the
  parent yields `[0]`, and the merge filter returns `count > 1` → **false** (traced through
  `dataSource.cpp:104-112` and `timeSampleArray.cpp:123-169`). So **the same animated parent can
  read as "varying" on its own and "not varying" through a child's combiner at a zero-width
  query.** [inferred by tracing; not run]
- **Recommendation:** to detect animation, query a real interval, for example the stage frame
  range relative to the current time, or ±1 frame. Never use `[0,0]`.
- Dirties: when time changes, the stage index dirties the parent's `xform` (flagged when its
  UsdImaging xform data source was built), and the flattening index invalidates and dirties every
  cached descendant, `ComputeDirtyLocatorsForDescendants` being universal [v26.03
  `flatteningSceneIndex.cpp:480-523,583-618`]. **A static child therefore gets an `xform` dirty on
  each `SetTime`**, provided its flattened xform was pulled before.
- The combiner's cached-at-0 value means **a handle held across `SetTime` returns a stale matrix
  at offset 0**, while other offsets are live. Always re-pull after a dirty. [inferred from
  `:27,50-52`]

### Other data: does anything report "time varying"?

- **Topology.** `faceVertexCounts`, `faceVertexIndices` and `holeIndices` are
  `UsdImagingDataSourceAttribute`s with flag locators [v26.03 `dataSourceMesh.cpp:92-111`], so they
  report sample times and get dirtied on time change. `orientation` is not flagged (`:112-114`).
- **Primvars**, including `points`: `primvarValue`, or `indexedPrimvarValue` and `indices`, are
  flagged when time-varying [v26.03 `dataSourcePrimvars.cpp:290-326`]. Values come from
  `UsdImagingDataSourceAttributeNew` (`:367-375`), so they report sample times.
- **Visibility.** It is flagged time-varying, so `SetTime` dirties it [v26.03
  `dataSourcePrim.cpp:35-45`]. But the value is a retained `bool` that **always returns false**
  from `GetContributingSampleTimesForInterval` [`dataSourcePrim.cpp:82-89`;
  `retainedDataSource.h:158-163`]. Animated visibility can therefore only be discovered by dirties
  or by asking USD directly. The flattened visibility of a descendant is the parent's container, so
  it behaves the same way.
- **Extent** is flagged and forwards sample times [v26.03 `dataSourcePrim.cpp:219-237,306-308`].
- **Implicit-surface generated points**: I did not trace their sample-time behavior.

### Capturing animation over a frame range

Hydra's model is "current frame plus shutter window". Two ways to capture frames [inferred]:

- **(a)** `SetTime(frame)` per frame and re-pull the dirtied locators. This is supported and
  cache-correct.
- **(b)** Use large `shutterOffset`s from one time. UsdImaging data sources do add any offset, but
  the guide calls arbitrary offsets potentially undefined, and the combiner's cache applies only at
  0.

Prefer (a).

Precision: sample offsets are converted from double to float [v26.03 `dataSourceAttribute.h:118-123`].
This is fine relative to the current frame, but expect float rounding for very large frame numbers
and sub-frame samples. [inferred]

---

## 5. Threading

### Contract

- Threadsafe by contract: `GetPrim`, `GetChildPrimPaths` [v26.03 `imaging/hd/sceneIndex.h:97,108`];
  container `GetNames`/`Get`, vector access and sampled `GetValue` [v26.03
  `imaging/hd/dataSource.h:104-109,136-142,163`].
- Not threadsafe: `AddObserver`, `RemoveObserver` and every `_Send*` [v26.03
  `imaging/hd/sceneIndex.h:71,79,184,193,203,212`]; observer callbacks are "not expected to be
  threadsafe" [v26.03 `sceneIndexObserver.h:123,132,143,151`].
- The guide makes no threading guarantees beyond saying `HdsiPrimManagingSceneIndexObserver`'s
  threading "will be customizable by future input arguments" [guide 606-609; docs URL].

### Implementations built for concurrent reads

- Flattening: `_recentPrims` is a tbb `concurrent_hash_map`, so a racing insert returns the winner;
  caches use atomic CAS [v26.03 `flatteningSceneIndex.cpp:45-66,349-381`].
- Stage globals use a tbb `concurrent_hash_map` for time-varying flags and a mutex for asset-path
  dependents [v26.03 `stageSceneIndex.h:141-147`; `.cpp:879-895`].
- The adapter manager uses tbb concurrent maps "filled during concurrent GetPrim calls" [v26.03
  `usdImaging/usdImaging/adapterManager.h:82-90`].
- Hydra itself reads the terminal index in parallel: `HdRenderIndex::SyncAll` runs rprim sync with
  `WorkParallelForN` / `WorkDispatcher` through the scene-index adapter delegate [v26.03
  `imaging/hd/renderIndex.cpp:1168,1465,1787-1840`]. Parallel reads are exercised in production.
  The flattening index's own notice handlers also use `WorkParallelForN` [v26.03
  `flatteningSceneIndex.cpp:406-415,553-558`].

### Constraints a capture must respect

[inferred from the code cited]

1. **Reads must not overlap notice processing or mutation.** The flattening index's notice handlers
   call `_ConsolidateRecentPrims()`, which mutates the non-concurrent `SdfPathTable _prims` that
   `GetPrim` reads without a lock [`flatteningSceneIndex.cpp:340,572-581`]. Run `SetTime`,
   `ApplyPendingUpdates`, `SetStage`, `Flush` and stage edits **only between** parallel read phases.
2. **USD edits must be serialized with the scene index.** `_OnUsdObjectsChanged` runs synchronously
   on the editing thread and appends to plain `std::vector`/`std::map` members with no lock, the
   same members `ApplyPendingUpdates` consumes [`stageSceneIndex.cpp:507-593,750-791`]. Editing the
   stage while reading it also gives torn reads, because data sources read the stage live.
3. Within a read phase, `WorkParallelForEach` over prim paths is fine: `GetPrim` plus schema access
   plus `GetValue`, copying values into per-thread outputs.
4. **Python and the GIL.** A call from Python enters C++ holding the GIL. If a worker task can
   re-enter Python (a Python Ar resolver or file-format plugin, or Python `Tf.Notice` listeners),
   holding the GIL while waiting on workers deadlocks. Release it around parallel capture with
   `TF_PY_ALLOW_THREADS_IN_SCOPE()` [v26.03 `base/tf/pyLock.h:140-181`; USD itself does this, e.g.
   `usd/usd/stage.cpp:923`]. `bpy` must be touched only on Blender's main thread, after the C++
   capture returns.
5. Errors posted on worker threads: `WorkDispatcher` carries `TfErrorTransport`s back to the
   waiting thread [v26.03 `base/work/dispatcher.h:106-110`; `dispatcher.cpp:67-71`]. I did not
   check `WorkParallelForN`'s behavior.

---

## 6. Scene index plugins

### Hd plugin registry

`HdSceneIndexPluginRegistry` is an `HfPluginRegistry` singleton [v26.03
`imaging/hd/sceneIndexPluginRegistry.h:30-276`]:

- `Define<T>()` registers a plugin type, usually in `TF_REGISTRY_FUNCTION(TfType)`.
- `RegisterSceneIndexForRenderer(rendererDisplayName, pluginId | callback, inputArgs, phase, order)`
  registers a plugin for a renderer. An empty renderer name means all renderers.
- `AppendSceneIndicesForRenderer(name, input, renderInstanceId, appName)` loads plugins with a
  `loadWithRenderer` key matching `""` or the given renderer (filtered by `preloadInApps`), then
  appends the registered entries by phase [v26.03 `imaging/hd/sceneIndexPluginRegistry.cpp:147-192,262-278`].
- `AppendSceneIndex(pluginId, …)` appends one plugin by id.
- plugInfo requirements: a type entry with `"bases": ["HdSceneIndexPlugin"]`, optional
  `loadWithRenderer`, `priority` and `displayName`, plus `LibraryPath` and so on [v26.03
  `imaging/hdSt/plugInfo.json:4-23`; `imaging/hdsi/plugInfo.json`]. The C++ side must call
  `RegisterSceneIndexForRenderer` in `TF_REGISTRY_FUNCTION(HdSceneIndexPlugin)` [v26.03
  `imaging/hdSt/dependencyForwardingSceneIndexPlugin.cpp:15-30`]. The header notes that
  `loadWithRenderer` only loads the library; registration is still needed (`:105-111`).
- dev heavily reworked this registry (1649-line `.cpp` diff): `preloadInApps` is renamed
  `loadWithApps`, and `sceneIndexCreateArgs` is overlaid into `inputArgs` [dev
  `imaging/hd/sceneIndexPluginRegistry.h` diff]. Code depending on its details will not port
  cleanly.

### UsdImaging scene index plugins

This is a different registry and is **not optional**. `UsdImagingCreateSceneIndices` always calls
`UsdImagingSceneIndexPlugin::GetAllSceneIndexPlugins()`, which **loads every plugin** declaring a
type derived from `UsdImagingSceneIndexPlugin` in the PlugRegistry [v26.03
`usdImaging/usdImaging/sceneIndexPlugin.cpp:42-82`; `sceneIndices.cpp:64-76,131-183`]. In stock
OpenUSD that is `usdSkelImaging` [v26.03 `usdImaging/usdSkelImaging/plugInfo.json`]. The same plugins
also contribute flattened providers and instance-aggregation names
[`flattenedDataSourceProviders.cpp:55-61`]. Prim adapters are discovered through the PlugRegistry
too [inferred from `UsdImaging_AdapterManager`; not traced line by line].

### Should a consumer without a render delegate use the Hd registry?

[inferred] No. Build the chain by hand. `AppendSceneIndicesForRenderer("")` would instantiate
whatever all-renderer plugins Blender, or anything on its plugin path, has registered, such as
`HdsiDebuggingSceneIndexPlugin`. The result would depend on the environment. Adding
`HdDependencyForwardingSceneIndex`, `HdsiImplicitSurfaceSceneIndex` and similar explicitly keeps the
chain reproducible.

### Implications inside Blender

[inferred]

- The PlugRegistry is process-global and shared with Blender. Which UsdImaging adapters and plugins
  exist depends on the plugInfo Blender ships and registers. The feasibility bridge got typed prims,
  which suggests usdImaging's plugInfo is registered; I did not verify this here.
- An extension adding its own plugin must call `PlugRegistry::RegisterPlugins(path)` before first
  use, from C++ or Python `pxr.Plug`. It cannot unregister, and it must avoid type-name clashes.
  Plugins appearing later do not change chains already built: `GetAllSceneIndexPlugins` runs at
  chain creation, and the flattened providers are a function-static cached on first call
  [v26.03 `usdImaging/usdImaging/flattenedDataSourceProviders.cpp:70-76`;
  `sceneIndices.cpp:237-238,278-279` statics].

---

## 7. Hydra 1 vs Hydra 2

- **Hydra 1.** `HdSceneDelegate` pull API, `HdRenderIndex` holding `HdRprim/HdSprim/HdBprim`,
  `HdChangeTracker` dirty bits, and `SyncAll` in tiered, typed, thread-per-prim order [guide 626-631].
- **Hydra 2.** A scene index graph with observers. The terminal index can be read directly.
- **Emulation in v26.03.**
  - Front end: when no terminal scene index is given and `HD_ENABLE_SCENE_INDEX_EMULATION` (default
    true) is set, `HdRenderIndex` builds this chain: `HdLegacyPrimSceneIndex` (legacy delegate
    insertions become data sources, `HdDataSourceLegacyPrim`) → `HdLegacyGeomSubsetSceneIndex` →
    `HdMergingSceneIndex` → notice batching → renderer plugins → optional `HdCachingSceneIndex`
    [v26.03 `imaging/hd/renderIndex.cpp:58-75,189-242`].
  - Back end: `HdSceneIndexAdapterSceneDelegate` feeds the terminal index into the legacy render
    delegate, and `SetTerminalSceneIndex`/`Update` give delegates a direct hook (`:245-252`;
    `renderDelegate.h:510-541`).
  - `HdDirtyBitsTranslator` maps locators to and from dirty bits.
- Docs: "there is no pure Hydra 2.0 HdRenderer implementation yet" [guide 615; docs URL]. `HdRenderer`
  is a stub, "the Hydra 2.0 replacement of the HdRenderDelegate" [v26.03 `imaging/hd/renderer.h:17-34`].
- **A render delegate or render index is not needed to get processed data.** The UsdImaging chain's
  terminal index already holds the flattened, instancing-resolved, material-binding-resolved data
  [§2 sources]. What a consumer gives up without the render index:
  - renderer plugin filters (dependency forwarding, Hdsi material binding resolution, primvar
    transfer, and so on) unless it adds them itself;
  - ext-computation evaluation: Storm's CPU computations, for example for skinning when skel
    resolution is not done in the scene index, rely on render-side machinery. I did not trace this.
  - Hydra-1-only pieces: `HdRprim::Sync`, change tracker, draw items, tasks, render passes.
- **Implicit surfaces** are not tessellated by UsdImaging. A non-renderer must add
  `HdsiImplicitSurfaceSceneIndex` (toMesh), as the bridge does, and needs dependency forwarding for
  correct updates [§0.2].

---

## 8. Error handling

- **Missing or ill-typed data gives null, not an error.** `HdContainerDataSource::Get(locator)` returns
  null on a missing element or a non-container midway [v26.03 `imaging/hd/dataSource.cpp:20-52`].
  Schema typed getters return null on a wrong type [v26.03 `imaging/hd/schema.h:47-53`]. A missing
  prim is `{TfToken(), nullptr}` [v26.03 `usdImaging/usdImaging/stageSceneIndex.cpp:247-268`].
- **UsdImaging attribute reads never fail visibly.** `GetTypedValue` returns the USD value, then the
  fallback, then **`T{}`** (zero or empty) [v26.03 `dataSourceAttribute.h:41-66`]. A missing value
  and an authored empty array look the same. A consumer that needs "authored or not" must ask USD,
  or check the schema-level null before calling `GetValue`.
- Data source creation for an unsupported attribute type posts `TF_WARN` and returns null.
  A null attribute posts `TF_VERIFY` and returns null [v26.03 `dataSourceAttribute.cpp:241-257`].
- **No fatal errors.** No `TF_AXIOM` or `TF_FATAL_ERROR` was found in the flattening, merging,
  dependency-forwarding, sceneIndex or stageSceneIndex sources [grep v26.03]. Coding errors are
  posted as `TfError` and execution continues. Examples: double `AddObserver` [v26.03
  `imaging/hd/sceneIndex.cpp:48-51`], and a `TF_VERIFY` in flattening's racing insert
  (`flatteningSceneIndex.cpp:378`).
- **No topology validation at the scene-index level.** Mesh topology and primvar arrays pass
  through unchanged from USD. Validation such as `HdMeshUtil` happens in render delegates.
  [inferred: no validation in `dataSourceMesh.cpp`/`dataSourcePrimvars.cpp` read paths] **The
  consumer must validate** counts against indices, index ranges, and primvar lengths against
  interpolation before building Blender meshes.
- **Where errors go.** `TfDiagnosticMgr::PostError` appends to the per-thread error list. With no
  active `TfErrorMark`, it reports the error through delegates or prints it to stderr [v26.03
  `base/tf/diagnosticMgr.cpp:205-264`]. Only modules using the Tf module processor turn errors into
  Python exceptions [v26.03 `base/tf/pyModule.cpp:142-181`]. **Recommendation:** each bridge entry
  point should open a `TfErrorMark`, collect `m.begin()..end()` into the result as structured
  diagnostics, and `Clear()` the mark. [inferred]
- **Crash risks found:**
  - (1) `nullptr` passed as `outSampleTimes` to UsdImaging sampled sources, directly or through
    merge or the combiner [§4].
  - (2) Using `HdDependencyForwardingSceneIndex` incorrectly is not a crash but loses updates.
  - (3) Reading during notice delivery from another thread [§5].

---

## 9. Patterns and testing practice

- **Build the chain by hand and read the terminal directly.** The guide shows filters built on
  `HdSingleInputFilteringSceneIndexBase`, and the greening example warns that conditional overrides
  must dirty the root locator [guide 345-363].
- **Terminal consumers.** Render delegates observe through `SetTerminalSceneIndex` [v26.03
  `imaging/hd/renderDelegate.h:519-528`]. Hydra-2-native consumers should use
  `HdsiPrimTypeNoticeBatchingSceneIndex` and `HdsiPrimManagingSceneIndexObserver` [guide 600-613;
  §3]. `HdsiComputeSceneIndexDiff*` computes remove/add/rename/dirty diffs between two scene
  indices, used by `HdsiSwitchingSceneIndex` [v26.03 `imaging/hdsi/computeSceneIndexDiff.h:20-50`].
- **Unit tests.**
  - `HdRetainedSceneIndex` is a scene index you populate and dirty by hand (`AddPrims`,
    `RemovePrims`, `DirtyPrims`) [v26.03 `imaging/hd/retainedSceneIndex.h:21-66`]. Tests chain the
    filter under test after it and check traversal and notices with a local
    `RecordingSceneIndexObserver` (event vectors and sets) [v26.03
    `imaging/hd/testenv/testHdSceneIndex.cpp:100-250,340-451`].
  - The hdsi tests cover diff, switching, prefix pruning, debugging and pinned curves [v26.03
    `imaging/hdsi/testenv/`].
  - The UsdImaging tests open `.usda`, attach a listener, call `SetStage`/`SetTime`/
    `ApplyPendingUpdates`, and compare `DirtiedPrimEntries` with an expected set of locators
    [v26.03 `usdImaging/usdImaging/testenv/testUsdImagingStageSceneIndex.cpp:209-290,351-386`].
  - `HdDebugPrintDataSource` dumps a data source with names sorted [v26.03 `imaging/hd/dataSource.cpp:115-154`].
  - **These helpers are C++-only.** Blender's `pxr` Python has no Hd, so retained-scene-index tests
    must run in the C++ test layer or through the project's compiled module. [inferred, from the
    project context]
- **Debugging.** `HdsiDebuggingSceneIndex` (env-enabled plugin) checks scene-index invariants
  [v26.03 `imaging/hdsi/plugInfo.json`; `debuggingSceneIndex.cpp:28`]. The Hydra Scene Debugger
  can open named scene indices [docs Scene Debugger page].

---

## 10. Limitations and gotchas

1. **No snapshot semantics.** Data sources are live views over the stage and current time. A
   snapshot must copy values out. A held flattened-xform handle returns a stale value at offset 0
   after a time change [§4].
2. **Change tracking depends on pulls.** Time-varying registration and descendant dirtying happen
   only for data that was pulled (stage flags, flattening cache). If you never pull, you never hear
   about it [§3].
3. **Coarse time dirties.** Every flagged locator is dirtied on every `SetTime`, whether or not the
   value changed. The flag map is never pruned, so dirties arrive for removed paths [§3].
4. **Resync means re-add.** It arrives as Added on existing paths, with removals only for paths that
   disappeared. Treat Added on a known path as a full refresh, including its subtree [§3].
5. **Dependency-declared dirties need `HdDependencyForwardingSceneIndex`.** UsdImaging does not add
   it, and implicit surfaces depend on it [§0, §2].
6. **Inconsistent "is time varying" answers.** Zero-width queries are unreliable (attribute on an
   exact sample → false; combiner over an animated xform → false; UsdImaging xform alone → true).
   Visibility never reports sample times. `Default` time always reports false [§4].
7. **`nullptr` `outSampleTimes` crashes** UsdImaging sources and anything merging them [§4, §8].
8. **Silent fallbacks.** Wrong types read as absent. Missing values read as `T{}`. No topology
   validation [§8].
9. **Threading.** Reads may run in parallel, but never during notice delivery, scene-index
   mutation or stage edits. Observers and notices are single-threaded. Release the GIL for parallel
   work [§5].
10. **Paths differ from USD for instanced content.** `UsdNiPropagatedPrototypes/…/UsdNiInstancer/
    UsdNiPrototype/…`. Prototype content is flattened relative to the prototype. Use `primOrigin`
    and `instancerTopology` and compose instance transforms yourself [§2].
11. **Material bindings.** Collection-based bindings are not resolved by
    `UsdImagingMaterialBindingsResolvingSceneIndex` in v26.03 [§2]. The result is per purpose
    (`HdMaterialBindingsSchema`). Hdsi's further resolution is a Storm plugin.
12. **The flattening index caches every queried prim** for the life of the chain, until removed or
    dirtied. Memory grows with scene size [§2]. Double flattening (the current bridge) doubles this.
13. **Plugin environment leaks into results.** UsdImaging scene index plugins (such as
    usdSkelImaging) and prim adapters load from whatever Blender's PlugRegistry knows, and they
    cannot be opted out of in `UsdImagingCreateSceneIndices` [§6].
14. **Visibility flattening** resolves "local wins, else parent", which the code comments call
    non-spec. UsdImaging only ever emits `false` or absent, which keeps it correct for USD input [§2].
15. **API drift after 26.03 (dev).**
    - `UsdImagingCreateSceneIndices` is deprecated for `UsdImagingSceneIndex`.
    - `HdSceneIndexPrim::operator bool` became explicit.
    - The plugin registry was reworked.
    - UsdImaging no longer returns `primvars`/`purpose` containers when nothing is authored, so
      code must handle null [dev `usdImaging/usdImaging/dataSourcePrim.cpp` diff].
    - `SetTime`'s default argument was split into overloads [dev `stageSceneIndex.h` diff].
    - Write against the 26.03 API and guard all schema accesses for null.
16. **Docs are thin.** The release docs make no threading guarantees and say little about holding
    handles. "No pure Hydra 2.0 HdRenderer yet" means the non-render-delegate consumer path has
    little in-tree precedent beyond tests and HdSt-internal observers [guide 615].
