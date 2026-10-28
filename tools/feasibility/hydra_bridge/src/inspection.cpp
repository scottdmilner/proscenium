// KindTarget: kind promotion, walking up from a floor on the live stage.
#include "inspection.h"

#include <pxr/usd/kind/registry.h>
#include <pxr/usd/usd/modelAPI.h>
#include <pxr/usd/usd/prim.h>

PXR_NAMESPACE_USING_DIRECTIVE

namespace hydra_bridge {

SdfPath KindTarget(const UsdStage &stage, const SdfPath &floor, const TfToken &kind) {
    for (UsdPrim prim = stage.GetPrimAtPath(floor); prim && !prim.IsPseudoRoot(); prim = prim.GetParent()) {
        TfToken authored;
        if (UsdModelAPI(prim).GetKind(&authored) && KindRegistry::IsA(authored, kind)) return prim.GetPath();
    }
    return floor;
}

}  // namespace hydra_bridge
