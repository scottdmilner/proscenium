// M4's model of the inspection layer (interaction contract, "Two Layers and the Live Stage"): selection targets
// by model kind on the live stage. Like M7's library, it reads only the stage it is given, and includes nothing
// else of the bridge.
#pragma once

#include <pxr/pxr.h>
#include <pxr/base/tf/token.h>
#include <pxr/usd/sdf/path.h>
#include <pxr/usd/usd/stage.h>

namespace hydra_bridge {

// The selection target of `floor` at the kind level `kind`: the nearest ancestor-or-self on `stage` whose
// authored kind is `kind` or derives from it, whether or not the prim is in a valid model hierarchy, or else
// `floor`, as when `floor` is absent from the stage. Read-only.
pxr::SdfPath KindTarget(const pxr::UsdStage &stage, const pxr::SdfPath &floor, const pxr::TfToken &kind);

}  // namespace hydra_bridge
