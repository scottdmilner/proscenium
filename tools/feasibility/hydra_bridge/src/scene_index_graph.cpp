#include "scene_index_graph.h"

#include <pxr/base/tf/diagnostic.h>
#include <pxr/imaging/hd/dependencyForwardingSceneIndex.h>
#include <pxr/imaging/hd/retainedDataSource.h>
#include <pxr/imaging/hd/tokens.h>
#include <pxr/imaging/hdsi/extComputationPrimvarPruningSceneIndex.h>
#include <pxr/imaging/hdsi/implicitSurfaceSceneIndex.h>
#include <pxr/imaging/hdsi/nurbsApproximatingSceneIndex.h>
#include <pxr/usdImaging/usdImaging/stageSceneIndex.h>

#include <memory>

PXR_NAMESPACE_USING_DIRECTIVE

namespace hydra_bridge {

namespace {

// The batching scene index requires a priority functor, but notice order doesn't matter yet: capture
// re-reads every prim after each flush rather than applying notices. A consumer that applies notices
// incrementally (Phase 2) might want materials first, so a prim's binding resolves to a material it
// has already seen; that is untested and undecided.
class SinglePriority final : public HdsiPrimTypeNoticeBatchingSceneIndex::PrimTypePriorityFunctor {
public:
    [[nodiscard]] size_t GetPriorityForPrimType(const TfToken &) const override { return 0; }
    [[nodiscard]] size_t GetNumPriorities() const override { return 1; }
};

HdContainerDataSourceHandle ImplicitSurfacesToMesh() {
    auto toMesh = HdRetainedTypedSampledDataSource<TfToken>::New(HdsiImplicitSurfaceSceneIndexTokens->toMesh);
    return HdRetainedContainerDataSource::New(HdPrimTypeTokens->cube, toMesh, HdPrimTypeTokens->sphere, toMesh,
                                              HdPrimTypeTokens->cone, toMesh, HdPrimTypeTokens->cylinder, toMesh,
                                              HdPrimTypeTokens->capsule, toMesh, HdPrimTypeTokens->plane, toMesh);
}

}  // namespace

void RecordingObserver::PrimsAdded(const HdSceneIndexBase &, const AddedPrimEntries &entries) {
    for (const auto &entry : entries) events_.push_back({EventKind::Added, entry.primPath, {}, {}});
}

void RecordingObserver::PrimsRemoved(const HdSceneIndexBase &, const RemovedPrimEntries &entries) {
    for (const auto &entry : entries) events_.push_back({EventKind::Removed, entry.primPath, {}, {}});
}

void RecordingObserver::PrimsDirtied(const HdSceneIndexBase &, const DirtiedPrimEntries &entries) {
    for (const auto &entry : entries) {
        Event event{EventKind::Dirtied, entry.primPath, {}, {}};
        for (const auto &locator : entry.dirtyLocators) event.locators.push_back(locator.GetString());
        events_.push_back(std::move(event));
    }
}

void RecordingObserver::PrimsRenamed(const HdSceneIndexBase &, const RenamedPrimEntries &entries) {
    for (const auto &entry : entries) events_.push_back({EventKind::Renamed, entry.newPrimPath, entry.oldPrimPath, {}});
}

std::vector<Event> RecordingObserver::Take() {
    std::vector<Event> taken;
    taken.swap(events_);
    return taken;
}

SceneIndexGraph::SceneIndexGraph(const UsdStageRefPtr &stage) {
    UsdImagingCreateSceneIndicesInfo info;
    info.stage = stage;
    info.addDrawModeSceneIndex = false;
    // Right after the stage scene index, where paths are still USD paths.
    const UsdStagePtr weakStage(stage);
    info.overridesSceneIndexCallback = [this,
                                        weakStage](const HdSceneIndexBaseRefPtr &input) -> HdSceneIndexBaseRefPtr {
        sourceInfo_ = SourceInfoSceneIndex::New(input, weakStage);
        return sourceInfo_;
    };
    // Already flattens inherited state at every instancing level.
    indices_ = UsdImagingCreateSceneIndices(info);
    // Every capture relies on the filter; a USD that skipped the overrides callback would build a graph
    // without it. The bridge's constructor raises this error.
    if (!sourceInfo_) TF_RUNTIME_ERROR("UsdImagingCreateSceneIndices didn't call the overrides callback");
    HdSceneIndexBaseRefPtr scene = indices_.finalSceneIndex;
    // Skinned points become plain primvars, computed on the CPU when read.
    scene = HdSiExtComputationPrimvarPruningSceneIndex::New(scene);
    scene = HdsiImplicitSurfaceSceneIndex::New(scene, ImplicitSurfacesToMesh());
    scene = HdsiNurbsApproximatingSceneIndex::New(scene);
    // Turns __dependencies into dirties, e.g. a cube's size dirtying the points generated from it.
    scene = HdDependencyForwardingSceneIndex::New(scene);
    auto priorities = std::make_shared<SinglePriority>();
    batching_ = HdsiPrimTypeNoticeBatchingSceneIndex::New(
        scene,
        HdRetainedContainerDataSource::New(
            HdsiPrimTypeNoticeBatchingSceneIndexTokens->primTypePriorityFunctor,
            HdRetainedTypedSampledDataSource<HdsiPrimTypeNoticeBatchingSceneIndex::PrimTypePriorityFunctorHandle>::New(
                priorities)));
    terminal_ = batching_;
    terminal_->AddObserver(HdSceneIndexObserverPtr(&observer_));
}

SceneIndexGraph::~SceneIndexGraph() {
    terminal_->RemoveObserver(HdSceneIndexObserverPtr(&observer_));
    // The stage scene index holds a strong stage reference; drop it so a caller-released stage can expire.
    if (sourceInfo_) sourceInfo_->Detach();
    indices_.stageSceneIndex->SetStage(nullptr);
}

void SceneIndexGraph::Advance(UsdTimeCode time) {
    if (sourceInfo_) sourceInfo_->SetTime(time);
    indices_.stageSceneIndex->SetTime(time);
    indices_.stageSceneIndex->ApplyPendingUpdates();
    if (sourceInfo_) sourceInfo_->ApplyPendingUpdates();
    // The batching scene index is empty until its first flush, and holds notices until each one.
    batching_->Flush();
}

}  // namespace hydra_bridge
