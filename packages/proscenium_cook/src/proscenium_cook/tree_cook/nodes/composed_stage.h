// The stage a Stage Output or Viewer composes on its layer, shared by both node types.
#pragma once

#include <pxr/pxr.h>
#include <pxr/usd/sdf/layer.h>
#include <pxr/usd/usd/stage.h>

#include "node_contexts.h"

namespace proscenium {

// The stage composed on rootLayer, with every payload loaded, kept in the node's cache. Each cook gets the same stage
// while its root layer stays the same: a binding reuses its evaluation stage only while the source stage's root and
// session layers stay the same (docs/spec/source-access.md "Source Stages"), and tools may author in the session
// layer. A null rootLayer drops the cached stage and gives null.
PXR_NS::UsdStageRefPtr ComposedStage(const NodeContext& context, const PXR_NS::SdfLayerHandle& rootLayer);

}  // namespace proscenium
