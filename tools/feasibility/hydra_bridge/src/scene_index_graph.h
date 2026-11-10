// The scene-index graph over a stage, built explicitly rather than through renderer plugin registration so its
// filters don't depend on what else is on Blender's plugin path.
#pragma once

#include "snapshot.h"
#include "source_info_scene_index.h"

#include <pxr/pxr.h>
#include <pxr/imaging/hd/sceneIndex.h>
#include <pxr/imaging/hd/sceneIndexObserver.h>
#include <pxr/imaging/hdsi/primTypeNoticeBatchingSceneIndex.h>
#include <pxr/usd/usd/stage.h>
#include <pxr/usd/usd/timeCode.h>
#include <pxr/usdImaging/usdImaging/sceneIndices.h>

#include <vector>

namespace hydra_bridge {

// Records the terminal's notices between captures.
class RecordingObserver final : public pxr::HdSceneIndexObserver {
public:
    void PrimsAdded(const pxr::HdSceneIndexBase &, const AddedPrimEntries &entries) override;
    void PrimsRemoved(const pxr::HdSceneIndexBase &, const RemovedPrimEntries &entries) override;
    void PrimsDirtied(const pxr::HdSceneIndexBase &, const DirtiedPrimEntries &entries) override;
    void PrimsRenamed(const pxr::HdSceneIndexBase &, const RenamedPrimEntries &entries) override;

    std::vector<SceneIndexEvent> Take();
    // Puts `events` before any not yet taken, for the next Take.
    void Requeue(std::vector<SceneIndexEvent> events);

private:
    std::vector<SceneIndexEvent> events_;
};

class SceneIndexGraph {
public:
    explicit SceneIndexGraph(const pxr::UsdStageRefPtr &stage);
    ~SceneIndexGraph();
    SceneIndexGraph(const SceneIndexGraph &) = delete;
    SceneIndexGraph &operator=(const SceneIndexGraph &) = delete;
    SceneIndexGraph(SceneIndexGraph &&) = delete;
    SceneIndexGraph &operator=(SceneIndexGraph &&) = delete;

    // Moves the graph to `time` and processes pending stage edits; notices reach the observer.
    // Must not overlap reads of the terminal.
    void Advance(pxr::UsdTimeCode time);
    // M4 Phase E (E3): dirties every value that depends on time, as a time change would, without changing it
    // (UsdImagingStageSceneIndex's forceDirtyingTimeDeps). Notices reach the observer. Must not overlap reads.
    void DirtyTimeDependencies();
    const pxr::HdSceneIndexBaseRefPtr &Terminal() const { return terminal_; }
    std::vector<SceneIndexEvent> TakeEvents() { return observer_.Take(); }
    void RequeueEvents(std::vector<SceneIndexEvent> events) { observer_.Requeue(std::move(events)); }
    // WORKAROUND for OpenUSD #3690 (instance_material_bindings.h). Call between advances, never alongside reads.
    std::shared_ptr<const CopyBindings> CopyBindingsNow() { return sourceInfo_->CurrentCopyBindings(); }

private:
    pxr::UsdImagingSceneIndices indices_;
    SourceInfoSceneIndexRefPtr sourceInfo_;
    pxr::HdsiPrimTypeNoticeBatchingSceneIndexRefPtr batching_;
    pxr::HdSceneIndexBaseRefPtr terminal_;
    RecordingObserver observer_;
    pxr::UsdTimeCode time_;  // the latest Advance's
};

}  // namespace hydra_bridge
