#include "scene_index_chain.h"

#include <pxr/imaging/hd/dependencyForwardingSceneIndex.h>
#include <pxr/imaging/hd/extentSchema.h>
#include <pxr/imaging/hd/instancedBySchema.h>
#include <pxr/imaging/hd/primOriginSchema.h>
#include <pxr/imaging/hd/retainedDataSource.h>
#include <pxr/imaging/hd/sceneIndexPrimView.h>
#include <pxr/imaging/hd/tokens.h>
#include <pxr/imaging/hd/xformSchema.h>
#include <pxr/imaging/hdsi/extComputationPrimvarPruningSceneIndex.h>
#include <pxr/imaging/hdsi/implicitSurfaceSceneIndex.h>
#include <pxr/imaging/hdsi/nurbsApproximatingSceneIndex.h>
#include <pxr/usdImaging/usdImaging/stageSceneIndex.h>

#include <algorithm>
#include <memory>
#include <stdexcept>

PXR_NAMESPACE_USING_DIRECTIVE

namespace proscenium {
namespace {

// Hydra samples a value at a shutter offset from the chain's time; the snapshot takes the time itself.
constexpr HdSampledDataSource::Time kNow = 0.0F;

HdContainerDataSourceHandle ImplicitSurfacesToMesh() {
  auto toMesh = HdRetainedTypedSampledDataSource<TfToken>::New(HdsiImplicitSurfaceSceneIndexTokens->toMesh);
  return HdRetainedContainerDataSource::New(HdPrimTypeTokens->cube, toMesh, HdPrimTypeTokens->sphere, toMesh,
                                            HdPrimTypeTokens->cone, toMesh, HdPrimTypeTokens->cylinder, toMesh,
                                            HdPrimTypeTokens->capsule, toMesh, HdPrimTypeTokens->plane, toMesh);
}

// The gprim's values, or nothing for a prim M5's capture doesn't draw: one that isn't a gprim, or one under native
// or point instancing, whose source and instance context M6's capture derives.
std::optional<DrawnGprim> ReadGprim(const HdSceneIndexBase& scene, const SdfPath& path) {
  const HdSceneIndexPrim prim = scene.GetPrim(path);
  if (!prim.dataSource || !HdPrimTypeIsGprim(prim.primType)) return std::nullopt;
  if (HdInstancedBySchema::GetFromParent(prim.dataSource)) return std::nullopt;
  DrawnGprim gprim;
  // Outside instancing, the stage scene index names a prim by its USD path, and the filtering scene indices that
  // convert it keep that.
  const SdfPath origin =
      HdPrimOriginSchema::GetFromParent(prim.dataSource).GetOriginPath(HdPrimOriginSchemaTokens->scenePath);
  gprim.source = origin.IsEmpty() ? path : origin;
  if (const HdMatrixDataSourceHandle matrix = HdXformSchema::GetFromParent(prim.dataSource).GetMatrix())
    gprim.world = matrix->GetTypedValue(kNow);
  if (const HdExtentSchema extent = HdExtentSchema::GetFromParent(prim.dataSource)) {
    const HdVec3dDataSourceHandle min = extent.GetMin();
    const HdVec3dDataSourceHandle max = extent.GetMax();
    if (min && max) gprim.bounds = GfRange3d(min->GetTypedValue(kNow), max->GetTypedValue(kNow));
  }
  return gprim;
}

}  // namespace

SceneIndexChain::SceneIndexChain(const UsdStagePtr& stage) : handle_(stage) {
  UsdImagingCreateSceneIndicesInfo info;
  info.stage = TfCreateRefPtrFromProtectedWeakPtr(handle_.Stage());
  info.addDrawModeSceneIndex = false;
  // Flattens transforms, visibility, and purpose at every instancing level.
  indices_ = UsdImagingCreateSceneIndices(info);
  HdSceneIndexBaseRefPtr scene = indices_.finalSceneIndex;
  // Skinned points become plain primvars; implicit surfaces and NURBS become meshes, as M6's planner reads them.
  scene = HdSiExtComputationPrimvarPruningSceneIndex::New(scene);
  scene = HdsiImplicitSurfaceSceneIndex::New(scene, ImplicitSurfacesToMesh());
  scene = HdsiNurbsApproximatingSceneIndex::New(scene);
  // Propagates PrimsDirtied along each prim's __dependencies, so a value computed from another is dirty with it.
  terminal_ = HdDependencyForwardingSceneIndex::New(scene);
}

SceneIndexChain::~SceneIndexChain() { Release(); }

void SceneIndexChain::Release() {
  if (indices_.stageSceneIndex) indices_.stageSceneIndex->SetStage(nullptr);
  terminal_.Reset();
  indices_ = {};
  handle_.Release();
}

SnapshotPtr SceneIndexChain::Capture(UsdTimeCode time) {
  if (!terminal_) throw std::runtime_error("The scene index chain has been released");
  indices_.stageSceneIndex->SetTime(time);
  indices_.stageSceneIndex->ApplyPendingUpdates();
  auto snapshot = std::make_shared<Snapshot>();
  snapshot->time = time;
  for (const SdfPath& path : HdSceneIndexPrimView(terminal_, SdfPath::AbsoluteRootPath())) {
    if (std::optional<DrawnGprim> gprim = ReadGprim(*terminal_, path)) snapshot->gprims.push_back(std::move(*gprim));
  }
  std::sort(snapshot->gprims.begin(), snapshot->gprims.end(),
            [](const DrawnGprim& a, const DrawnGprim& b) { return a.source < b.source; });
  return snapshot;
}

}  // namespace proscenium
