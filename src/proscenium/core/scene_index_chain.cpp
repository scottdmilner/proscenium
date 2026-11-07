#include "scene_index_chain.h"

#include <pxr/imaging/hd/dependencyForwardingSceneIndex.h>
#include <pxr/imaging/hd/retainedDataSource.h>
#include <pxr/imaging/hd/sceneIndexPrimView.h>
#include <pxr/imaging/hd/tokens.h>
#include <pxr/imaging/hdsi/extComputationPrimvarPruningSceneIndex.h>
#include <pxr/imaging/hdsi/implicitSurfaceSceneIndex.h>
#include <pxr/imaging/hdsi/nurbsApproximatingSceneIndex.h>
#include <pxr/usdImaging/usdImaging/stageSceneIndex.h>

#include <memory>
#include <stdexcept>
#include <vector>

PXR_NAMESPACE_USING_DIRECTIVE

namespace proscenium {
namespace {

HdContainerDataSourceHandle ImplicitSurfacesToMesh() {
  auto toMesh = HdRetainedTypedSampledDataSource<TfToken>::New(HdsiImplicitSurfaceSceneIndexTokens->toMesh);
  return HdRetainedContainerDataSource::New(HdPrimTypeTokens->cube, toMesh, HdPrimTypeTokens->sphere, toMesh,
                                            HdPrimTypeTokens->cone, toMesh, HdPrimTypeTokens->cylinder, toMesh,
                                            HdPrimTypeTokens->capsule, toMesh, HdPrimTypeTokens->plane, toMesh);
}

// A new prim container holding a frozen copy of each planned schema the prim has, and nothing else. HdMakeStaticCopy
// samples every value at the chain's current time into retained data sources, so the copy no longer reads the stage.
HdContainerDataSourceHandle CopyPlannedSchemas(const HdContainerDataSourceHandle& source) {
  if (!source) return nullptr;
  TfTokenVector names;
  std::vector<HdDataSourceBaseHandle> copies;
  for (const TfToken& name : PlannedSchemas()) {
    if (const HdDataSourceBaseHandle schema = source->Get(name)) {
      names.push_back(name);
      copies.push_back(HdMakeStaticCopy(schema));
    }
  }
  return HdRetainedContainerDataSource::New(names.size(), names.data(), copies.data());
}

}  // namespace

SceneIndexChain::SceneIndexChain(const UsdStagePtr& stage) : handle_(stage) {
  UsdImagingCreateSceneIndicesInfo info;
  info.stage = TfCreateRefPtrFromProtectedWeakPtr(handle_.Stage());
  info.addDrawModeSceneIndex = false;
  // Right after the stage scene index, where paths are still USD paths.
  const UsdStagePtr stagePtr = handle_.Stage();
  info.overridesSceneIndexCallback = [this, stagePtr](const HdSceneIndexBaseRefPtr& input) -> HdSceneIndexBaseRefPtr {
    sourceInfo_ = SourceInfoSceneIndex::New(input, stagePtr);
    return sourceInfo_;
  };
  // Flattens transforms, visibility, and purpose at every instancing level.
  indices_ = UsdImagingCreateSceneIndices(info);
  // Every capture relies on the filter.
  if (!sourceInfo_) throw std::runtime_error("UsdImagingCreateSceneIndices didn't call the overrides callback");
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
  if (sourceInfo_) sourceInfo_->Detach();
  if (indices_.stageSceneIndex) indices_.stageSceneIndex->SetStage(nullptr);
  terminal_.Reset();
  sourceInfo_.Reset();
  indices_ = {};
  handle_.Release();
}

SnapshotPtr SceneIndexChain::Capture(UsdTimeCode time) {
  if (!terminal_) throw std::runtime_error("The scene index chain has been released");
  sourceInfo_->SetTime(time);
  indices_.stageSceneIndex->SetTime(time);
  indices_.stageSceneIndex->ApplyPendingUpdates();
  // Depth-first, parents before children, so the retained scene index gets each parent first.
  std::vector<HdRetainedSceneIndex::AddedPrimEntry> entries;
  for (const SdfPath& path : HdSceneIndexPrimView(terminal_, SdfPath::AbsoluteRootPath())) {
    const HdSceneIndexPrim prim = terminal_->GetPrim(path);
    entries.push_back({path, prim.primType, CopyPlannedSchemas(prim.dataSource)});
  }
  auto snapshot = std::make_shared<Snapshot>();
  snapshot->time = time;
  snapshot->scene = HdRetainedSceneIndex::New();
  snapshot->scene->AddPrims(entries);
  return snapshot;
}

}  // namespace proscenium
