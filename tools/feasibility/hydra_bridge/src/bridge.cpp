#include "bridge.h"

#include "capture.h"
#include "diagnostics.h"

#include <pxr/base/tf/errorMark.h>

#include <stdexcept>

PXR_NAMESPACE_USING_DIRECTIVE

namespace hydra_bridge {

Bridge::Bridge(const UsdStagePtr &stage) : stage_(stage) {
    TfErrorMark mark;
    // A strong reference of the graph's own, added to the caller's rather than taken from it.
    UsdStageRefPtr strong = TfCreateRefPtrFromProtectedWeakPtr(stage);
    if (!strong) throw std::invalid_argument("Expected a valid USD stage");
    {
        WarningCollector warnings;
        graph_ = std::make_unique<SceneIndexGraph>(strong);
        pending_ = warnings.Take();
    }
    RaiseTfErrors(mark);
}

SnapshotPtr Bridge::Capture(UsdTimeCode time, bool incremental) {
    if (!graph_) throw std::runtime_error("Bridge has been released");
    last_ = hydra_bridge::Capture(*graph_, time, incremental ? last_.get() : nullptr, std::move(pending_));
    pending_.clear();
    return last_;
}

}  // namespace hydra_bridge
