#include "stage_handle.h"

#include <stdexcept>

PXR_NAMESPACE_USING_DIRECTIVE

namespace proscenium {

StageHandle::StageHandle(const UsdStagePtr& stage) : stage_(stage), held_(TfCreateRefPtrFromProtectedWeakPtr(stage)) {
  if (!held_) throw std::invalid_argument("Expected a valid USD stage");
}

}  // namespace proscenium
