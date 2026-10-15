# UsdImaging scene-index chain (Hydra 2.0) in OpenUSD v26.03: a consumer's view

Scope: what a C++ core gets from `UsdImagingCreateSceneIndices` without a render delegate, and what it must add or do itself. This is read against the M1b prototype list in `docs/milestones/M01b-evaluation-gate.md`.

Path conventions: `V/` = `pxr/` in an OpenUSD v26.03 checkout, `D/` = `pxr/` in an OpenUSD `dev` checkout at commit `5bc38c9`.

Labels:
- **[src path:line]**: verified in the v26.03 source.
- **[dev path:line]**: verified in the dev clone (HEAD 5bc38c9, 2026-10-07).
- **[docs]**: from the openusd.org release docs.
- **[inferred]**: reasoned from the code, not run. Nothing here was executed except listing Blender's installed plugins.

Runtime fact (checked on this machine): `/Applications/Blender.app/Contents/Resources/lib/usd/` contains plugInfo for `usdImaging`, `usdSkelImaging`, `usdVolImaging`, `usdProcImaging`, `usdRiPxrImaging`, `hd`, `hdsi`, `hdSt`, `hdx`, `hdGp`, and `usdImagingGL`, in one monolithic `libusd_ms.dylib`. That means the UsdSkelImaging scene-index plugin (§7) **is** discovered and appended inside `UsdImagingCreateSceneIndices` in Blender's build.

---

## 0. Headline findings

1. **The chain's output is already flattened.** `UsdImagingNiPrototypePropagatingSceneIndex` puts an `HdFlatteningSceneIndex` with `UsdImagingFlattenedDataSourceProviders()` at every native-instancing recursion level. **[src V/usdImaging/usdImaging/niPrototypePropagatingSceneIndex.cpp:200-209]**
   - Non-instanced prims come out with world xform, resolved visibility, purpose, inherited constant primvars, and flattened USD material bindings.
   - Prims inside propagated prototypes come out flattened relative to the prototype root, which is forced to identity with `resetXformStack=true`. **[src V/usdImaging/usdImaging/niPrototypeSceneIndex.cpp:81-93]**
   - The bridge's extra `HdFlatteningSceneIndex(HdFlattenedDataSourceProviders())` on top is redundant. Flattened xforms carry `resetXformStack=true`, so the extra pass does not double-apply transforms. **[src V/imaging/hd/flattenedXformDataSourceProvider.cpp:86-98,126-133]**
   - The bridge record's claim "inherited state through HdFlatteningSceneIndex (tested)" was really exercising the chain's internal flattening. **[inferred]**
2. **`postInstancingNoticeBatchingSceneIndex->Flush()` does nothing by default.** Batching is off until `SetBatchingEnabled(true)`. **[src V/imaging/hd/noticeBatchingSceneIndex.cpp:18,40,123-128]**
3. **No approximation signal from the implicit-surface filter.**
   - The prim type becomes `mesh` and the original schema (e.g. `sphere`) is replaced by a block data source. **[src V/imaging/hdsi/implicitSurfaceSceneIndex.cpp:264-282,1558-1625]**
   - Tessellation is hard-coded: sphere 10×10, cone/cylinder 10 radial, capsule 10 radial × 4 per cap. **[src …implicitSurfaceSceneIndex.cpp:295,480,708-709,863-865]**
   - Sphere, cone, cylinder and capsule cages are `catmullClark`; cube and plane are `bilinear`. **[src V/imaging/geomUtil/meshGeneratorBase.cpp:89; cuboidMeshGenerator.cpp:37; planeMeshGenerator.cpp:32]**
   - The only trace is a `__dependencies/implicitToMesh` entry. **[src …:89-110]**
4. **Skinning is resolved in-chain, but as ext computations, not as points.**
   - The `points` and `normals` primvars of skinned prims are *blocked*, and an `extComputationPrimvars/points` entry is added instead. **[src V/usdImaging/usdSkelImaging/dataSourceResolvedPointsBasedPrim.cpp:291-304,471-489]**
   - To read deformed points the consumer must append `HdSiExtComputationPrimvarPruningSceneIndex`, which runs the CPU callback when the primvar is pulled. **[src V/imaging/hdsi/extComputationPrimvarPruningSceneIndex.cpp:383-398]**
5. **Native instances that differ in inherited primvars share one instancer.**
   - Constant primvars on instance roots (including inherited ones, because the input is flattened) become `instance`-interpolated primvars on the instancer. They are not pushed into prototype prims. **[src V/usdImaging/usdImaging/niInstanceAggregationSceneIndex.cpp:475-508]**
   - Instances are split into separate instancers by: material bindings, purpose, geomModel (draw mode), model (assetInfo), skel binding, and the *set* of constant primvar names and roles. **[src V/usdImaging/usdImaging/sceneIndices.cpp:142-158; niInstanceAggregationSceneIndex.cpp:733-798]**
   - Visibility becomes `instancerTopology/mask`. **[src …:591-621]**
6. **Native instancers populate `instanceLocations` (instance-root paths); point instancers do not.** For a point instancer, the instance index equals the USD point index. **[src niInstanceAggregationSceneIndex.cpp:560-589,643-645; V/usdImaging/usdImaging/dataSourcePointInstancer.cpp:256-275]**
7. **Time-varying information is available in two forms, with different gaps.**
   - Per-data-source `GetContributingSampleTimesForInterval`.
   - The set of dirty notices emitted by `SetTime`, which covers exactly the locators flagged by `ValueMightBeTimeVarying` *for data sources that have been pulled*.
   - Visibility, instancer masks, and several mesh fields (orientation, doubleSided, subdivisionScheme, subdivisionTags) report no sample times. Some of these are not flagged at all. See §8.

---

## 1. `UsdImagingCreateSceneIndices`

### 1.1 Options (`UsdImagingCreateSceneIndicesInfo`) **[src V/usdImaging/usdImaging/sceneIndices.h:32-50]**

| Field | Default | Meaning |
|---|---|---|
| `stage` | – | `UsdStageRefPtr`. Can be set later with `stageSceneIndex->SetStage`. |
| `stageSceneIndexInputArgs` | null | Container passed to `UsdImagingStageSceneIndex::New`. The only key read is `includeUnloadedPrims` (bool). **[src stageSceneIndex.cpp:190-204]** |
| `addDrawModeSceneIndex` | `true` | Inserts `UsdImagingDrawModeSceneIndex` through the prototype-propagation callback, at every instancing level. |
| `displayUnloadedPrimsWithBounds` | `false` | Forces `includeUnloadedPrims=true` and inserts `UsdImagingUnloadedDrawModeSceneIndex`. **[src sceneIndices.cpp:78-91,213-216]** |
| `overridesSceneIndexCallback` | empty | Lets the client insert scene indices right after the stage scene index. **[src sceneIndices.cpp:208-211]** |

There is a second overload that takes an inputArgs container in `UsdImagingUsdSceneIndexInputArgsSchema` form (`stage`, `includeUnloadedPrims`, `displayUnloadedPrimsWithBounds`, `addDrawModeSceneIndex`). **[src sceneIndices.cpp:313-341; V/usdImaging/usdImaging/hdSchemaDefs.py:15-22]**

Environment settings that matter:
- `USDIMAGING_SET_STAGE_AFTER_CHAINING_SCENE_INDICES` (default true). The stage is set after the chain is built, so `PrimsAdded` flows down the whole chain. **[src sceneIndices.cpp:40-48,302-308]**
- `HD_USE_ENCAPSULATING_SCENE_INDICES` wraps the result in an encapsulating scene index. **[src :296-300]**

### 1.2 Chain, in order **[src V/usdImaging/usdImaging/sceneIndices.cpp:185-311]**

1. **`UsdImagingStageSceneIndex`** → handle `stageSceneIndex`. USD prims become Hydra prims through the prim and API-schema adapters. No flattening and no instancing (see §2).
2. *(optional)* the client's `overridesSceneIndexCallback`.
3. *(optional)* `UsdImagingUnloadedDrawModeSceneIndex`: unloaded prims get draw mode `bounds`.
4. **`UsdImagingExtentResolvingSceneIndex`**: uses `extentsHint` when `extent` is unauthored, for purposes geometry/render/proxy. The header has a TODO: it does not call `UsdGeomComputeExtentFunction`. **[src extentResolvingSceneIndex.h; sceneIndices.cpp:93-115]**
5. **`UsdImagingPiPrototypePropagatingSceneIndex`**: point instancers become `instancer` prims. Each prototype is copied to `<protoPath>/ForInstancer<hash>` with `instancedBy`. Prims under an instancer or `over` inside a prototype are made unrenderable. **[src piPrototypePropagatingSceneIndex.h:23-80; piPrototypePropagatingSceneIndex.cpp:415; piPrototypeSceneIndex.cpp:185-230]**
6. **`UsdImagingNiPrototypePropagatingSceneIndex`**: native instancing. It is internally a merging scene index made of these pieces (§5):
   - pruning: `UsdImaging_NiPrototypePruningSceneIndex`
   - `UsdImaging_NiPrototypeSceneIndex`
   - **`HdFlatteningSceneIndex(UsdImagingFlattenedDataSourceProviders())`**
   - draw mode, when enabled
   - `UsdImaging_NiInstanceAggregationSceneIndex`
   - recursive `UsdImagingRerootingSceneIndex` + `NiPrototypePropagating` per instancer.
   **[src niPrototypePropagatingSceneIndex.cpp:169-253,454-506]**
7. **`HdNoticeBatchingSceneIndex`** → handle `postInstancingNoticeBatchingSceneIndex`. Batching is off by default.
8. **`UsdImaging_InstanceProxyPathTranslationSceneIndex`**: rewrites path-valued data sources that target instance proxies, so they point at prototype paths. It applies to `usdMaterialBindings` plus plugin-provided names (skel binding). **[src sceneIndices.cpp:163-183,281-282; instanceProxyPathTranslationSceneIndex.h]**
9. **`UsdImagingMaterialBindingsResolvingSceneIndex`**: turns flattened USD direct and collection bindings into Hydra `materialBindings/<purpose>/path` (§6).
10. **Plugin scene indices** (`UsdImagingSceneIndexPlugin`). In Blender's build that is `UsdSkelImagingResolvingSceneIndexPlugin`, which appends `UsdSkelImagingSkeletonResolvingSceneIndex` then `UsdSkelImagingPointsResolvingSceneIndex`. **[src sceneIndices.cpp:64-76; V/usdImaging/usdSkelImaging/resolvingSceneIndexPlugin.cpp:22-41]**
11. **`UsdImagingSelectionSceneIndex`** → handle `selectionSceneIndex`. `AddSelection(usdPath)` and `ClearSelection()`.
12. **`UsdImagingRenderSettingsFlatteningSceneIndex`**: flattened render settings.
13. → `finalSceneIndex`.

### 1.3 Handles exposed **[src sceneIndices.h:54-60]**

- `stageSceneIndex`: `SetTime`, `ApplyPendingUpdates`, `SetStage`, `GetTime`.
- `postInstancingNoticeBatchingSceneIndex`: `SetBatchingEnabled`, `Flush`.
- `selectionSceneIndex`
- `finalSceneIndex`

### 1.4 Not included, and must be added by a consumer

All of these exist in hdsi (§4). Renderers add them through `HdSceneIndexPluginRegistry`.

| Filter | Needed by Proscenium? | Added by Storm (`V/imaging/hdSt/*SceneIndexPlugin.cpp`) | hdPrman (`third_party/renderman/plugin/hdPrman`) |
|---|---|---|---|
| `HdsiImplicitSurfaceSceneIndex` | yes (toMesh) | yes, all six shapes toMesh **[src hdSt/implicitSurfaceSceneIndexPlugin.cpp:57-73]** | yes (implicitSurfaceSceneIndexPlugin.cpp) |
| `HdsiNurbsApproximatingSceneIndex` | maybe | yes | – |
| `HdsiMaterialBindingResolvingSceneIndex` (pick one purpose) | or do it yourself | yes: `preview`, then `allPurpose` **[src hdSt/materialBindingResolvingSceneIndexPlugin.cpp:51-57]** | (matfilt) |
| `HdsiMaterialPrimvarTransferSceneIndex` | optional | yes | yes |
| `HdDependencyForwardingSceneIndex` (turns `__dependencies` into dirty notices) | **yes**, if relying on dirty locators after implicit/NURBS/skel filters | yes | yes |
| `HdSiExtComputationPrimvarPruningSceneIndex` (CPU skinning becomes plain primvars) | **yes**, for skinned points | – | yes |
| `HdsiVelocityMotionResolvingSceneIndex` | probably not | yes | yes |
| `HdsiTetMeshConversionSceneIndex` | maybe | yes | yes |
| `HdsiPinnedCurveExpandingSceneIndex` | if curves supported | – | yes |
| Another flattening pass | **no**, already present (§0.1) | – | – |

Others: Storm also adds node-identifier resolving, unbound-material pruning, render-pass prune/visibility, and dependency scene indices. hdPrman adds light linking, coordSys prims, Riley conversion, and more (file list checked).

The docs say the same in general terms: "The UsdImaging library provides the method UsdImagingCreateSceneIndices to create a UsdImagingStageSceneIndex and all of its associated filters." **[docs https://openusd.org/release/api/_page__hydra__getting__started__guide.html]**

---

## 2. `UsdImagingStageSceneIndex`

**Population.**
- `SetStage` registers for `UsdNotice::ObjectsChanged` on that stage and walks it with `UsdPrimRange`. **[src stageSceneIndex.cpp:376-402,404-478]**
- The predicate is `UsdPrimIsActive && !UsdPrimIsAbstract`, plus `UsdPrimIsLoaded` unless `includeUnloadedPrims`. **Undefined prims (`over`s) are traversed on purpose**; the PI and NI prototype scene indices empty their types later. **[src :480-503]**
- Instance proxies are never populated. `GetPrim` returns empty for them. **[src :263-265]**
- USD prototypes (`/__Prototype_N`) are populated as root children. **[src :343-347,414-416]**
- Each prim yields its "" subprim, plus property-path subprims an adapter declares. **[src :46-99,465-476]**

**Prims with no adapter** (Xform, Scope, untyped, unknown or custom typed schemas):
- They get `primType = ""` and `UsdImagingDataSourcePrim`, which carries xform, visibility, purpose, extent, primvars, `__usdPrimInfo` and `primOrigin`. **[src adapterManager.cpp:72-100,206-224; dataSourcePrim.cpp:672-713]**
- An adapter that returns null data still gets an empty container. **[src stageSceneIndex.cpp:279-283]**

**Edits.**
- `_OnUsdObjectsChanged` queues edits into three lists:
  - prim resyncs: whole subtree repopulated;
  - property resyncs and updates: become dirty locators through the adapters' `InvalidateImagingSubprim`;
  - asset-path resyncs: re-dirty recorded asset-path-dependent attributes.
  **[src :507-593]**
- Info-only changes to *plugin* metadata fields on a prim trigger a resync. Built-in field changes are ignored. **[src :557-574]**
- Nothing reaches observers until **`ApplyPendingUpdates()`**. **[src :750-791]**
- In a resync, removals of paths that are re-added are dropped, so observers see `PrimsAdded` for re-synced prims, not remove+add. **[src :698-736]**
- An adapter can request repopulation by dirtying `UsdImagingTokens->stageSceneIndexRepopulate`. **[src :858-871]**

**Layer reload, recomposition, session-layer edits, population masks.**
- These all arrive as ordinary `ObjectsChanged` resyncs or changes, so they take the same path. **[inferred]**
- A layer reload typically resyncs `/` and repopulates everything. **[inferred]**
- Population masks and unloaded payloads simply limit what the stage traversal sees. **[inferred]**
- **Gotcha [inferred]:** data sources read USD lazily at pull time (`UsdAttributeQuery::Get` with the current time), and flattening caches its results until dirtied. Reading between a USD edit and `ApplyPendingUpdates` can therefore mix fresh attribute values with stale topology or flattened caches. Always call `ApplyPendingUpdates` before capture.

**`SetTime(time, forceDirtyingTimeDeps=false)`.**
- It is a no-op if the time is unchanged. **[src :354-369]**
- Otherwise it emits `PrimsDirtied` for **every** (path, locator set) recorded through `FlagAsTimeVarying`. **[src :902-914]**
- Locators are recorded when a data source is *constructed* and its query's `ValueMightBeTimeVarying()` is true, e.g. `UsdImagingDataSourceAttribute` ctor, xform, visibility, primvars. **[src dataSourceAttribute.h:226-243; dataSourcePrim.cpp:35-46,458-469; dataSourcePrimvars.cpp:303-327]**
- Consequences:
  - Only prims whose data sources have been pulled are dirtied. **[inferred]**
  - A value that is time-varying overall is dirtied even when it is identical at both times.
  - The map is cleared only by `SetStage`, so entries persist across resyncs. **[src :963-972]**

**Lifetime.**
- The stage scene index holds a **strong** `UsdStageRefPtr _stage`. **[src stageSceneIndex.h:154]**
- Release requires `SetStage(nullptr)` or destroying the whole chain. Downstream scene indices hold refs to upstream ones, and destruction emits no notices. **[src stageSceneIndex.cpp:217-238]**
- This matters for M3's "bridge must not keep released stages alive".

**Root prim.** `/` carries `system` (asset resolution) and `sceneGlobals` (render-settings prim path). **[src dataSourceStage.cpp:25-52]**

---

## 3. Prim adapters in v26.03 and the Hydra types they produce

Taken from each adapter's `GetImagingSubprimType` (grep over `V/usdImaging/*/…Adapter.cpp`) and the plugInfo files.

| USD type / API | Hydra type |
|---|---|
| Mesh | `mesh` |
| GeomSubset | `geomSubset` (child prim) |
| BasisCurves | `basisCurves` |
| NurbsCurves | `nurbsCurves` |
| NurbsPatch | `nurbsPatch` |
| Points | `points` |
| TetMesh | `tetMesh` |
| Volume | `volume` |
| Capsule, Cone, Cube, Cylinder, Sphere, Plane | same names (implicit, not meshes) |
| Camera | `camera` |
| PointInstancer | `instancer` |
| Material (+ Shader/NodeGraph represented by the material) | `material` |
| Rect/Sphere/Disk/Cylinder/Distant/Dome(_1)/Plugin lights | `rectLight`, … `domeLight`, `pluginLight` |
| LightAPI (on any prim, e.g. mesh lights) | `light` |
| PortalLight | `light` |
| LightFilter | `lightFilter` |
| RenderSettings/Product/Var/Pass | `renderSettings` etc. |
| Skeleton | `skeleton`, turned into a guide `mesh` by the skeleton resolving SI |
| SkelAnimation | `skelAnimation` |
| BlendShape | `skelBlendShape` |
| SkelRoot | "" |
| OpenVDBAsset / Field3DAsset / ParticleField (usdVolImaging) | `openvdbAsset`, `field`, `particleField` |
| GenerativeProcedural (usdProcImaging) | – |
| **HermiteCurves** | Hydra-1 adapter only, **no 2.0 data**: `""`. The adapter returns null data, so the prim gets only an empty container: no xform or primvars **[src hermiteCurvesAdapter.cpp:37-48; stageSceneIndex.cpp:279-283] [inferred for the consequence]** |
| API adapters | MaterialBindingAPI, CollectionAPI, CoordSysAPI, GeomModelAPI, LightAPI, SkelBindingAPI, Pxr* |

**Custom schemas.** They need an adapter or API-schema adapter registered in plugInfo, or a keyless API adapter. Otherwise they are "" prims. `__usdPrimInfo/typeName` still names the USD type. **[src dataSourceUsdPrimInfo.cpp:63,91-92; hdSchemaDefs.py:29-43]**

### Mesh **[src V/usdImaging/usdImaging/dataSourceMesh.cpp:71-167]**

- `mesh/topology/{faceVertexCounts, faceVertexIndices, holeIndices, orientation}`
- `mesh/subdivisionScheme`
- `mesh/doubleSided`
- `mesh/subdivisionTags/{faceVaryingLinearInterpolation, interpolateBoundary, triangleSubdivisionRule, cornerIndices, cornerSharpnesses, creaseIndices, creaseLengths, creaseSharpnesses}`

All values are passed through raw: no triangulation, no hole removal. Only counts, indices and holes are registered for time-variance. Orientation, scheme, doubleSided and tags are **not**, so animating them does not dirty on `SetTime`.

### GeomSubset **[src geomSubsetAdapter.cpp:106-148]**

- Each `UsdGeomSubset` child of a mesh is a separate child prim of type `geomSubset`.
- `HdGeomSubsetSchema` has only `type` (`typeFaceSet`/`typePointSet`; others warn and give an empty token) and `indices`. **[src :62-78; V/imaging/hd/hdSchemaDefs.py:61-75]**
- **`familyName`/`familyType` are not exposed.** All subsets appear, whatever their family. Hydra 1 only used the `materialBind` family. **[src meshAdapter.cpp:101-115]**
- Per-subset material bindings come from MaterialBindingAPI on the subset, resolved like any prim.
- Because subsets are namespace children of the mesh, flattening gives a subset without its own binding the mesh's binding. **[inferred]**
- The consumer must read the family from USD, or treat only `materialBind` subsets as material partitions.

### Primvars **[src dataSourcePrimvars.cpp:82-178,285-393]**

- **Indexed primvars are preserved:** `indexedPrimvarValue` + `indices`. Non-indexed primvars have `primvarValue`. `HdPrimvarSchema::GetFlattenedPrimvarValue()` expands on demand. **[src V/imaging/hd/primvarSchema.cpp:172-202]**
- Each primvar carries `interpolation` (USD tokens map 1:1), `role` (from the value-type role), `colorSpace` (for color role), and `elementSize` (only when ≠1).
- Only *authored* primvars appear. `displayColor` and `displayOpacity` have no fallback. **[src :96-104,140-142]**
- `primvars:points/velocities/accelerations` are rejected in favour of the attributes. **[src :44-62]**
- For PointBased prims: `points`, `velocities`, `accelerations`, `normals`, and `widths` (curves) come from the attributes. `primvars:normals` is stronger than `normals`. **[src dataSourceGprim.cpp:31-104]**
- Primvar relationships become constant path-valued primvars. **[src dataSourcePrimvars.cpp:167-174]**

### Other prim types

- **BasisCurves:** `basisCurves/topology{curveVertexCounts, curveIndices, basis, type, wrap}` + `widths`. **[src hdSchemaDefs.py BasisCurvesTopology]**
- **Points, volumes, cameras, lights:** distinct prim types that need their own support or a diagnostic.

---

## 4. hdsi filters in v26.03

From each header's first comment block, `V/imaging/hdsi/*.h`.

| Filter | Purpose |
|---|---|
| computeSceneIndexDiff | Computes added/removed/dirtied between two scene indices. |
| coordSysPrimSceneIndex | Adds `coordSys` prims for coordSys bindings. |
| debuggingSceneIndex (+Plugin) | Consistency checker. |
| domeLightCameraVisibilitySceneIndex | Overrides dome-light camera visibility. |
| extComputationDependencySceneIndex | Dependencies for ext computations. |
| **extComputationPrimvarPruningSceneIndex** | Turns computed primvars into authored primvars; runs the CPU kernel when pulled. |
| **implicitSurfaceSceneIndex** | Implicits → mesh, or spine axis → transform. |
| legacyDisplayStyleOverrideSceneIndex | refineLevel, cullStyle overrides. |
| lightLinkingSceneIndex | Light-linking categories. |
| **materialBindingResolvingSceneIndex** | Picks one purpose from `materialBindings` by priority. |
| materialOverrideResolvingSceneIndex | Material override resolution (no doc comment). |
| materialPrimvarTransferSceneIndex | Transfers primvars from the bound material to the geometry. |
| materialRenderContextFilteringSceneIndex | Keeps the first matching render context. |
| nodeIdentifierResolvingSceneIndex | sourceAsset → nodeIdentifier. |
| **nurbsApproximatingSceneIndex** | nurbsCurves → basisCurves, nurbsPatch → mesh. |
| pinnedCurveExpandingSceneIndex | Expands pinned curves. |
| prefixPathPruningSceneIndex | Prunes subtrees. |
| primManagingSceneIndexObserver | RAII prim objects (HdPrimTypeIndex analogue). |
| primTypeAndPathPruningSceneIndex | Prunes by type and path predicate (keeps hierarchy). |
| primTypeNoticeBatchingSceneIndex | Batches notices by type priority. |
| primTypePruningSceneIndex | Prunes by type and its bindings. |
| renderPassPruneSceneIndex | Render-pass prune rules. |
| renderSettingsFilteringSceneIndex | Render-settings filtering. |
| sceneGlobalsSceneIndex | Sets sceneGlobals. |
| sceneMaterialPruningSceneIndex | Prunes materials and bindings. |
| switchingSceneIndex | Switches between inputs. |
| tetMeshConversionSceneIndex | TetMesh → triangle mesh. |
| unboundMaterialPruningSceneIndex | Prunes unbound materials. |
| **velocityMotionResolvingSceneIndex** | Velocity/acceleration-based motion. |

There is no composition scene index in hdsi. dev adds locatorCaching, primId, particleFieldConversion, backPlate and applicationRenderSettings (§11).

### 4.1 Implicit surfaces **[src V/imaging/hdsi/implicitSurfaceSceneIndex.cpp]**

**Configuration.**
- Per-type modes come from inputArgs: `{cube, cone, cylinder, sphere, capsule, plane} → toMesh | axisToTransform`. **[src :1544-1554; .h:19-20]**
- `axisToTransform` exists only for cone and cylinder. Capsule has none. **[src :1570-1599]**

**Output.**
- Prim type becomes `mesh`.
- The original schema is overlaid with `HdBlockDataSource`.
- `mesh` is added: the generator's topology, `orientation=rightHanded`, `doubleSided=false` hard-coded.
- `primvars/points` is added (role point, interpolation vertex), computed from size/radius/height/axis (and radiusTop/radiusBottom for cylinder and capsule).
- Everything else (xform, primvars such as displayColor, material bindings) comes through from the input overlay.
- **[src :145-283,1558-1625]**
- Authored `doubleSided` on the implicit is ignored. **[inferred from :168-169]**

**Exactness.**

| Shape | Exact? | Scheme |
|---|---|---|
| Cube | exact (8-point bilinear box) | bilinear |
| Plane | exact (quad) | bilinear |
| Sphere | polygonal 10×10 | catmullClark |
| Cone | 10 radial | catmullClark |
| Cylinder | 10 radial | catmullClark |
| Capsule | 10 radial, 4 per cap | catmullClark |

- Under subdivision the curved shapes are a smooth approximation of the cage, not the true surface. Hydra emits **no approximation diagnostic**.
- The consumer can detect a converted prim in three ways:
  - (a) keep a handle to the pre-implicit scene index and compare types;
  - (b) check for `__dependencies/implicitToMesh`;
  - (c) read `__usdPrimInfo/typeName` (Sphere, etc.).
  **[inferred]**
- The fidelity constants are compile-time. Better tessellation means writing your own filter. **[src :295,480,708-709,863-865]**

**Change tracking.**
- `_PrimsDirtied` forwards locators unchanged. **[src :1694-1704]**
- So a `sphere/radius` change (or `SetTime` on animated radius, flagged via `UsdImagingDataSourceMapped`) arrives as `sphere/radius`, not `primvars/points`.
- Translation needs `HdDependencyForwardingSceneIndex` downstream, which reads `__dependencies`. **[src :87-110; dataSourceImplicits-Impl.h:36-94]**
- Sample times for points follow the size/radius data sources. **[src :197-206]**

### 4.2 NURBS **[src V/imaging/hdsi/nurbsApproximatingSceneIndex.cpp]**

- `nurbsCurves` becomes `basisCurves` with **`linear` basis over the control points**. Only `curveVertexCounts` is used, so knots, order, weights and ranges are ignored. **[src :28-32,75-98]**
- `nurbsPatch` becomes a quad mesh of the control-vertex grid with `catmullClark` scheme. Trims, knots and weights are ignored. **[src :258-296,355-367]**
- The header calls it "only an approximation". **[src .h:17-23]**
- There is no diagnostic.

### 4.3 Material binding purpose resolving

- `HdsiMaterialBindingResolvingSceneIndex` collapses `materialBindings/<purpose>` to one destination purpose, taking the first found in a priority list. **[src materialBindingResolvingSceneIndex.h:18-20]**
- Storm uses `[preview, allPurpose]`. **[src hdSt/materialBindingResolvingSceneIndexPlugin.cpp:51-57]**

### 4.4 Material primvar transfer

Primvars on the bound material are copied to the geometry. Inherited primvars are stronger, so this filter must run after flattening. **[src materialPrimvarTransferSceneIndex.h:18-29]**

---

## 5. Native instancing

### 5.1 Pipeline

`UsdImagingNiPrototypePropagatingSceneIndex` is a merging scene index of:
- the stage minus prototypes (`NiPrototypePruning`) → `NiPrototypeSceneIndex(forPrototype=false)` → flattening → draw mode;
- an `NiInstanceAggregation` scene index on that;
- per added instancer, a `UsdImagingRerootingSceneIndex(/UsdNiInstancer → <instancerPath>)` wrapping a recursive `NiPrototypePropagating` for that prototype name and binding-overlay hash. That recursive one isolates `/__Prototype_N` → `/UsdNiInstancer/UsdNiPrototype`.

Scene indices are cached per (prototype name, binding hash). **[src niPrototypePropagatingSceneIndex.cpp:41-280,454-506; .h:63-120]**

`UsdImaging_NiPrototypeSceneIndex`:
- forces empty type on renderable instance prims;
- overlays the prototype root with `instancedBy{paths:[/UsdNiInstancer], prototypeRoots:[/UsdNiInstancer/UsdNiPrototype]}`, xform identity with `resetXformStack=true`, and the binding-scope data;
- underlays `instancedBy` on all prototype descendants.

**[src niPrototypeSceneIndex.cpp:57-93,142-200]**

### 5.2 Hydra paths

These are hashed and rename-unstable. **[src niInstanceAggregationSceneIndex.cpp:864-912,1863-1890]**

```
<enclosingProtoRoot>/UsdNiPropagatedPrototypes/<bindingHash>/<__Prototype_N>/UsdNiInstancer          (instancer)
<enclosingProtoRoot>/UsdNiPropagatedPrototypes/<bindingHash>/<__Prototype_N>/UsdNiInstancer/UsdNiPrototype/...   (prototype copy)
```

- `<bindingHash>` is `"NoPrimvars"` or `"Primvars%zx"`, plus `_<name>%zx` for each binding data source present. **[src :741-798]**
- The header examples show `NoBindings` and `Bindings…`. Those are outdated against this code. **[inferred]**
- `enclosingProtoRoot` is `/` for top level, the PI `ForInstancer…` copy when inside a point-instanced prototype, or `/UsdNiInstancer/UsdNiPrototype` (rerooted) when nested.
- The instance root (e.g. `/Cube_1`) stays as a ""-typed prim carrying flattened xform and `instance{instancer, prototypeIndex=0, instanceIndex}`. **[src :1674-1735]**
- Point-instancer prototypes are copied to `<proto>/ForInstancer<hash>`. **[src piPrototypePropagatingSceneIndex.cpp:415]**
- USD prototypes `/__Prototype_N` are pruned from the final scene.

### 5.3 How aggregation groups instances

The key is (enclosing prototype root, binding hash, USD prototype name). **[src niInstanceAggregationSceneIndex.h:32-40; .cpp:864-873,1354-1404]**

The binding hash combines:
- the **set of constant primvar names and roles** (not values);
- data-source hashes of `instanceDataSourceNames`: `materialBindings` (USD, flattened), `purpose`, `geomModel` (drawMode, applyDrawMode, cards…), `model` (assetInfo), and `skelBinding` from the plugin. **[src sceneIndices.cpp:131-161; resolvingSceneIndexPlugin.cpp:53-59]**

The values are *flattened*: the input is the flattening scene index. So a binding inherited from an ancestor of the instance root splits groups just as one authored on the root does. **[src niPrototypePropagatingSceneIndex.cpp:187-217]**

Binding paths under the instance are rerooted relative to the prototype before hashing, so `/I1/Mat` and `/I2/Mat` hash equal. **[src .cpp:1375-1401]**

What happens to each kind of inherited state:
- **Differing material binding / purpose / draw mode / assetInfo** → separate instancer and separate propagated prototype copy. The binding copy (`_MakeBindingCopy`) is overlaid on the prototype root and flattened into descendants with weaker opinions. **[src .cpp:840-862; niPrototypePropagatingSceneIndex.cpp:475-501]**
- **Differing primvar values** (same names) → same instancer. Values go to `instancer.primvars/<name>` with `interpolation=instance`, one per instance. **[src .cpp:149-336,475-508]**
- **Visibility** → `instancerTopology/mask[i]` (flattened visibility of instance i at shutter 0). **[src :591-621]**
- **Xform** → `primvars/hydra:instanceTransforms[i]`: the instance's flattened matrix, world or relative to the enclosing prototype. **[src :365-473]**
- The instancer itself has no xform. **[src :669-731]**
- Dirty handling:
  - xform dirties `instanceTransforms`;
  - primvar *value* dirties the instancer primvar;
  - a change to primvar set or interpolation, or to a key data source, re-aggregates;
  - visibility dirties `mask`.
  **[src :1170-1300]**
- **[inferred]** The renderer convention that the prototype gprim's own primvar beats the instance primvar is not encoded in the data. The consumer must apply that precedence itself, plus outer-before-inner order for nested instancers.

### 5.4 Instancer schemas as populated for native instances **[src :534-731]**

- `instancerTopology`:
  - `prototypes = [<instancer>/UsdNiPrototype]` (always one);
  - `instanceIndices = [[0..n-1]]`;
  - `mask = [vis_i]`;
  - `instanceLocations = [instance root paths]`.
  - The order is **sorted `SdfPathSet` order**, so indices shift when instances are added or removed. That re-dirties `instance` on every member. **[src :1640-1656,1780-1811]**
- `instance` (on the instance root): `{instancer, prototypeIndex: 0, instanceIndex: i}`.
- `instancedBy` (on prototype prims and nested instancers): `{paths:[instancer], prototypeRoots:[protoRoot]}`. A nested instancer takes the outer `instancedBy`. **[src :680-698]**
- `primOrigin/scenePath` on prims inside a prototype is the prototype-relative path, which equals the path relative to any instance root. **[src dataSourcePrim.cpp:510-557]**

**Point instancers** **[src dataSourcePointInstancer.cpp:98-140,160-280,349-370]**:
- `prototypes` are the `ForInstancer` copies.
- `instanceIndices[p]` are the original point indices whose `protoIndices == p`, so the **instance index is the USD point index**.
- `mask` comes from `ComputeMaskAtTime` (invisibleIds/inactiveIds).
- The primvars are `hydra:instanceTranslations`, `hydra:instanceRotations`, `hydra:instanceScales`, plus raw velocities and accelerations.
- **No `instanceLocations`.**

The schema doc: `instanceLocations` is meaningful for implicit (native) instancing and "meaningless" for explicit instancing. **[src V/imaging/hd/instancerTopologySchema.h:74-90]**

### 5.5 Forward mapping (USD path → Hydra), as `UsdImagingSelectionSceneIndex` does it **[src selectionSceneIndex.cpp:198-608]**

- Walk the USD path one element at a time from `/`. Append each name to the current Hydra path.
- If the Hydra prim has an `instance` schema:
  - record `{instancer, prototypeIndex, instanceIndex}`;
  - replace the current path with `instancer.instancerTopology.prototypes[prototypeIndex]`.
  - **[src :453-532,578-608]**
- If it has `__usdPrimInfo/piPropagatedPrototypes`, also fork into each PI copy with all of that instancer's indices. **[src :371-409,543-573]**
- Result: a set of Hydra paths, each with a nested instance-indices vector (outermost first).
- `AddSelection` only writes `selections` data sources. To *use* the algorithm without selection state, reimplement it. It is about 100 lines.
- Note: dev rewrote this file (parallel wavefront; skips descending into NI propagated prototypes). **[dev D/usdImaging/usdImaging/selectionSceneIndex.cpp diff]**

### 5.6 Reverse mapping algorithm (Hydra prim + instance indices → USD source + instance context)

**[inferred, from the schemas above; must be verified by the M1b fixture]**

```
resolve(hydraPath P):                         # returns list of (usdPath, context[], worldXform) per drawn copy
  ib = P.instancedBy
  if !ib: return [(P, [], P.xform.matrix)]    # outside instancing: Hydra path == USD path (flattened world xform)
  I = ib.paths[0]; R = ib.prototypeRoots[0]
  rel = P.MakeRelativePath(R)                 # == P.primOrigin.scenePath (except PI roots: '.')
  topo = I.instancerTopology
  p = index of R in topo.prototypes
  out = []
  for (instancerCopy in resolve(I)):          # recursion handles nested instancers (I itself has instancedBy)
    for k in topo.instanceIndices[p]:
      if topo.mask nonempty and !topo.mask[k]: continue
      if topo.instanceLocations:             # native instancer
        L = topo.instanceLocations[k]         # Hydra path of instance root, in I's namespace
        # L may itself lie in an outer propagated prototype: map it with the same rule
        rootUsd = mapContainerPath(L, instancerCopy)   # = outerInstanceRootUsd / L.MakeRelativePath(outerR)
        usd = rootUsd / rel                   # USD instance-proxy path, e.g. /Outer/Inner/Mesh
        ctx = instancerCopy.ctx + [rootUsd]   # chain of native-instance roots (outermost first)
        localXf = I.primvars.hydra:instanceTransforms[k]
      else:                                   # point instancer
        usd = R.GetParentPath() / rel         # R = <usdProto>/ForInstancer<hash>
        ctx = instancerCopy.ctx + [(I-as-USD, point index k)]
        localXf = compose(translations[k], rotations[k], scales[k])
      world = P.xform(proto-relative) * localXf * instancerCopy.world   # row-vector convention
      out.append((usd, ctx, world))
  return out
```

Why this works:
- Path-valued data sources (including `instanceLocations`) are rewritten through `UsdImagingRerootingContainerDataSource` when prototypes are rerooted. So nested `instanceLocations` are paths in the *outer propagated prototype's* Hydra namespace. **[src rerootingSceneIndex.h:17-28; rerootingSceneIndex.cpp:39-65; rerootingContainerDataSource.cpp:15-61]**
- The instancer itself carries no xform. The prototype root is identity. Instance transforms are relative to the enclosing prototype. Therefore world = protoLocal × innerInstance × outerInstance × … × (PI instancer's own flattened xform for PIs). **[src niPrototypeSceneIndex.cpp:81-93; niInstanceAggregationSceneIndex.cpp:394-407] [inferred composition]**

Durable identity:
- Instance indices are positional (sorted path order) and the Hydra paths contain hashes.
- Durable identities should be (USD source path, chain of instance-root USD paths), as the algorithm produces. For PIs the context element is (PI USD path, point index).

---

## 6. Materials

**Network.**
- `UsdImagingDataSourceMaterial` builds `material/<renderContext>` → `HdMaterialNetworkSchema{nodes, terminals, interface}`.
  - Node: `{parameters{value, colorSpace, typeName}, inputConnections{upstreamNodePath, upstreamNodeOutputName}, nodeIdentifier, renderContextNodeIdentifiers, nodeTypeInfo}`.
  - **[src V/imaging/hd/hdSchemaDefs.py MaterialNetwork/Node; V/usdImaging/usdImaging/dataSourceMaterial.cpp:600-1030]**
- Render contexts come from the material's output namespaces (`outputs:surface` → "", `outputs:ri:surface` → `ri`), plus an "all" context. **[src :619-650]**
- Terminals are resolved with `ComputeSurfaceSource/DisplacementSource/VolumeSource(renderContext)`. **[src :811-830]**
- Node names are paths relative to the material prim. **[src :846-851]**
- `sourceColorSpace` on UsdUVTexture is folded into the file parameter's colorSpace. **[src :225-227]**
- Interface (public input) mappings are emitted. **[src :737-750]**

**Shaders and dirtying.**
- Shaders are **not** separate Hydra prims: the material adapter is `RepresentsSelfAndDescendents`. **[src materialAdapter.cpp:254-257]**
- A Shader input edit dirties the terminal locator connected to it, or else the whole `material` locator. **[src materialAdapter.cpp:186-251]**
- A public interface input edit dirties all of `material`. **[src dataSourceMaterial.cpp:1062-1088]**
- Animated shader parameters are flagged time-varying on the material prim. **[src :1010-1012; materialParamUtils.cpp:436]**

**Binding resolution.** `UsdImagingMaterialBindingsResolvingSceneIndex` **[src materialBindingsResolvingSceneIndex.cpp:36-305]**:
- Reads the flattened `usdMaterialBindings` vectors, ancestors first, holding direct and collection bindings.
- Applies `strongerThanDescendants`. A collection binding beats a direct one at the same level.
- Evaluates collection membership with `HdCollectionExpressionEvaluator` **on Hydra paths**: "XXX This does not handle instance proxy paths yet". **[src :136]** **[inferred consequence: collection bindings that target prims inside native instances by USD path will not match prototype copies]**
- Writes `materialBindings/<purpose>/path`. It does not fall back from a specific purpose to allPurpose. **[src :88-92]**
- The header's "does not factor in collection bindings" note is outdated against the code.

**Instancing interaction.**
- Materials inside a USD prototype are duplicated per propagated copy.
- Bindings to instance-proxy material paths are translated to prototype paths by stage 8 of §1.2. **[src sceneIndices.cpp:163-183,275-282]**

---

## 7. Skinning (UsdSkelImaging v26.03)

- **Included by default:** yes. Its plugin is appended in `_AddPluginSceneIndices` when usdSkelImaging is registered, which it is in Blender's build. **[src sceneIndices.cpp:287-288; resolvingSceneIndexPlugin.cpp:22-41]**
- Order: `SkeletonResolving`, then `PointsResolving`.
- **Mode.** With `HD_ENABLE_DEFERRED_SKINNING=false` (the default), points are skinned by ext computations. **[src V/imaging/hd/skinningSettings.cpp:15,29-34]**
- `PointsResolving` overlays the skinned mesh, points or basisCurves prim, under a SkelRoot with a bound Skeleton. It:
  - **blocks `primvars/points` and `primvars/normals`**;
  - adds `extComputationPrimvars/points` (and normals if `USDSKELIMAGING_ENABLE_NORMAL_COMPUTATIONS`);
  - adds ext-computation child prims under the mesh.
  - **[src dataSourceResolvedPointsBasedPrim.cpp:222-304,449-489,1062-1083; pointsResolvingSceneIndex.cpp:70-110,150-215]**
- The computation has a real **CPU callback** (classic linear and dual-quaternion). **[src dataSourceResolvedExtComputationPrim.cpp:447-448; extComputations.cpp:453-481]**
- The output is in prim-local space: `skelLocalToWorld * primWorldToLocal`. **[src extComputations.cpp:193-194,218-219]**

**What a consumer reads for deformed points at time t:**
- Append `HdSiExtComputationPrimvarPruningSceneIndex`. It replaces computed primvars with ordinary primvars whose value runs the CPU callback. **[src extComputationPrimvarPruningSceneIndex.h:19-35; .cpp:383-398]**
- Then `SetTime(t)` and read `primvars/points`.
- hdPrman does this. Storm does not; it uses GPU or ext-computation sync.
- Reading `primvars/points` without the pruning filter gives *no points* for skinned prims, since the primvar is blocked.
- Sample-time reporting of the computed points was **not verified**.
- The M1b probe must check deformed points at several times against `UsdSkel` CPU skinning (`UsdSkelSkinningQuery::ComputeSkinnedPoints`).

---

## 8. Time-varying detection

**Attributes.** `UsdImagingDataSourceAttribute::GetContributingSampleTimesForInterval` **[src dataSourceAttribute.h:71-126]**:
- Returns `false` if `!ValueMightBeTimeVarying()` or the current time is `Default`.
- Otherwise returns `GetTimeSamplesInInterval([t+start, t+end])` plus the bracketing samples outside the edges, relative to t, as **float**.
- Returns true only if more than one time results.
- **Gotcha [inferred from code]:** for a zero-width interval `[0,0]` at a time exactly on an authored sample, the result is one time, so it **returns false**. Between samples it returns true.
- Query a wide interval (e.g. `[stageStart−t, stageEnd−t]`) to ask "does this vary?"
- `ValueMightBeTimeVarying` is false with a single time sample (USD semantics), so single-sample attributes read as static.

**Xform.**
- `UsdImagingDataSourceXformMatrix` uses `XformQuery::TransformMightBeTimeVarying` / `GetTimeSamplesInInterval`. **[src dataSourcePrim.cpp:416-454]**
- It pads with the interval edges, not bracketing samples, so it returns **true for any interval** when the transform might vary.
- `resetXformStack` and xformOp order are handled inside `XformQuery`. **[src :380-414]**
- `geomXformVectors` is not multi-sampled. **[src :805-829]**

**Flattened xform** (the M1b question about a static child under an animated parent):
- Child with no local xform: the flattened data source *is* the parent's flattened container, so it reports the parent's times. **[src flattenedXformDataSourceProvider.cpp:112-116]**
- Child with a static local xform: `_MatrixCombinerDataSource` returns the merged times of parent and local, i.e. the parent's. **[src :31-40; V/imaging/hd/dataSource.cpp:71-113]**
- Child with `resetXformStack`: only its own. **[src :86-98]**
- So **yes, time variance inherited through flattening is reported** for xforms. Dirtying works too: the flattening scene index dirties descendants with the universal set on an xform or visibility change. **[src flattenedXformDataSourceProvider.cpp:137-142; flatteningSceneIndex.cpp:504-521]**
- Native-instance `instanceTransforms` report the merged times of the instances' flattened xforms. **[src niInstanceAggregationSceneIndex.cpp:380-392]**

**Visibility.**
- The visibility data source returns a retained constant `false` (or null), so there are **no sample times**. **[src dataSourcePrim.cpp:56-93]**
- Flattened visibility is a retained container too. **[src flattenedVisibilityDataSourceProvider.cpp:15-40]**
- Animated visibility *is* flagged, so `SetTime` dirties it. **[src dataSourcePrim.cpp:42-45]**
- The instancer `mask` is retained and has no times. **[src niInstanceAggregationSceneIndex.cpp:646-648]**

**Other fields.**
- **Topology:** counts, indices and holes report times and are flagged. Orientation, scheme, doubleSided and tags report times through the attribute data source but are **not flagged**, so `SetTime` will not dirty them. **[src dataSourceMesh.cpp:95-163]**
- **Points and primvars:** attribute data sources; flagged per `primvarValue`, or `indexedPrimvarValue` / `indices`. **[src dataSourcePrimvars.cpp:303-327]**
- **Implicit-generated points:** follow the size/radius sample times. **[src implicitSurfaceSceneIndex.cpp:197-206]**

**Is there an "isTimeVarying" query?**
- Not as public API. `_timeVaryingLocators` is private. **[src stageSceneIndex.h:141-143]**
- A practical detector **[inferred]**:
  1. Pull every prim's needed data sources once, so the flags are registered.
  2. Call `SetTime(t + δ)`, or `SetTime(t, true)`.
  3. Record the `PrimsDirtied` entries seen at the terminal. That is the set of time-varying (prim, locator) pairs, already expanded by flattening to descendants and rerooted into propagated prototypes.
  4. Combine with `GetContributingSampleTimesForInterval` over the stage range for interval and sample positions.
- Limits:
  - It inherits `ValueMightBeTimeVarying`'s conservative answers (value clips, splines).
  - It misses unflagged locators.
  - Entries are never cleared until `SetStage`.

---

## 9. Unsupported types, enumeration, path schemes

- Every prim appears with a type token (possibly "") and a data source. Enumerate with `HdSceneIndexPrimView(finalSceneIndex, /)` or a `GetChildPrimPaths` walk.
- Unhandled USD types are "" with `__usdPrimInfo/{typeName, specifier, isLoaded, apiSchemas, kind, niPrototypePath, isNiPrototype, piPropagatedPrototypes}`. **[src hdSchemaDefs.py:29-43; dataSourceUsdPrimInfo.cpp:63-115]**
- Hydra types the consumer doesn't translate (basisCurves, points, volume, …) arrive with their full data. A placeholder needs only xform, visibility, purpose and extent.
- Outside instancing, **Hydra path == USD path** for real prims. Added namespaces are:
  - `…/UsdNiPropagatedPrototypes/<hash>/__Prototype_N/UsdNiInstancer[/UsdNiPrototype/…]`
  - `<proto>/ForInstancer<hash>/…`
  - property-path subprims (`/Prim.subprim`), e.g. light filters and skel ext computations as children.
  - **[src stageSceneIndex.cpp:336-341]**
- Original point-instancer prototype locations remain. Prims under a PointInstancer prim or under an `over` are emptied of type. **[src piPrototypeSceneIndex.cpp:210-230,270-305]**
- A USD prototype located elsewhere (e.g. `/MyPrototype`) is *also* drawn in place, per USD rules. **[src selectionSceneIndex.cpp:624-662]**
- To map back, use `primOrigin/scenePath`: absolute outside prototypes, prototype-relative inside. Then apply §5.6.

---

## 10. Where display state is resolved

| State | Where | Notes |
|---|---|---|
| Transform | `UsdImagingDataSourceXform` (local), flattened in the NI prototype propagating chain | world, or prototype-relative |
| Visibility | Local `false`/null **[src dataSourcePrim.cpp:56-93]**; flattened (invisible ancestor ⇒ invisible) | `UsdGeomVisibilityAPI` (guide/proxy/render visibility) is **not** imaged: no adapter found by grep |
| Purpose | `HdPurposeSchema{purpose (default→geometry), inheritable, fallback}`; flattened **[src dataSourcePrim.cpp:97-140; flattenedPurposeDataSourceProvider.cpp]** | no filtering: the consumer filters render tags |
| Draw mode / model kind | `geomModel` (GeomModelAPI adapter), flattened by `UsdImagingFlattenedGeomModelDataSourceProvider`; `UsdImagingDrawModeSceneIndex` replaces geometry if enabled; kind in `__usdPrimInfo/kind` | draw-mode cards use glslfx (Storm-only) materials **[src drawModeSceneIndex.h]** |
| Extent | Authored `extent` only, or `extentsHint` via the ExtentResolving SI | no computed extents (TODO) |
| displayColor / displayOpacity | plain constant primvars if authored; inherited via flattened primvars; per-instance via instancer primvars | no fallback |
| doubleSided | `mesh/doubleSided` (fallback false) | implicit→mesh hard-codes false |
| Material binding | flattened USD bindings → resolving SI → `materialBindings` | purpose choice left to the consumer |

---

## 11. Gaps and gotchas

1. **Already-flattened output.** Don't add a second flattening pass. Prototype prims are prototype-relative; compose with instancer transforms.
2. `Flush()` on the batching scene index does nothing unless batching is enabled.
3. **No approximation diagnostics** for implicit or NURBS filters. Fidelity is hard-coded (10 segments). Curved implicits become `catmullClark` cages. NURBS becomes a control hull.
4. The implicit and NURBS filters forward dirty locators untranslated. Add `HdDependencyForwardingSceneIndex`, or re-read the whole prim on any dirty.
5. **Skinned points are blocked.** They need `HdSiExtComputationPrimvarPruningSceneIndex`. The output is local space, from a CPU callback.
6. **GeomSubset family is not exposed.** Non-materialBind subsets appear. Edge and segment element types warn and give an empty type.
7. **Native instance aggregation differs from USD prototypes.**
   - It splits by bindings, purpose, draw mode, assetInfo, skel binding, and the constant-primvar name set.
   - It merges instances that differ only in primvar *values*; those go to per-instance primvars.
   - Precedence between instance primvars and prototype primvars is not encoded.
8. Instance indices are positional (sorted paths) and Hydra paths are hashed. Neither is durable.
9. Point instancers have no `instanceLocations`. The instance index is the point index.
10. Collection material bindings are evaluated on Hydra paths; instance-proxy paths are unsupported (XXX). There is no specific-purpose → allPurpose fallback in the resolving scene index.
11. `UsdGeomVisibilityAPI` is not imaged. HermiteCurves has no Hydra 2.0 data.
12. Time variance:
    - Visibility and masks report no sample times.
    - Several mesh fields are unflagged.
    - Zero-width interval queries return false at exact sample times.
    - Flags are registered only when data sources are pulled and are never cleared until `SetStage`.
    - Hydra sample times are float.
13. The stage scene index holds a strong stage reference. Notices are queued until `ApplyPendingUpdates`, and reads in between may be inconsistent **[inferred]**.
14. Extents are not computed. `primvars:*` primvars with no authored value are absent.
15. The implicit filter ignores authored `doubleSided` and always emits rightHanded orientation.
16. `SetTime` dirties every flagged locator even when the value is unchanged. A dirty notice is not a change.

### v26.03 → dev differences that matter

- `UsdImagingCreateSceneIndices` is **deprecated** in favour of an encapsulating `UsdImagingSceneIndex`. "inputArgs" is renamed "createArgs" (`UsdImagingSceneIndexCreateArgsSchema`). **[dev D/usdImaging/usdImaging/sceneIndices.h:64-74; sceneIndex.h:32-35]**
- dev inserts `HdsiLocatorCachingSceneIndex` for materials after the stage scene index. **[dev D/usdImaging/usdImaging/sceneIndices.cpp diff]**
- dev adds `usdUpAxis` to the instance aggregation key. **[dev sceneIndices.cpp diff]**
- dev normalizes binding paths for the aggregation hash (USD-12324), so more instances aggregate. **[dev niInstanceAggregationSceneIndex.cpp diff]**
- dev adds a `UsdHydraPrimAPI::ShouldExpandInstancesForPrim` opt-out that expands native instances as instance proxies. **[dev stageSceneIndex.cpp diff]**
- dev splits `SetTime(time)` from `SetTime(time, force)`. **[dev stageSceneIndex.h diff]**
- dev rewrites the selection scene index.
- New in dev: `motionAPIAdapter`, `backPlateAPIAdapter`, `collectionPredicateLibrary`, and hdsi `primId`, `particleFieldConversion`, `backPlate`, `applicationRenderSettings`, `locatorCaching`.
- Unchanged in dev: `dataSourceAttribute.h`, `dataSourcePrimvars.cpp`, `geomSubsetAdapter.cpp`, `dataSourceMesh.cpp`, `implicitSurfaceSceneIndex.cpp`, `nurbsApproximatingSceneIndex.cpp`.
- **Implementation must target the v26.03 API.** The release docs may describe the dev forms.

### Implications for the M1b prototype

The prototype should verify these, never against Hydra's own output:
- **Chain:** use `finalSceneIndex` → implicit (toMesh) → `HdDependencyForwardingSceneIndex` → `HdSiExtComputationPrimvarPruningSceneIndex`. Drop the extra flattening. Enable batching only if `Flush` is used.
- **Subsets and primvars:** check subset families against USD. Check indexed primvars keep `indices`.
- **Implicits:** emit the approximation diagnostic yourself, from `__usdPrimInfo/typeName` ∈ {Sphere, Cone, Cylinder, Capsule} after conversion.
- **Nested instances:** fixture where outer instance roots differ in `primvars:displayColor` and in material binding. Expect the instancer count from §5.3. Run the §5.6 reverse mapping and compare against USD instance-proxy paths and `UsdGeomXformCache` world matrices.
- **Time:** compare (a) `SetTime` dirty sets and (b) wide-interval sample times against `UsdAttribute::ValueMightBeTimeVarying` / `GetTimeSamples`. Include a static mesh under an animated Xform (expect its xform reported) and animated visibility (expect a dirty notice but no sample times).
- **Skinning:** compare points at several times against UsdSkel CPU skinning.
