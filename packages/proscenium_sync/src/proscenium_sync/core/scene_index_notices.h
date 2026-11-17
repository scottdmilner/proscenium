// The notices the chain's terminal scene index sends between captures, and the paths they name, so a capture copies
// only those prims again and shares the rest with the snapshot before (scene_index_chain.h). Ported from the Hydra
// bridge's RecordingObserver and its capture's affected paths.
#pragma once

#include <pxr/imaging/hd/sceneIndexObserver.h>
#include <pxr/pxr.h>
#include <pxr/usd/sdf/path.h>

#include <cstdint>
#include <mutex>
#include <unordered_set>
#include <vector>

namespace proscenium {

enum class SceneIndexNoticeKind : std::uint8_t { Added, Removed, Dirtied, Renamed };

struct SceneIndexNotice {
  SceneIndexNoticeKind kind;
  PXR_NS::SdfPath primPath;                      // for a rename, the new path
  PXR_NS::SdfPath oldPrimPath;                   // renamed only
  PXR_NS::HdDataSourceLocatorSet dirtyLocators;  // dirtied only
};

using SceneIndexNotices = std::vector<SceneIndexNotice>;

// Records each prim entry of the notices a scene index sends it, in order, until taken.
class NoticeRecorder final : public PXR_NS::HdSceneIndexObserver {
 public:
  void PrimsAdded(const PXR_NS::HdSceneIndexBase&, const AddedPrimEntries& entries) override;
  void PrimsRemoved(const PXR_NS::HdSceneIndexBase&, const RemovedPrimEntries& entries) override;
  void PrimsDirtied(const PXR_NS::HdSceneIndexBase&, const DirtiedPrimEntries& entries) override;
  void PrimsRenamed(const PXR_NS::HdSceneIndexBase&, const RenamedPrimEntries& entries) override;

  // The notices recorded since the last call.
  SceneIndexNotices Take();

 private:
  std::mutex mutex_;  // notices are sent where a stage is edited or the chain moves, never alongside a read
  SceneIndexNotices notices_;
};

// The prims notices name: an added or dirtied prim exactly, and a removed or renamed prim with its descendants.
class NoticedPrims {
 public:
  explicit NoticedPrims(const SceneIndexNotices& notices);

  [[nodiscard]] bool Contains(const PXR_NS::SdfPath& primPath) const;

 private:
  std::unordered_set<PXR_NS::SdfPath, PXR_NS::SdfPath::Hash> exact_;
  std::unordered_set<PXR_NS::SdfPath, PXR_NS::SdfPath::Hash> subtreeRoots_;
};

}  // namespace proscenium
