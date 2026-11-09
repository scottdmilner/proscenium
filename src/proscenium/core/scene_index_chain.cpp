#include "scene_index_chain.h"

#include <pxr/base/work/loops.h>
#include <pxr/imaging/hd/dependencyForwardingSceneIndex.h>
#include <pxr/imaging/hd/primvarsSchema.h>
#include <pxr/imaging/hd/retainedDataSource.h>
#include <pxr/imaging/hd/tokens.h>
#include <pxr/imaging/hdsi/extComputationPrimvarPruningSceneIndex.h>
#include <pxr/imaging/hdsi/implicitSurfaceSceneIndex.h>
#include <pxr/imaging/hdsi/nurbsApproximatingSceneIndex.h>
#include <pxr/usd/usdGeom/metrics.h>
#include <pxr/usdImaging/usdImaging/stageSceneIndex.h>

#include <algorithm>
#include <memory>
#include <set>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <utility>
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
  // Only the planned primvars, so no prim's geometry is copied before planning reads it.
  TfTokenVector primvarNames;
  std::vector<HdDataSourceBaseHandle> primvarCopies;
  const HdPrimvarsSchema primvars = HdPrimvarsSchema::GetFromParent(source);
  for (const TfToken& name : primvars ? PlannedPrimvars() : TfTokenVector()) {
    if (const HdContainerDataSourceHandle primvar = primvars.GetPrimvar(name).GetContainer()) {
      primvarNames.push_back(name);
      primvarCopies.push_back(HdMakeStaticCopy(primvar));
    }
  }
  if (!primvarNames.empty()) {
    names.push_back(HdPrimvarsSchema::GetSchemaToken());
    copies.push_back(
        HdRetainedContainerDataSource::New(primvarNames.size(), primvarNames.data(), primvarCopies.data()));
  }
  return HdRetainedContainerDataSource::New(names.size(), names.data(), copies.data());
}

}  // namespace

SceneIndexChain::SceneIndexChain(const UsdStagePtr& stage) : handle_(stage) {
  TfDiagnosticCollector warnings;
  Build();
  pending_ = warnings.Take();
}

void SceneIndexChain::Build() {
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
  // Destroying the stage scene index drops its stage reference.
  terminal_.Reset();
  sourceInfo_.Reset();
  indices_ = {};
  handle_.Release();
}

SnapshotPtr SceneIndexChain::Capture(UsdTimeCode time) {
  if (!terminal_) throw std::runtime_error("The scene index chain has been released");
  TfDiagnosticCollector warnings;
  // The chain's own: those posted while it was built, then while it moves to `time` and applies the stage's edits.
  Diagnostics chain;
  chain.swap(pending_);
  // Depth-first, parents before children, so the retained scene index gets each parent first.
  SdfPathVector paths;
  {
    const TfErrorMark mark;
    sourceInfo_->SetTime(time);
    indices_.stageSceneIndex->SetTime(time);
    indices_.stageSceneIndex->ApplyPendingUpdates();
    // As HdSceneIndexPrimView, with each prim's children listed under its source, since listing them can make
    // UsdImaging post about that prim.
    std::vector<SdfPath> stack{SdfPath::AbsoluteRootPath()};
    while (!stack.empty()) {
      const SdfPath path = stack.back();
      stack.pop_back();
      paths.push_back(path);
      const TfDiagnosticCollector::ScopedSource source(path);
      SdfPathVector children = terminal_->GetChildPrimPaths(path);
      stack.insert(stack.end(), children.rbegin(), children.rend());
    }
    HarvestErrors(mark, SdfPath(), chain);
  }
  // One parallel pass, as the bridge's capture copies: Hydra's reads are threadsafe, and nothing changes the chain
  // until the pass ends. Each prim's read opens its own mark, so an error is the prim's, and the collector attributes
  // the thread's warnings to it; one posted on a thread Hydra hands part of a read to names that thread's prim, or
  // none.
  std::vector<HdRetainedSceneIndex::AddedPrimEntry> entries(paths.size());
  std::vector<Diagnostics> errors(paths.size());
  WorkParallelForN(paths.size(), [&](std::size_t begin, std::size_t end) {
    for (std::size_t i = begin; i < end; ++i) {
      const TfDiagnosticCollector::ScopedSource source(paths[i]);
      const TfErrorMark mark;
      const HdSceneIndexPrim prim = terminal_->GetPrim(paths[i]);
      entries[i] = {paths[i], prim.primType, CopyPlannedSchemas(prim.dataSource)};
      HarvestErrors(mark, paths[i], errors[i]);
    }
  });
  const HdRetainedSceneIndexRefPtr scene = HdRetainedSceneIndex::New();
  scene->AddPrims(entries);
  // A warning attributed to a prim is its own; the rest the chain posted.
  std::unordered_map<SdfPath, Diagnostics, SdfPath::Hash> warned;
  for (Diagnostic& warning : warnings.Take())
    (warning.source.IsEmpty() ? chain : warned[warning.source]).push_back(std::move(warning));
  // A prim's diagnostics name its path, so they never repeat another's.
  Diagnostics prims;
  std::set<std::pair<DiagnosticCode, std::string>> attributed;
  for (std::size_t i = 0; i < paths.size(); ++i) {
    Diagnostics own;
    AppendUnique(errors[i], own);
    if (const auto found = warned.find(paths[i]); found != warned.end()) AppendUnique(found->second, own);
    for (const Diagnostic& diagnostic : own) attributed.emplace(diagnostic.code, diagnostic.message);
    prims.insert(prims.end(), own.begin(), own.end());
  }
  // A chain diagnostic a prim's repeats is the same problem, reported with less: UsdImaging posts while the chain is
  // built what it posts again while a capture lists that prim's children.
  chain.erase(std::remove_if(chain.begin(), chain.end(),
                             [&](const Diagnostic& d) { return attributed.count({d.code, d.message}) != 0; }),
              chain.end());
  Diagnostics diagnostics;
  AppendUnique(chain, diagnostics);
  diagnostics.insert(diagnostics.end(), prims.begin(), prims.end());
  const UsdStagePtr stage = handle_.Stage();
  return std::make_shared<Snapshot>(
      Snapshot{time, scene, UsdGeomGetStageMetersPerUnit(stage), UsdGeomGetStageUpAxis(stage), std::move(diagnostics)});
}

}  // namespace proscenium
