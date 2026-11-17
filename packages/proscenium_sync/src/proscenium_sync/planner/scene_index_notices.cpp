#include "scene_index_notices.h"

#include <utility>

PXR_NAMESPACE_USING_DIRECTIVE

namespace proscenium {

void NoticeRecorder::PrimsAdded(const HdSceneIndexBase&, const AddedPrimEntries& entries) {
  const std::scoped_lock lock(mutex_);
  for (const auto& entry : entries) notices_.push_back({SceneIndexNoticeKind::Added, entry.primPath, {}, {}});
}

void NoticeRecorder::PrimsRemoved(const HdSceneIndexBase&, const RemovedPrimEntries& entries) {
  const std::scoped_lock lock(mutex_);
  for (const auto& entry : entries) notices_.push_back({SceneIndexNoticeKind::Removed, entry.primPath, {}, {}});
}

void NoticeRecorder::PrimsDirtied(const HdSceneIndexBase&, const DirtiedPrimEntries& entries) {
  const std::scoped_lock lock(mutex_);
  for (const auto& entry : entries)
    notices_.push_back({SceneIndexNoticeKind::Dirtied, entry.primPath, {}, entry.dirtyLocators});
}

void NoticeRecorder::PrimsRenamed(const HdSceneIndexBase&, const RenamedPrimEntries& entries) {
  const std::scoped_lock lock(mutex_);
  for (const auto& entry : entries)
    notices_.push_back({SceneIndexNoticeKind::Renamed, entry.newPrimPath, entry.oldPrimPath, {}});
}

SceneIndexNotices NoticeRecorder::Take() {
  const std::scoped_lock lock(mutex_);
  SceneIndexNotices taken;
  taken.swap(notices_);
  return taken;
}

NoticedPrims::NoticedPrims(const SceneIndexNotices& notices) {
  for (const SceneIndexNotice& notice : notices) {
    switch (notice.kind) {
      case SceneIndexNoticeKind::Added:
      case SceneIndexNoticeKind::Dirtied:
        exact_.insert(notice.primPath);
        break;
      case SceneIndexNoticeKind::Removed:
        subtreeRoots_.insert(notice.primPath);
        break;
      case SceneIndexNoticeKind::Renamed:
        subtreeRoots_.insert(notice.oldPrimPath);
        subtreeRoots_.insert(notice.primPath);
        break;
    }
  }
}

bool NoticedPrims::Contains(const SdfPath& primPath) const {
  if (exact_.count(primPath) != 0) return true;
  if (subtreeRoots_.empty()) return false;
  for (SdfPath ancestor = primPath; !ancestor.IsEmpty(); ancestor = ancestor.GetParentPath()) {
    if (subtreeRoots_.count(ancestor) != 0) return true;
    if (ancestor.IsAbsoluteRootPath()) break;
  }
  return false;
}

}  // namespace proscenium
