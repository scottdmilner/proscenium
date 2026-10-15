#include "bridge.h"

#include "capture.h"
#include "diagnostics.h"

#include <pxr/base/tf/errorMark.h>

#include <stdexcept>

PXR_NAMESPACE_USING_DIRECTIVE

namespace hydra_bridge {

Bridge::Bridge(const UsdStageRefPtr &stage) : stage_(stage) {
    TfErrorMark mark;
    if (!stage) throw std::invalid_argument("Expected a valid USD stage");
    graph_ = std::make_unique<SceneIndexGraph>(stage);
    RaiseTfErrors(mark);
}

SnapshotPtr Bridge::Capture(UsdTimeCode time) {
    if (!graph_) throw std::runtime_error("Bridge has been released");
    return hydra_bridge::Capture(*graph_, time);
}

}  // namespace hydra_bridge
