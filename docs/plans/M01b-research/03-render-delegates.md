# Render delegates as reference Hydra consumers: Storm, Embree, Prman

Research for Proscenium M1b. The question: what can a consumer that reads Hydra scene indices but does not render learn from three render delegates, and what should it copy or avoid?

## Conventions

- `V/` = an OpenUSD v26.03 checkout (the OpenUSD bundled with Blender 5.2). `D/` = an OpenUSD `dev` checkout (commit 5bc38c9d, 2026-10-07).
- `HdPrman/` = `third_party/renderman/plugin/hdPrman/`. `Embree/` = `pxr/imaging/plugin/hdEmbree/`.
- Labels: **[V path:line]** and **[D path:line]** mean I read that source. **[Blender 5.2.2 nm]** means I found the symbol in the exported symbols (`nm -gU`) of `/Applications/Blender.app/Contents/Resources/lib/libusd_ms.dylib`, a Blender 5.2.2 install on this machine (namespace `pxrBlender_v26_03__pxrReserved__`). A symbol being exported does not prove it behaves correctly at runtime. **[docs/URL]** is documentation. **[inferred]** is my reasoning, not a tested result.
- Nothing here was executed against a scene. Every claim comes from reading source or symbol tables.

---

## 0. Shared machinery: how a render delegate gets Hydra data in v26.03

All three delegates are classic `HdRenderDelegate`s. In v26.03 they receive Hydra 2 scene-index data through **back-end emulation**:

1. `HdRenderIndex` builds its own chain. That chain is: `HdLegacyPrimSceneIndex` (for legacy scene delegates), then `HdLegacyGeomSubsetSceneIndex`, then `HdMergingSceneIndex` (UsdImaging's final scene index is inserted here), then notice batching, then **`HdSceneIndexPluginRegistry::AppendSceneIndicesForRenderer(rendererDisplayName, …)`**, then an optional `HdCachingSceneIndex`. The result is the **terminal scene index** **[V pxr/imaging/hd/renderIndex.cpp:189-243]**. Emulation is on by default (`HD_ENABLE_SCENE_INDEX_EMULATION=true`) **[V renderIndex.cpp:58]**. A newer overload, `HdRenderIndex::New(..., terminalSceneIndex)`, takes a prebuilt terminal scene index and skips the emulation front end **[V renderIndex.h:143-146; renderIndex.cpp:189-193]**.
2. An `HdSceneIndexAdapterSceneDelegate` observes the terminal scene index and turns it back into Hydra 1:
   - `PrimsAdded` becomes `_InsertRprim/Sprim/Bprim/Instancer`, but only for prim types the delegate reports as supported (`IsRprimTypeSupported` …). A `geomSubset` prim instead marks its parent `DirtyTopology` **[V hd/sceneIndexAdapterSceneDelegate.cpp:236-300]**.
   - `PrimsDirtied` turns locators into dirty bits with `HdDirtyBitsTranslator::*LocatorSetToDirtyBits` **[V …:425-495]**.
   - The scene-delegate getters (`Get`, `GetMeshTopology`, `SamplePrimvar`, `GetMaterialResource`, …) read the terminal scene index's data sources on demand **[V …:1993-2290, 2341-2560]**.
3. `HdRenderIndex::SyncAll` first calls `renderDelegate->Update()`, the hook scene-index-native delegates use **[V renderIndex.cpp:1590-1592]**. It then syncs rprims in parallel with `WorkParallelForN`, gated by `sceneDelegate->IsEnabled(parallelRprimSync)` **[V renderIndex.cpp:1800-1850]**. The adapter does not override `IsEnabled`, and the base implementation returns `true` for `parallelRprimSync` **[V hd/sceneDelegate.cpp:48-55]**. So under emulation, Sync runs in parallel and reads the terminal scene index from many threads at once.
4. **A Hydra 2 renderer API exists in v26.03.** `HdRendererPlugin::CreateRenderer(sceneIndex, rendererCreateArgs)` returns an `HdRenderer`, described as "the Hydra 2.0 replacement of the HdRenderDelegate". Its default implementation `_CreateRendererFromRenderDelegate` wraps a legacy delegate in a render index built over the given terminal scene index **[V hd/renderer.h:17-35; hd/rendererPlugin.h:80-200; hd/rendererPlugin.cpp:91-184]**. `UsdImagingGLEngine` already uses it: it builds merging → renderer plugins → terminal, then calls `plugin->CreateRenderer(_terminalSceneIndex, …)` **[V usdImaging/usdImagingGL/engine.cpp:1685-1740]**.

### Facts about the adapter that matter to any consumer

- **Indexed primvars are flattened by default.** `HdPrimvarSchema::GetPrimvarValue()` returns a flattening data source whenever the primvar is indexed. `GetIndexedPrimvarValue()` plus `GetIndices()` return the raw form **[V hd/primvarSchema.h:79-108; primvarSchema.cpp:133-170]**. The flattener writes `T()` for out-of-range indices and warns once ("Invalid primvar indices"). It merges the sample times of the values and the indices **[V primvarSchema.cpp:47-125]**. `HdRprim::GetPrimvar` → `delegate->Get` → `GetPrimvarValue` (flattened). `GetIndexedPrimvar` returns the unflattened values **[V hd/rprim.h:354-364; sceneIndexAdapterSceneDelegate.cpp:2232-2290]**.
- **GeomSubsets reach Hydra 1 as `HdGeomSubsets` on the mesh topology.** `_GatherGeomSubsets` walks the mesh's direct children of type `geomSubset`:
  - Only face-set subsets with a resolved material binding become `HdGeomSubset{TypeFaceSet, path, materialId, indices}`.
  - Invisible subsets become `invisibleFaces`/`invisiblePoints` on the topology.
  - Subsets with no binding are dropped **[V sceneIndexAdapterSceneDelegate.cpp:580-650]**.
- **Sample times are relative to the stage's current time.** `_SamplePrimvar` and `SampleTransform` call `GetContributingSampleTimesForInterval(start, end)` on the value data source. If that returns `false`, they use a single sample at offset 0 **[V …:2341-2440, 2488-2560]**.
- **The adapter does not override `GetScenePrimPath`.** Its header lists it as unused for emulation **[V hd/sceneIndexAdapterSceneDelegate.h:218-220]**. The base implementation only strips the delegate prefix **[V hd/sceneDelegate.cpp:342-357]**. **[inferred]** So delegates that call `GetScenePrimPath(id, instanceIndex)` get scene-index paths, not USD instance paths, when they run under scene-index emulation. HdPrman does this (§3.4). Picking instead uses `HdxPrimOriginInfo` (§4).

---

## 1. HdEmbree: the minimal CPU consumer

### 1.1 Which Hydra path

Hydra 1 Sync only, through emulation. `HdEmbreeMesh : HdMesh`; `Sync()` → `_PopulateRtMesh(sceneDelegate, …, dirtyBits)` **[V Embree/mesh.cpp:119-145]**. The delegate does not override `SetTerminalSceneIndex` or `Update` (grep finds neither in Embree/).

Supported types:
- Rprims: `mesh` only.
- Sprims: `camera`, `extComputation`, and five light types.
- Bprims: `renderBuffer`.

**[V Embree/renderDelegate.cpp:30-49]**

### 1.2 Scene index plugins

One plugin, `HdEmbree_ImplicitSurfaceSceneIndexPlugin`: phase 0, `InsertionOrderAtStart`. It configures `HdsiImplicitSurfaceSceneIndex` with `toMesh` for sphere, cube, cone, cylinder, capsule and plane **[V Embree/implicitSurfaceSceneIndexPlugin.cpp:30-72; plugInfo.json]**.

### 1.3 Mesh and primvar pipeline

The steps, in order, from **[V Embree/mesh.cpp]**:

1. **Pull (lines 563-616).**
   - Points come from `sceneDelegate->Get(id, points)` as `VtVec3fArray`, or from computed primvars through `HdExtComputationUtils::GetComputedPrimvarValues` (428-478).
   - Topology comes from `GetMeshTopology`, preserving the refine level and subdiv tags. Subdiv tags are re-read only when `refineLevel > 0`.
   - Also read: transform, visibility, cull style, double-sided.
   - Other primvars are cached as `{VtValue, interpolation}` per dirty primvar, via `GetPrimvar`, which is the flattened value. The cache only adds and updates entries, because "hydra doesn't have a good way of communicating changes in the set of primvars" (396-426).
2. **Decide refinement (619-650).**
   - Refine only if the repr is `Surf`, the scheme is not `none`, and `refineLevel > 0`.
   - Smooth normals are computed only if flat shading is off, the scheme is not `none` or `bilinear`, and there are no authored `normals`.
3. **Build geometry (655-722).**
   - Refined meshes become an Embree subdiv mesh: faces, indices and holes are shared buffers, and edge creases are unrolled from Hydra's compact crease encoding. If the corner indices and weights differ in length, it warns and drops the vertex creases (213-360).
   - Otherwise it triangulates with **`HdMeshUtil::ComputeTriangleIndices(&tris, &primitiveParams)`** (362-393).
4. **Smooth normals (766-786).**
   - `Hd_VertexAdjacency::BuildAdjacencyTable(&topology)`, then `Hd_SmoothNormals::ComputeSmoothNormals(&adj, nPoints, points)`.
5. **Primvar samplers by interpolation (480-549).**
   - Constant: one value.
   - Uniform: indexed through `primitiveParams` with `HdMeshUtil::DecodeFaceIndexFromCoarseFaceParam` **[V Embree/meshSamplers.cpp ~56-70]**.
   - Vertex and varying: triangle corner lookups.
   - Face-varying: **`HdMeshUtil::ComputeTriangulatedFaceVaryingPrimvar`**, which reports a coding error on failure **[V meshSamplers.cpp ~110-125]**. Face-varying on refined meshes is unsupported and warns (528-534).
   - Samplers check bounds before reading **[V Embree/sampler.cpp ~18-20]**.
6. **GeomSubsets and materials:** none. Embree has no material sprim and never reads `GetGeomSubsets`.

### 1.4 Instancing

- Each mesh owns a prototype `RTCScene` and creates one Embree instance per entry returned by `ComputeInstanceTransforms`. It combines `_transform * instanceXf` (mesh.cpp:838-914).
- It calls `HdInstancer::_SyncInstancerAndParents` itself (848-849); the source comment notes the render index should do this.
- `HdEmbreeInstancer::ComputeInstanceTransforms(protoId)` **[V Embree/instancer.cpp:80-191]**:
  1. Starts from `GetInstancerTransform`.
  2. Pre-multiplies `hydra:instanceTranslations`, `…Rotations` (quaternion), `…Scales` and `…Transforms`, sampled at each `GetInstanceIndices(instancerId, protoId)` entry.
  3. **Recurses into the parent instancer** with `parent->ComputeInstanceTransforms(GetId())` and forms the Cartesian product `final[i*n + j] = xf[j] * parentXf[i]`.
- So nesting is fully **flattened** into one level, with the inner index varying fastest. An invisible instancer returns no instances.
- The dev branch changes only primvar storage (`VtValue` instead of `HdVtBufferSource*`) **[D Embree/instancer.cpp diff]**.
- Picking maps hits back to (geometry, instanceId), where `instanceId` is the flattened index **[V Embree/context.h:53; renderer.cpp:867-877]**.

### 1.5 Change processing, unsupported prims, threading, errors

- **Changes.** Dirty bits only. Topology or refine changes recreate the prototype mesh. Point changes refit the BVH. Instancer or transform changes resize and update instances. No time samples: one time step (`rtcSetGeometryTimeStepCount(...,1)`).
- **Unsupported prims.** Types outside the supported lists never become rprims and are skipped silently by the adapter (§0). `CreateRprim` reports `TF_CODING_ERROR` only for types it claimed to support but cannot build **[V renderDelegate.cpp:320-327]**.
- **Threading.** Rprim Sync runs in parallel (§0). The resource registry is guarded by a mutex **[V renderDelegate.cpp:51,175-186]**.
- **Malformed data.**
  - It relies on `HdMeshUtil` for triangulation; that code warns and writes degenerate triangles (§5).
  - It checks bounds when sampling primvars.
  - It does not validate the topology.

---

## 2. Storm (`hdStorm` plugin + `hdSt`)

### 2.1 Which Hydra path

Hydra 1 Sync through emulation, with heavy GPU-side processing.
- `hdStorm/rendererPlugin.cpp` only creates `HdStRenderDelegate`. It reports `IsSupported` (requires a GPU and Hgi) and `GetSceneIndexInputArgs` (`motionBlurSupport=false`, `cameraMotionBlurSupport=true`) **[V pxr/imaging/plugin/hdStorm/rendererPlugin.cpp]**.
- Supported rprims: `mesh`, `basisCurves`, `points`, `volume`. Sprims: `camera`, `drawTarget`, `extComputation`, `material`, the light types, and `imageShader` **[V hdSt/renderDelegate.cpp:62-84]**.
- Delegate info: binding purpose `preview`; material render contexts `glslfx`, plus `mtlx` when MaterialX is built; `isPrimvarFilteringNeeded=true`; `isCoordSysSupported=false` **[V hdSt/renderDelegate.cpp:623-641]**.

### 2.2 Scene index plugins (`loadWithRenderer: "GL"`)

| Plugin | Phase / order | Purpose | Non-render consumer? |
|---|---|---|---|
| `HdSt_ImplicitSurfaceSceneIndexPlugin` → `HdsiImplicitSurfaceSceneIndex` (all six implicits → mesh) | 0 / start | implicit → mesh | **Yes** |
| `HdSt_NurbsApproximatingSceneIndexPlugin` → `HdsiNurbsApproximatingSceneIndex` | 0 / start | NURBS patch/curve approximation (its plugInfo displayName "resolve terminal names" is a copy-paste error) | **Yes** (with an approximation diagnostic) |
| `HdSt_TetMeshConversionSceneIndexPlugin` → `HdsiTetMeshConversionSceneIndex` | 0 / start | tet mesh → triangle mesh | Probably |
| `HdSt_MaterialBindingResolvingSceneIndexPlugin` → `HdsiMaterialBindingResolvingSceneIndex(purposes={preview, allPurpose}, dst=allPurpose)` | 0 / start | picks the binding purpose | Yes (choose the purpose deliberately) |
| `HdSt_NodeIdentifierResolvingSceneIndexPlugin` → `HdSiNodeIdentifierResolvingSceneIndex` | 0 / start | resolves nodeIdentifier from glslfx `sourceAsset` | Maybe (for sourceAsset shaders) |
| `HdSt_VelocityMotionResolvingSceneIndexPlugin` → `HdsiVelocityMotionResolvingSceneIndex(fps 24)` | 0 / end | velocity → points across the shutter | No (it changes points at offsets ≠ 0) |
| `HdSt_RenderPassPruneSceneIndexPlugin` | 1 / start | render-pass prune rules | No |
| `HdSt_MaterialPrimvarTransferSceneIndexPlugin` → `HdsiMaterialPrimvarTransferSceneIndex` | 3 / start | copies primvars authored on the material onto bound gprims | **Yes** |
| `HdSt_RenderPassVisibilitySceneIndexPlugin` | 4 / start | render-pass visibility | No |
| `HdSt_DependencySceneIndexPlugin` | 100 / start | declares Storm dependencies (material bindings → material, …) for forwarding | Pattern only |
| `HdSt_UnboundMaterialPruningSceneIndexPlugin` → `HdsiUnboundMaterialPruningSceneIndex` | 900 / start | removes unbound materials | Maybe (cheaper) |
| `HdSt_DependencyForwardingSceneIndexPlugin` → `HdDependencyForwardingSceneIndex` | 1000 / end | forwards dirties along `__dependencies` | **Yes**, for incremental refresh |

Sources: **[V hdSt/*SceneIndexPlugin.cpp registration blocks; hdSt/plugInfo.json; implicitSurfaceSceneIndexPlugin.cpp:59-73; materialBindingResolvingSceneIndexPlugin.cpp:46-55; dependencySceneIndexPlugin.cpp:44-56]**.

Two kinds of plugin apply to every renderer (they register with an empty renderer name):
- `HdGpSceneIndexPlugin`, only when `HDGP_INCLUDE_DEFAULT_RESOLVER` is set **[V hdGp/sceneIndexPlugin.cpp:25-41]**.
- `UsdImagingGLEngine`'s per-instance "app scene indices" (scene globals, dome-light camera visibility, scene material pruning) **[V usdImagingGL/engine.cpp:150-205]**.

Also, `UsdImagingCreateSceneIndices` appends every `UsdImagingSceneIndexPlugin` before the selection scene index **[V usdImaging/sceneIndices.cpp:66-76,288]**. One of these is `UsdSkelImagingResolvingSceneIndexPlugin` **[V usdSkelImaging/plugInfo.json:42-46]**, and it is present in Blender 5.2.2's `lib/usd/usdSkelImaging` plugInfo.

**[inferred]** So the bridge's chain should already include skeleton resolution when the plugin is registered. This is untested.

### 2.3 Meshes

- **Topology.** It reads `HdMeshTopology` and the display style (refine level, flat shading).
  - `scheme == none` forces refine level 0.
  - **Loop with refinement on non-triangle faces** warns through `HF_VALIDATION_WARN` and forces level 0, "since asking PxOsd to loop-subdivide a non-triangular mesh is unsupported and may crash" **[V hdSt/mesh.cpp:600-630]**.
  - It then builds `HdSt_MeshTopology` (uniform or adaptive refinement; quads triangulated or not) **[V mesh.cpp:631-656]**.
- **GeomSubsets.** One **draw item per subset**, each with its own material shader `HdStGetMaterialNetworkShader(..., geomSubset.materialId)` **[V mesh.cpp:440-480]**. `HdSt_MeshTopology::SanitizeGeomSubsets` **[V hdSt/meshTopology.cpp:310-370]**:
  - drops subsets with empty indices or an empty material,
  - warns and drops face indices `>= numFaces`,
  - warns on faces shared between subsets,
  - collects **non-subset faces** into `_nonSubsetFaces`, drawn with the prim's own material.
  - **[inferred] Gap:** negative indices are not rejected. `unusedFaces[index]` with `index < 0` is out-of-bounds access. A consumer must check `0 <= i < numFaces` itself.
- **Primvars.**
  - Vertex and varying: size is checked against `numPoints`. If `points` is too short, the whole prim's vertex buffer is dropped ("Skipping prim due to insufficient data"). Other short primvars are skipped. Long ones warn and are truncated **[V mesh.cpp:1480-1525]**.
  - Face-varying: when refining, the **indexed** form (`GetIndexedPrimvar`) is kept and its indices tracked per channel by `_fvarTopologyTracker`; empty or short indices warn and skip **[V mesh.cpp:269-345]**. Otherwise it uses the flattened value and requires `size == numFaceVaryings`, else warns and skips **[V mesh.cpp:2080-2125]**.
  - Triangulation, quadrangulation and refinement of primvars go through `HdSt_MeshTopology` computations built on `HdMeshUtil` (GPU or CPU) **[V mesh.cpp:1136-1260]**.
- **Normals.** Authored normals win; "normals specified as both computed and authored" warns and skips the authored ones (1527-1550). Otherwise it computes smooth or flat normals, or limit normals for adaptive refinement.

### 2.4 Instancing

- `HdStInstancer::_SyncPrimvars` uploads instance-rate primvars, including `hydra:instanceTransforms` as double or float matrices **[V hdSt/instancer.cpp:84-140]**.
- `_GetInstanceIndices` **walks up the parent instancers**, collecting one index array per level. It sanity-checks each index against the instance-primvar element count; on a bad index it warns and replaces the list with `[0]` **[V instancer.cpp:210-265]**.
- `GetInstanceIndices` builds the **Cartesian product**, prefixed with a global index, innermost level fastest (`[<0>,0,3,7, <1>,1,3,7, …]`) **[V instancer.cpp:268-320]**. The GPU composes the transforms per level. Every instance is drawn from one draw item, so prototype sharing is by draw item.

### 2.5 Materials

- `HdStMaterial::Sync` returns early unless `DirtyResource|DirtyParams` is set. Then it **re-reads the whole network**: `sceneDelegate->GetMaterialResource(id)` → `HdMaterialNetworkMap` → `HdStMaterialNetwork::ProcessMaterialNetwork`. It falls back to a fallback glslfx when no source results **[V hdSt/material.cpp:185-230]**. There is no incremental diff of parameters.
- In the adapter, `GetMaterialResource` picks the network with `HdMaterialSchema::GetMaterialNetwork(renderDelegate->GetMaterialRenderContexts())`. That call takes the first matching context and falls back to the universal context, which is where `UsdPreviewSurface` lives **[V sceneIndexAdapterSceneDelegate.cpp:1325-1346; hd/materialSchema.h:159-172]**.
- `ProcessMaterialNetwork` **[V hdSt/materialNetwork.cpp:1156-1215]**:
  1. `HdConvertToHdMaterialNetwork2` (and detects whether the network is a volume).
  2. Selects the `surface` or `volume` terminal.
  3. Runs the MaterialX filter `HdSt_ApplyMaterialXFilter` when the terminal is MaterialX.
  4. Generates glslfx code and gathers parameters, primvars and textures (`_GatherMaterialParams`).
  5. Derives the material tag (translucent/masked) from `opacityThreshold`, a connection to `opacity`, or an authored `opacity` (66-110).

### 2.6 Change processing, unsupported prims, threading, errors

- **Changes.** Dirty bits through the adapter, plus custom bits (for example `DirtyFlatNormals`). There is no motion blur (`motionBlurSupport=false`), so it uses one sample at the current time.
- **Unsupported prims.** Prims with no Storm type are silently ignored by the adapter.
- **Threading.** Rprim Sync is parallel. GPU resources are committed afterwards.
- **Errors.** It uses `HF_VALIDATION_WARN` and `TF_WARN` widely. Data is skipped or truncated rather than failing. Storm itself never calls `PxOsdMeshTopology::Validate` (grep over hd, hdSt, hdsi, plugins and hdPrman: no calls).

---

## 3. HdPrman

### 3.1 Which Hydra path: two coexisting paths

**Path A, the default: Hydra 1 Sync through emulation.**
- `HdPrman_Gprim<BASE>::Sync`:
  - samples transforms with `SampleTransform(id, shutterOpen, shutterClose)` (motion blur);
  - resolves the material from `DirtyMaterialId`;
  - calls `_ConvertGeometry` to fill an `RtPrimVarList` and the subsets;
  - creates or modifies **riley geometry prototypes**, one per subset, or one if there are no subsets;
  - then creates **riley geometry instances**, or defers to `HdPrmanInstancer::Populate` when instanced.

  **[V HdPrman/gprim.h:140-525]**
- Parallel prim sync is enabled only for camera, coordSys, displayFilter, lightFilter, material and sampleFilter, through `IsParallelSyncEnabled`. Volume, lights, integrator and render settings are excluded "due to interaction with HdChangeTracker state" **[V HdPrman/renderDelegate.cpp:86-92, 920-935]**.

**Path B, experimental and off by default: native scene-index observer ("riley prims").**
- Gated by `HD_PRMAN_EXPERIMENTAL_RILEY_SCENE_INDEX_OBSERVER=false`, documented as "the incomplete pure Hydra 2.0 implementation" **[V HdPrman/sceneIndexObserverApi.cpp:15-22; same in D]**.
- `SetTerminalSceneIndex` builds `_RileySceneIndices` **[V renderDelegate.cpp:94-190, 894-918]**:
  - **`HdsiPrimTypeNoticeBatchingSceneIndex`** over the terminal scene index holds notices until `Flush()`. It merges duplicates and orders them by a type-priority functor: globals first, then shaders, materials and coordsys, then geometry prototypes, then instances **[V HdPrman/rileyPrimFactory.cpp:50-110; hdsi/primTypeNoticeBatchingSceneIndex.h:28-46]**.
  - **`HdsiPrimManagingSceneIndexObserver`** with an `HdPrman_RileyPrimFactory` creates one C++ object per riley prim type. `Update()` → `Flush()`.
- `HdPrman_RileyConversionSceneIndexPlugin` (phase 101) **converts Hydra prims into `riley:*` prim types inside the scene index**. In v26.03 and dev it converts **only `sphere`**, into a `riley:geometryPrototype` at the same path plus a child `riley:geometryInstance` **[V HdPrman/rileyConversionSceneIndexPlugin.cpp:186-260, 316, 341; D HdPrman/rileyConversionSceneIndex.cpp (only `sphere` matches)]**. Meshes still go through Path A, and the two paths run together.
- Each managed prim **[V HdPrman/rileyGeometryInstancePrim.cpp:58-135]**:
  - reads its own schema in the constructor and calls `Create*`;
  - in `_Dirty(entry)` re-reads only the fields whose locator `entry.dirtyLocators.Intersects(...)`, then calls `Modify*`;
  - resolves references to other managed prims with `observer->GetTypedPrim<T>(path)`, holding a `shared_ptr` so that dependencies outlive their users **[V HdPrman/rileyIds.h:63,119]**.
- In dev, the three riley plugins are folded into a single `HdPrman_Renderer2SceneIndexPlugin`; still env-gated **[D HdPrman/renderer2SceneIndexPlugin.cpp:30-55]**.

**How data is read in each path.**
- Path A: through the scene-delegate API. That means `SamplePrimvar`, which uses **flattened** primvars because no indices argument is passed (`samples.Resample(time)` for everything except P) **[V HdPrman/renderParam.cpp:812-880]**; `GetMeshTopology`; `SampleTransform`; `GetMaterialResource`.
- Path B: directly from the data sources of the `riley:*` schemas produced by the conversion scene index.

### 3.2 Scene index plugins (registered for each `HdPrman_GetPluginDisplayNames()` entry)

| Plugin | Phase | Purpose | Non-render consumer? |
|---|---|---|---|
| ImplicitSurface → `HdsiImplicitSurfaceSceneIndex` | 0 | RIS: cone/cylinder `axisToTransform` (native quadrics), cube/capsule/plane `toMesh`; XPU or `HDPRMAN_TESSELLATE_IMPLICIT_SURFACES`: all `toMesh` **[V implicitSurfaceSceneIndexPlugin.cpp:75-162]** | **Yes** (all `toMesh`) |
| TetMeshConversion | 0 | tet → mesh | Probably |
| ExtComputationPrimvarPruning → `HdSiExtComputationPrimvarPruningSceneIndex` | 0 | evaluates ext computations into plain primvars | **Yes**, if ext computations appear (legacy skinning path) |
| Retesselation | 0 (not XPU) | dirties geometry on displacement edits | No |
| RenderPassPrune, RenderSettingsFiltering | 1 | render passes and settings | No |
| PreviewSurfacePrimvars | 2 | adds primvars needed by preview surfaces | Maybe |
| VelocityMotionResolving | 2 / end | velocity motion | No (only for interval sampling) |
| MotionBlur | 3 | limits samples per prim and attribute (`ri:object:mblur`, `geosamples`, `xformsamples`) **[V motionBlurSceneIndexPlugin.cpp:20-90, 270-370]** | No |
| PinnedCurveExpanding → `HdsiPinnedCurveExpandingSceneIndex` | 3 / end | pinned curves → explicit end points | Only if curves are supported |
| LightLinking (env, default on) | 4 | light linking | No |
| Matfilt: PreviewMaterial and MaterialX (`NodeTranslation`), VirtualStruct (`ConnectionResolve`), NodeIdentifier (`NodeIdResolution`) | matfilt order (< 200) | translate UsdPreviewSurface and MaterialX into Pxr nodes; resolve vstructs **[V matfiltSceneIndexPlugins.cpp:77-111]** | Pattern only (the project translates to Principled itself) |
| RileyConversion | 101 | Path B (env) | Pattern |
| DependencyScene | ≥100 | declares dependencies | Pattern |
| RenderPassVisibilityAndMatte | 113 | render passes | No |
| MeshLightResolving, PortalLightResolving, UpdateObjectSettings | 115 | lights, object settings | No |
| MaterialPrimvarTransfer | max(3, 200) / end | after matfilt | **Yes** |
| CoordSysPrim → `HdsiCoordSysPrimSceneIndex` | 900 / end | makes coordSys bindings into coordSys prims | Maybe (texture projection) |
| RileyGlobals | 950 | riley options | No |
| WorldOffset | 999 | camera-relative world offset | No |
| DependencyForwarding, RenderTerminalOutputInvalidating | 1000 / end | dirty forwarding | **Yes** (forwarding) |

Dev adds plugins for display and rendering color space, fallback materials, particle-field conversion, render terminal time sampling, an id-assigning plugin (phase 115, §3.4), and compile-time `static_assert`s on phase ordering (ext computations < velocity < motion blur) **[D HdPrman/sceneIndexPluginOrdering.cpp; directory diff]**.

### 3.3 Meshes and GeomSubsets

`HdPrman_Mesh::_ConvertGeometry` **[V HdPrman/mesh.cpp:81-330]**:
- **Subsets.**
  - It takes `topology.GetGeomSubsets()` and marks used faces.
  - It **appends a synthetic subset for the unused faces**, with an empty material meaning the prim's material (100-125).
  - Out-of-range indices are guarded only by `TF_VERIFY(index < numFaces)`. **[inferred]** Negative indices are not checked, the same gap as Storm.
- **Scheme and holes.** The scheme maps to `Ri:scheme`. Holes are the union of `invisibleFaces` and authored `holeIndices`, passed as subdivision `hole` tags; a `none` scheme with holes switches to bilinear (~160-200). Creases, corners and interpolation rules are converted from `PxOsdSubdivTags`.
- **Primvars.** `HdPrman_ConvertPrimvars(sceneDelegate, id, primvars, nFaces, nPoints, nPoints, nFaceVaryings, shutter)`:
  - checks each non-constant primvar's array size against the size for its interpolation, and `TF_WARN` + skips on mismatch;
  - warns on unhandled types **[V renderParam.cpp:853-880]**.
- **Subset prototypes.** `gprim.h` gives **each subset its own riley geometry prototype** carrying the **full mesh primvars plus `k_shade_faceset = subset indices`**. A subset with no material gets the prim's material **[V gprim.h:297-370]**. **[inferred]** This duplicates geometry per subset, which RenderMan can afford because a faceset restricts shading.

### 3.4 Instancing

`HdPrmanInstancer` **[V HdPrman/instancer.cpp; instancer.h]**:
- **Nested instancing is native.** Each nested instancer turns its prototypes into a **riley geometry prototype group**, and the parent instances that group. Up to `HDPRMAN_MAX_SUPPORTED_NESTING_DEPTH = 4`; deeper levels pass `_InstanceData` lists up to be multiplied (flattened). It can be disabled with `HD_PRMAN_DISABLE_NESTED_INSTANCING` **[V instancer.cpp:73-76, 932-975]**.
- **"FlattenData".** Instance parameters riley does not support inside groups (visibility, light-linking categories) are moved out and flattened onto the outermost instances **[V instancer.h:185-330]**.
- **Transforms.** Sampled over the shutter: `SampleInstancerTransform`, plus `SamplePrimvar` of `hydra:instanceTransforms/Translations/Rotations/Scales`. The instancer's own transform is included only at depth 0; a parent applies it otherwise **[V instancer.cpp:595-700]**.
- **Threading.** Populate can run concurrently from several prototypes; it uses `tbb::spin_rw_mutex` and a concurrent map **[V instancer.cpp:917-927, 1698-1760; instancer.h:337-440]**.
- **Instance → path.** `GetScenePrimPath(prototypePath, i)` names the riley instance for stats **[V instancer.cpp:1308]**. Per §0 this does not give USD instance paths under emulation. **[inferred]**
- **Dev only (PXR_VERSION ≥ 2605, so not in v26.03): `HdPrman_IdSceneIndex`** writes stable identifiers as primvars **[D HdPrman/idSceneIndexPlugin.cpp:66-186, 316-330]**:
  - prototype prims (those with `instancedBy` but no `instancerTopology`) get `user:primOrigin = primOrigin.scenePath`;
  - native instancers (`instanceLocations` present) get an `instanceLocations` primvar holding each instance prim's `primOrigin.scenePath`;
  - point instancers get synthesized `"<originPath>[i]"` names.
  - `HdPrman_IdMap` maps a stable u64 id (split into `identifier:id` and `id2`) to `{name, primId, instanceId}` for picking from AOVs **[D HdPrman/idMap.h:18-60]**.

  This is the closest prior art to Proscenium's need for durable source identity per instance.

### 3.5 Materials

- Path A: `HdPrman_Material::Sync` reads `GetMaterialResource`. The networks were already transformed by the matfilt scene indices, which translate UsdPreviewSurface and MaterialX into Pxr nodes and resolve vstructs. It then converts to riley shading nodes. Material binding is per prim (`DirtyMaterialId`) and per subset (`HdGeomSubset::materialId`) **[V gprim.h:200-222, 337-345]**.
- The matfilt scene indices use the `HdMaterialFilteringSceneIndexBase` / `HdMaterialNetworkInterface` pattern **[V hd/materialFilteringSceneIndexBase.h; hd/dataSourceMaterialNetworkInterface.h]**.
- **[inferred]** Parameter edits arrive as dirty locators under `material`, and the whole network is re-processed.

### 3.6 Time and motion

- Path A gets sample times from `SamplePrimvar` and `SampleTransform` with the render param's shutter interval. The adapter turns those into `GetContributingSampleTimesForInterval` (§0).
- The MotionBlur scene index clamps the samples per attribute. Every primvar except P is resampled at a single time **[V renderParam.cpp:833-840]**.
- Path B riley prims receive the shutter interval through `HdPrman_RileyTransform(schema.GetXform(), shutter)` **[V rileyGeometryInstancePrim.cpp ~70]**.

### 3.7 Unsupported prims, errors

- **Unsupported prims.** Silently skipped by the adapter. Path B's factory returns null for unknown types, and the observer stores nothing **[V hdsi/primManagingSceneIndexObserver.cpp:96-117]**.
- **Errors.** Size checks with `TF_WARN` and skip. `TF_VERIFY` on subset indices. A riley creation failure warns **[V gprim.h ~512]**. Exceptions from RenderMan are routed through `xcpt.cpp`.

---

## 4. The instance reverse-mapping mechanism Hydra offers

The project's need, (instancer, instance index) → the USD instance-root chain, is exactly what **`HdxPrimOriginInfo`** implements for picking, using only the **terminal scene index**.

**The data model, in the scene-index schemas.**
- `HdInstancedBySchema` on a prototype prim lists the instancer(s) that instance it.
- `HdInstancerTopologySchema` on the instancer has four fields **[V hd/instancerTopologySchema.h:49-132]**:
  - `prototypes` (paths),
  - `instanceIndices` (an int array per prototype),
  - `mask`,
  - `instanceLocations`, set only for **implicit (USD native) instancing**: the scene-index paths of the instance prims.
- `ComputeInstanceIndicesForProto(path)` matches every prototype that prefixes `path`, applies the mask, and returns the instance indices that draw it **[V instancerTopologySchema.cpp:35-75]**.
- `HdInstanceSchema` on each native-instance prim is the inverse link: `{instancer, prototypeIndex, instanceIndex}` **[V hd/instanceSchema.h:47-103]**.
- `HdPrimOriginSchema.scenePath` holds the USD path. For prims inside a USD prototype it is **prototype-relative**, built by UsdImaging from `_ComputePrototypeRelativePath` **[V usdImaging/dataSourcePrim.cpp:540-555]**. It is wrapped in `OriginPath` so prefixing scene indices leave it unchanged **[V hd/primOriginSchema.h:68-95]**.

**The algorithm, `_FromPickHitWithCache` [V hdx/pickTask.cpp:1053-1210].** Input: a hit `{objectId = scene-index path of the rprim, instanceIndex = flattened index}`.
1. Read `primOrigin` from the prim.
2. Loop:
   - a. instancer = `instancedBy[0]`;
   - b. `idx = ComputeInstanceIndicesForProto(currentPath)`, `n = idx.size()`;
   - c. `i = instanceIndex % n; instanceIndex /= n`, so **the innermost level varies fastest**, matching Storm's Cartesian product and Embree's flattening;
   - d. `instanceId = idx[i]`;
   - e. if `instanceLocations` exists, `instanceSceneIndexPath = instanceLocations[instanceId]` and its `primOrigin`;
   - f. move up to the instancer.
3. Reverse the list so the outermost level comes first.

**Composing the USD path, `GetFullPath` [V pickTask.cpp:1264-1305].** Fold `primOrigin.scenePath` across the instance contexts and then the prim. An absolute path replaces the accumulated path; a relative one appends to it.
- The outermost native instance gives an absolute USD path (outside any prototype).
- Inner ones give prototype-relative paths.
- The result is the full USD instance-proxy path, for example `/World/A/ProtoChild/B/Mesh`.

`ComputeInstancerContext` builds the legacy `HdInstancerContext` (instancer, instance id) pairs **[V pickTask.cpp:1305+; pickTask.h:115-215]**. `FromPickHits` caches instancer lookups across many hits.

**Availability.** `HdxPrimOriginInfo::FromPickHit`, `GetFullPath`, `HdInstancerTopologySchema::ComputeInstanceIndicesForProto` and `HdPrimOriginSchema::GetOriginPath` are all exported from Blender 5.2.2's `libusd_ms` **[Blender 5.2.2 nm]**. `FromPickHit(HdSceneIndexBaseRefPtr, HdxPickHit)` needs no render index **[V pickTask.h:165-200]**.

**Using it for Proscenium [inferred].** No picking is needed. While traversing the terminal scene index, for each prototype prim:
1. Walk `instancedBy` upward.
2. Expand instance indices level by level, using `ComputeInstanceIndicesForProto` once per (instancer, prototype).
3. Record `instanceLocations[instanceId]` and each level's `primOrigin`.

This gives, for each instance tuple, the chain of USD instance roots, built with the same rules as `GetFullPath`. You can either synthesize an `HdxPickHit{objectId, instanceIndex}` and call `FromPickHits` (cached), or reimplement the ~60 lines.
- **Point instancers have no `instanceLocations`.** Identity there is (instancer USD path, instance index), the same choice dev hdPrman makes with `"<path>[i]"`.
- The forward direction, from a USD path to scene-index paths including inside instances, is `UsdImagingSelectionSceneIndex` (milestone background). It is exported **[Blender 5.2.2 nm]**.

**Caveat [inferred, needs a probe].** Native-instance **aggregation** groups instances by inherited state (bindings, visibility, …). Prims under different aggregated instancers can therefore come from the same USD prototype. Durable identity should key on the **composed path** from `GetFullPath`, not on scene-index prototype paths, which are synthesized (`UsdNiPropagatedPrototypes/...`) and can change when grouping changes.

---

## 5. Reusable helpers (public in v26.03, exported by Blender 5.2.2)

| Helper | What it gives a consumer | Evidence |
|---|---|---|
| `PxOsdMeshTopology::Validate()` → `PxOsdMeshTopologyValidation` (codes: invalid face-vertex counts element, invalid indices element or size, invalid hole index, crease and corner size/element/negative weights, invalid scheme, orientation, interpolation rules) | **Topology validation before Blender** (no delegate calls it) | **[V pxOsd/meshTopology.h:192-209; meshTopologyValidation.h:48-66]**; exported |
| `HdMeshTopology::GetPxOsdMeshTopology()`, `GetGeomSubsets`, `GetInvisibleFaces`, … | topology access | **[V hd/meshTopology.h:69]** |
| `HdMeshUtil::ComputeTriangleIndices` / `ComputeQuadIndices` / `ComputeTriQuadIndices` / `ComputeTriangulatedFaceVaryingPrimvar` / `ComputeQuadrangulatedPrimvar` / `EnumerateEdges` / `DecodeFaceIndexFromCoarseFaceParam`, `HdMeshEdgeIndexTable` | triangulation with face mapping; edge enumeration (useful for crease edges into Blender) | **[V hd/meshUtil.h:77-215, 313-336]**; exported |
| `Hd_VertexAdjacency::BuildAdjacencyTable`, `Hd_SmoothNormals::ComputeSmoothNormals` | smooth normals (Blender computes its own, so rarely needed) | **[V hd/vertexAdjacency.h:58-72; smoothNormals.h:29-52]**; exported |
| `HdPrimvarSchema::GetIndexedPrimvarValue` / `GetIndices` / `GetFlattenedPrimvarValue` | keep indexed primvars (Blender UV and corner domains can use indices) or flatten | **[V hd/primvarSchema.h:79-108]** |
| `HdSceneIndexPrimView` | full traversal | exported |
| `HdDirtyBitsTranslator` | locator ↔ dirty-bit mapping, a ready-made list of which locators matter for each prim type | **[V hd/dirtyBitsTranslator.h:21-45]**; exported |
| `HdsiPrimManagingSceneIndexObserver` (+ `PrimFactoryBase`/`PrimBase`) | per-prim objects created, dirtied and removed from notices, with a `GetTypedPrim` dependency lookup | **[V hdsi/primManagingSceneIndexObserver.h; .cpp:45-172]**; exported |
| `HdsiPrimTypeNoticeBatchingSceneIndex` | holds and merges notices until `Flush()`, ordered by type priority | **[V hdsi/primTypeNoticeBatchingSceneIndex.h:28-110]**; exported |
| `HdDependencyForwardingSceneIndex` + `HdDependenciesSchema` | forwards a material edit to bound prims, etc. | exported |
| `HdsiImplicitSurfaceSceneIndex`, `HdsiNurbsApproximatingSceneIndex`, `HdsiTetMeshConversionSceneIndex`, `HdsiPinnedCurveExpandingSceneIndex`, `HdsiMaterialPrimvarTransferSceneIndex`, `HdsiMaterialBindingResolvingSceneIndex`, `HdSiExtComputationPrimvarPruningSceneIndex`, `HdsiCoordSysPrimSceneIndex`, `HdsiVelocityMotionResolvingSceneIndex` | filters listed in §2.2 and §3.2 | `New` symbols found **[Blender 5.2.2 nm]** (CoordSys and DependencyForwarding `New` are inline; their class symbols are exported) |
| `HdConvertToHdMaterialNetwork2`, `HdMaterialSchema::GetMaterialNetwork(contexts)`, `HdDataSourceMaterialNetworkInterface`, `HdMaterialFilteringSceneIndexBase`, `HdUtils::ConvertHdMaterialNetworkToHdMaterialSchema` | material network extraction and filtering | **[V hd/material.h:180-184; materialSchema.h:159-172; hd/utils.h:164-178]**; exported |
| `HdGetMergedContributingSampleTimesForInterval` | merging time samples across data sources | exported |
| `HdxPrimOriginInfo` | instance reverse mapping (§4) | exported |
| `HdSceneIndexAdapterSceneDelegate` | a Hydra 1 view of any scene index, if needed for a getter such as `GetMeshTopology` with subsets | exported |

---

## 6. Time-sampled data (input to the M1b probe)

- Sample-time queries are relative to the stage scene index's current time. `UsdImagingDataSourceAttribute::GetContributingSampleTimesForInterval` returns `false` (not varying) when `!ValueMightBeTimeVarying()` or the time is not numeric. Otherwise it returns `GetTimeSamplesInInterval` plus the bracketing samples, offset by the current time **[V usdImaging/dataSourceAttribute.h:71-115]**.
- **Flattened transforms merge parent and local sample times** **[V hd/flattenedXformDataSourceProvider.cpp:31-40]**. **[inferred]** So a static mesh under an animated ancestor should report a varying `xform.matrix` in the flattened scene. That is the case the milestone asks to verify.
- Flattened indexed primvars merge the sample times of values and indices **[V hd/primvarSchema.cpp:114-123]**.
- The renderers ask over the shutter interval, and fall back to offset 0 when the answer is "not varying" **[V sceneIndexAdapterSceneDelegate.cpp:2395-2420]**.
- **[inferred]** A non-render consumer can call `GetContributingSampleTimesForInterval(-inf, +inf)`, or the stage range relative to now, on the points, xform, visibility, topology and primvar data sources to classify each value as static or animated. Data sources computed by filters, such as implicit → mesh points from a varying radius, must forward this correctly. Verify per filter.

---

## 7. Threading and safety contract

- `HdSceneIndexBase::GetPrim` and `GetChildPrimPaths` "are expected to be threadsafe". `AddObserver` and notice sending are not; some observers expect a single thread **[V hd/sceneIndex.h:71-110, 184-213]**. `HdSampledDataSource::GetValue` and the sample-time queries are expected to be threadsafe **[V hd/dataSource.h:104-170]**.
- Hydra's default rprim Sync reads the terminal scene index in parallel (§0). The adapter keeps a per-thread input-prim cache **[V sceneIndexAdapterSceneDelegate.h:222-234]**.
- **[inferred]** A parallel capture (`WorkParallelForEach` over prim paths, reading data sources) uses the same contract Hydra's own Sync relies on. Notices must still be processed on one thread, and the stage must not change during capture.
- HdPrman marks only some prim types parallel-safe because their Sync has side effects on the change tracker. A capture that only reads has no such side effects.
- `HdsiPrimManagingSceneIndexObserver` processes notices serially today; comments sketch how to parallelize creation **[V primManagingSceneIndexObserver.cpp:62-66, 96-104, 127-133]**.

---

## 8. Validation and malformed input: what Hydra does and does not catch

| Problem | Hydra behavior | Source |
|---|---|---|
| Face with < 3 vertices | `HdMeshUtil` skips it and warns "degenerated face found" | **[V hd/meshUtil.cpp:67-96]** |
| counts and indices disagree | `_FanTriangulate` checks for overrun, writes a (0,0,0) triangle, warns "numVerts and verts are inconsistent" | **[V meshUtil.cpp:28-52, 160-245]** |
| face-vertex index ≥ point count | **not checked** by HdMeshUtil, Embree or the adapter. Storm only compares primvar sizes with `numPoints` (derived from the max index) | **[inferred from V meshUtil.cpp, hdSt/mesh.cpp:1480-1525]** |
| primvar size mismatch | Storm warns, then skips or truncates; HdPrman warns and skips | **[V hdSt/mesh.cpp:1480-1525, 2110-2120; HdPrman/renderParam.cpp:853-860]** |
| indexed primvar index out of range | flattener writes `T()` and warns; Storm checks indices only for face-varying | **[V hd/primvarSchema.cpp:47-70; hdSt/mesh.cpp:295-312]** |
| GeomSubset index ≥ numFaces / duplicates | Storm drops with a warning; HdPrman `TF_VERIFY`; **negative indices unchecked in both** | **[V hdSt/meshTopology.cpp:310-370; HdPrman/mesh.cpp:105]** |
| loop subdivision on non-triangles | Storm forces refine 0 ("may crash") | **[V hdSt/mesh.cpp:618-630]** |
| instance index ≥ instance primvar count | Storm warns, replaces with `[0]` | **[V hdSt/instancer.cpp:222-240]** |
| crease or corner size mismatch | Embree drops vertex creases | **[V Embree/mesh.cpp:240-246]** |

**[inferred]** These warnings go through `TfDiagnostic`, not return values. A consumer should do its own validation before Blender:
1. `PxOsdMeshTopology::Validate()` for structure.
2. An explicit `max(faceVertexIndices) < len(points)` check.
3. Per-interpolation size checks.
4. Index-range checks for indexed primvars, subsets and instances, including negatives.

Each failure should produce a Proscenium diagnostic. Install a `TfDiagnosticMgr` delegate to capture Hydra's warnings as diagnostics too.

---

## 9. Prior art beyond the three delegates (brief)

- **OpenUSD docs.** The Hydra 2.0 getting-started guide describes scene-index consumers generally, and recommends a simple originating scene index with complex transformations done by filters [https://openusd.org/dev/api/_page__hydra__getting__started__guide.html]. It does not describe a "scene index → application data" importer.
- **Autodesk MayaHydra.** Maya → Hydra (Flow Viewport merging scene index, scene-index plugins per Maya node type). Same direction as Blender's Hydra: an application *producing* scene indices for a viewport [https://github.com/Autodesk/maya-hydra; …/doc/mayaHydraDetails.md].
- **NVIDIA Omniverse.** The Fabric Scene Delegate populates Hydra *from* Fabric. USD → Fabric population is done outside Hydra [https://docs.omniverse.nvidia.com/kit/docs/usdrt/latest/docs/fabricsd/intro.html].
- **Houdini Solaris / Karma.** Hydra for viewport and rendering; SOP import is USD-side. I found no public description of translating scene indices into SOPs [https://www.sidefx.com/docs/houdini/solaris/sop_import.html; https://www.sidefx.com/docs/hdk/_h_d_k__u_s_d_hydra.html].
- **Unreal USD importer.** Documentation shows a stage actor and importer built on USD APIs; I found no evidence it uses Hydra [https://dev.epicgames.com/documentation/en-us/unreal-engine/universal-scene-description-in-unreal-engine]. **[inferred from absence]**
- **Blender.** `render/hydra` and `io/usd/hydra` go Blender → Hydra (milestone background).
- **Closest in-tree analogues** of "scene index → native objects":
  - HdPrman Path B (filtering scene index converts to target prim types, then a prim-managing observer creates and modifies native objects);
  - `HdxPrimOriginInfo` (scene index → source identity);
  - dev `HdPrman_IdSceneIndex` (stable per-instance identity from `primOrigin` and `instanceLocations`).
- **Conclusion.** I found no public project that imports Hydra 2 scene indices into an application's native scene. **[web search, not exhaustive]**

---

## 10. Patterns for a non-render consumer

Three candidate architectures:

**(a) A render delegate with `HdRenderIndex`.** Write an `HdRenderDelegate` (e.g. "Proscenium") whose rprims capture data in `Sync`. Optionally use `HdRenderIndex::New(delegate, {}, terminalSceneIndex)`, or the v26.03 `HdRendererPlugin::CreateRenderer`.
- *Pros:* dirty bits, change tracking and parallel `SyncAll` for free. `HdInstancer` parent sync. The adapter's getters do the work: GeomSubsets assembled with bindings, `SamplePrimvar`/`SampleTransform`, `GetMaterialResource` with render-context fallback. This is the path all three delegates use, so it is proven.
- *Cons:*
  - You inherit Hydra 1 semantics: subsets without bindings are dropped and subset visibility is folded into `invisibleFaces` (§0).
  - `GetScenePrimPath` is not implemented, so instance identity still needs §4.
  - Repr, render-tag and task machinery (the delegate must still provide `CreateRenderPass` and similar).
  - Plugin-registry chains apply by renderer display name.
  - Bits are coarser than locators.
  - The Sync order (rprims before instancers resolved through the render index) and `_SyncInstancerAndParents` quirks (Embree comment) add lifecycle complexity.
  - Immutable snapshots would be assembled from mutable rprim objects.
- *Verdict:* **avoid** as the main architecture. It solves incremental update, but makes the snapshot and identity model worse.

**(b) Direct traversal of the terminal scene index plus an observer (the current bridge).**
- *Pros:* simplest. Reads locators and schemas directly, so subsets, indexed primvars, `primOrigin`, `instancerTopology` and sample times are all visible. The immutable-snapshot model fits naturally. Capture parallelizes under Hydra's thread-safety contract (§7). It has no renderer lifecycle.
- *Cons:* you write the dirty-locator → refresh mapping, instancer expansion and subset assembly yourself. Both are small: `HdDirtyBitsTranslator`'s tables are a guide, and the adapter's `_GatherGeomSubsets` (~70 lines) is a template.

**(c) A prim-managing observer (HdPrman Path B style).** `HdsiPrimTypeNoticeBatchingSceneIndex` + `HdsiPrimManagingSceneIndexObserver` with a factory of per-type "capture prims". Each holds its last evaluated record, re-reads only the fields whose locators intersect a dirty entry, and references dependencies (material, prototype) through `GetTypedPrim`.
- *Pros:*
  - A natural fit for Phase 2 incremental refresh: per-prim retained state, locator-granular updates.
  - `Flush()` gives a deterministic, deduplicated, type-ordered batch per refresh: materials before meshes before instancers, matching Blender build order.
  - Both classes are public and exported.
- *Cons:*
  - Serial today.
  - The managed objects are mutable state, so a snapshot must copy them out or share them.
  - The pattern is labeled experimental and incomplete in HdPrman, though the hdsi classes themselves are general.
  - Initial population is a serial `HdSceneIndexPrimView` loop.

**Recommendation [inferred, opinionated].**
- Phase 1: **(b)** — a parallel full traversal into an immutable snapshot.
- Phase 2: **(c)**, specifically:
  - an `HdsiPrimTypeNoticeBatchingSceneIndex` at the end of the chain, flushed once per refresh;
  - an observer that turns the flushed notices into a *change set* (added, removed, and dirtied paths with locators) used to re-capture only the affected prims and build the next snapshot by structural sharing.

  `HdsiPrimManagingSceneIndexObserver` is optional. Its main value is that per-prim retained records make "unchanged refresh → empty plan" cheap.

Do not adopt (a).

**Copy these:**
1. **Build the filter chain explicitly in C++** instead of through `HdSceneIndexPluginRegistry` renderer names. That keeps the chain reproducible and free of plugin-load surprises: app scene indices, HdGp env gating, and Storm's GL-only filters.
   - Suggested order after `UsdImagingCreateSceneIndices(addDrawModeSceneIndex=false)`:
     1. `HdSiExtComputationPrimvarPruningSceneIndex`;
     2. `HdsiImplicitSurfaceSceneIndex` (all `toMesh`, as Storm and Embree do);
     3. `HdsiNurbsApproximatingSceneIndex`;
     4. optionally `HdsiTetMeshConversionSceneIndex`;
     5. `HdsiMaterialBindingResolvingSceneIndex` (purposes `{full, allPurpose}` or `{preview, allPurpose}`, a deliberate choice; Storm uses preview);
     6. `HdsiMaterialPrimvarTransferSceneIndex`;
     7. the project's dependency declarations + `HdDependencyForwardingSceneIndex`;
     8. `HdFlatteningSceneIndex`;
     9. the notice-batching scene index.
   - Leave out velocity and motion blur, render-pass, light, and matfilt-to-renderer filters.
   - Check whether `UsdSkelImagingResolvingSceneIndexPlugin` is already in the chain; it is registered in Blender 5.2.2's plugInfo.
2. **Read indexed primvars un-flattened** (`GetIndexedPrimvarValue` + `GetIndices`) when the Blender target can use them, and flatten explicitly otherwise. Do not rely on `GetPrimvarValue`, which flattens silently and writes `T()` for bad indices.
3. **Subsets: Storm's sanitization rules plus a negative-index check.** Explicitly represent non-subset faces with the prim's material, as both Storm (`_nonSubsetFaces`) and HdPrman (a synthetic subset) do. For Blender, map subsets to *material slots on a single mesh*, not per-subset geometry copies (HdPrman's choice suits RenderMan facesets, not Blender). Decide policy for unbound and invisible subsets yourself instead of inheriting the adapter's drop and fold.
4. **Instance flattening order and reverse mapping:**
   - use the same innermost-fastest flattened index as Storm, Embree and `HdxPrimOriginInfo`;
   - compute per-level `instanceId`s with `ComputeInstanceIndicesForProto`;
   - compose identity with `GetFullPath` rules from `instanceLocations` + `primOrigin`;
   - for point instancers use (instancer path, index), as dev HdPrman does.
   - **For representation, prefer HdPrman's approach** (nested prototype groups, flattening only beyond a depth or for unsupported per-instance attributes, analogous to Blender collection instancing) **over Embree's full Cartesian flattening.**
5. **Validate before Blender** (§8), and turn Tf warnings into diagnostics.
6. **Classify time variation with `GetContributingSampleTimesForInterval`** on the *flattened* data sources (§6). Probe every filter in the chain.
7. **Materials:**
   - choose the network with `GetMaterialNetwork({mtlx?, universal})` (Storm's rule);
   - convert with `HdConvertToHdMaterialNetwork2`, or read through `HdDataSourceMaterialNetworkInterface`;
   - on a `material` dirty, re-translate that material only. Storm and HdPrman both re-process whole networks; there is no parameter-level diff to borrow.

**Avoid:**
- relying on `GetScenePrimPath` under emulation;
- treating `points` as a vertex buffer without checking sizes (Storm drops the whole prim when `points` is short; a consumer must emit a diagnostic and a placeholder instead);
- running filters that change geometry for rendering (velocity motion, motion blur, retessellation);
- Hydra 1 per-prim parallel side effects. Keep capture read-only.
