// KindTarget: kind promotion, walking up from a floor on the live stage.
#include "kind_targets.h"

#include <pxr/usd/kind/registry.h>
#include <pxr/usd/usd/modelAPI.h>
#include <pxr/usd/usd/prim.h>

PXR_NAMESPACE_USING_DIRECTIVE

namespace proscenium_inspection {

SdfPath KindTarget(const UsdStage& stage, const SdfPath& floorPath, const TfToken& kind) {
  for (UsdPrim prim = stage.GetPrimAtPath(floorPath); prim && !prim.IsPseudoRoot(); prim = prim.GetParent()) {
    TfToken authored;
    if (UsdModelAPI(prim).GetKind(&authored) && KindRegistry::IsA(authored, kind)) return prim.GetPath();
  }
  return floorPath;
}

bool IsRegisteredKind(const TfToken& kind) { return KindRegistry::HasKind(kind); }

}  // namespace proscenium_inspection
