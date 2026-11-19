#include "nodes/composed_stage.h"

PXR_NAMESPACE_USING_DIRECTIVE

namespace proscenium {

UsdStageRefPtr ComposedStage(const NodeContext& context, const SdfLayerHandle& rootLayer) {
  auto& stage = context.Cache<UsdStageRefPtr>("stage");
  if (!rootLayer) {
    stage = nullptr;
  } else if (!stage || stage->GetRootLayer() != rootLayer) {
    stage = UsdStage::Open(rootLayer, UsdStage::LoadAll);
  }
  return stage;
}

}  // namespace proscenium
