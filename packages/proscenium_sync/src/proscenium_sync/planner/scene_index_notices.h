// Unique affected paths sent by the terminal scene index between captures, so a capture copies only those prims
// again and shares the rest with the snapshot before (scene_index_chain.h).
#pragma once

#include <pxr/imaging/hd/sceneIndexObserver.h>
#include <pxr/pxr.h>
#include <pxr/usd/sdf/path.h>

#include <mutex>
#include <unordered_set>

namespace proscenium {

// An added or dirtied prim exactly, and a removed or renamed prim with its descendants.
class NoticedPrims {
 public:
  [[nodiscard]] bool Contains(const PXR_NS::SdfPath& primPath) const;

 private:
  friend class NoticeRecorder;
  std::unordered_set<PXR_NS::SdfPath, PXR_NS::SdfPath::Hash> exact_;
  std::unordered_set<PXR_NS::SdfPath, PXR_NS::SdfPath::Hash> subtreeRoots_;
};

// Coalesces the affected paths of notices until a capture takes them.
class NoticeRecorder final : public PXR_NS::HdSceneIndexObserver {
 public:
  void PrimsAdded(const PXR_NS::HdSceneIndexBase&, const AddedPrimEntries& entries) override;
  void PrimsRemoved(const PXR_NS::HdSceneIndexBase&, const RemovedPrimEntries& entries) override;
  void PrimsDirtied(const PXR_NS::HdSceneIndexBase&, const DirtiedPrimEntries& entries) override;
  void PrimsRenamed(const PXR_NS::HdSceneIndexBase&, const RenamedPrimEntries& entries) override;

  // The prims noticed since the last call.
  NoticedPrims Take();

 private:
  std::mutex mutex_;  // notices are sent where a stage is edited or the chain moves, never alongside a read
  NoticedPrims noticed_;
};

}  // namespace proscenium
