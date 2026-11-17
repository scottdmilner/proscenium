// The inspection layer (interaction-contract.md "Two Layers and the Live Stage"), ported from the bridge's inspection:
// selection targets by model kind on the live stage. It includes only USD and the standard library, never the planner,
// and is read-only: it authors nothing and changes no load set, population mask, or other stage setting.
#pragma once

#include <pxr/base/tf/token.h>
#include <pxr/pxr.h>
#include <pxr/usd/sdf/path.h>
#include <pxr/usd/usd/stage.h>

namespace proscenium_inspection {

// The selection target of `floorPath` at the kind level `kind` (interaction-contract.md "Selection"): the nearest
// ancestor-or-self on `stage` whose authored kind is `kind` or derives from it, whether or not the prim is in a valid
// model hierarchy, or else `floorPath`, as when the stage lacks it.
PXR_NS::SdfPath KindTarget(const PXR_NS::UsdStage& stage, const PXR_NS::SdfPath& floorPath,
                           const PXR_NS::TfToken& kind);

// Whether `kind` is a registered model kind, so a selection level.
bool IsRegisteredKind(const PXR_NS::TfToken& kind);

}  // namespace proscenium_inspection
