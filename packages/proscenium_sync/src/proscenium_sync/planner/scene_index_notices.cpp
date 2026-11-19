#include "scene_index_notices.h"

#include <utility>

PXR_NAMESPACE_USING_DIRECTIVE

namespace proscenium {

void NoticeRecorder::PrimsAdded(const HdSceneIndexBase&, const AddedPrimEntries& entries) {
  const std::scoped_lock lock(mutex_);
  for (const auto& entry : entries) noticed_.exact_.insert(entry.primPath);
}

void NoticeRecorder::PrimsRemoved(const HdSceneIndexBase&, const RemovedPrimEntries& entries) {
  const std::scoped_lock lock(mutex_);
  for (const auto& entry : entries) noticed_.subtreeRoots_.insert(entry.primPath);
}

void NoticeRecorder::PrimsDirtied(const HdSceneIndexBase&, const DirtiedPrimEntries& entries) {
  const std::scoped_lock lock(mutex_);
  for (const auto& entry : entries) noticed_.exact_.insert(entry.primPath);
}

void NoticeRecorder::PrimsRenamed(const HdSceneIndexBase&, const RenamedPrimEntries& entries) {
  const std::scoped_lock lock(mutex_);
  for (const auto& entry : entries) {
    noticed_.subtreeRoots_.insert(entry.oldPrimPath);
    noticed_.subtreeRoots_.insert(entry.newPrimPath);
  }
}

NoticedPrims NoticeRecorder::Take() {
  const std::scoped_lock lock(mutex_);
  return std::exchange(noticed_, {});
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
