// A lazy Hydra container whose contents are reused until its revision counter changes.
#pragma once

#include <pxr/imaging/hd/dataSource.h>
#include <pxr/pxr.h>

#include <cstdint>
#include <functional>
#include <mutex>

namespace proscenium {

// Downstream scene indices retain this container between notices; each read checks its current revision.
class RevisionCachedContainer final : public PXR_NS::HdContainerDataSource {
 public:
  HD_DECLARE_DATASOURCE(RevisionCachedContainer);

  PXR_NS::TfTokenVector GetNames() override;
  PXR_NS::HdDataSourceBaseHandle Get(const PXR_NS::TfToken& name) override;

 private:
  RevisionCachedContainer(std::function<PXR_NS::HdContainerDataSourceHandle()> build,
                          std::function<uint64_t()> readRevision);
  PXR_NS::HdContainerDataSourceHandle GetOrBuildContents();

  std::function<PXR_NS::HdContainerDataSourceHandle()> build_;
  std::function<uint64_t()> readRevision_;
  std::mutex mutex_;
  bool valid_ = false;
  uint64_t builtRevision_ = 0;
  PXR_NS::HdContainerDataSourceHandle built_;
};

}  // namespace proscenium
