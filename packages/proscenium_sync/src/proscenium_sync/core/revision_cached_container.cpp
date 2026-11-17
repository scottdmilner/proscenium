#include "revision_cached_container.h"

#include <utility>

PXR_NAMESPACE_USING_DIRECTIVE

namespace proscenium {

RevisionCachedContainer::RevisionCachedContainer(std::function<HdContainerDataSourceHandle()> build,
                                                 std::function<uint64_t()> readRevision)
    : build_(std::move(build)), readRevision_(std::move(readRevision)) {}

HdContainerDataSourceHandle RevisionCachedContainer::GetOrBuildContents() {
  const uint64_t revision = readRevision_();
  const std::scoped_lock lock(mutex_);
  if (!valid_ || revision != builtRevision_) {
    built_ = build_();
    builtRevision_ = revision;
    valid_ = true;
  }
  return built_;
}

TfTokenVector RevisionCachedContainer::GetNames() {
  const HdContainerDataSourceHandle built = GetOrBuildContents();
  return built ? built->GetNames() : TfTokenVector();
}

HdDataSourceBaseHandle RevisionCachedContainer::Get(const TfToken& name) {
  const HdContainerDataSourceHandle built = GetOrBuildContents();
  return built ? built->Get(name) : nullptr;
}

}  // namespace proscenium
