// WORKAROUND for OpenUSD #3690 (open, "Missing material binding on propagated prototype";
// https://github.com/PixarAnimationStudios/OpenUSD/issues/3690). Hydra resolves collection-based material
// bindings on prototype paths, and the source-info filter's UsdShade resolution runs on prototype prims too,
// so a binding collection that names prims inside a native instance binds nothing there. USD resolves each
// instance proxy on its own, so instances of one prototype can bind differently. The same cause misses a
// collection outside an instance that includes one instance's prims (no upstream issue found for that shape).
//
// For every instance a binding collection reaches, UsdShade resolves each drawn copy on its instance-proxy
// path, and the planner uses those answers in place of its per-prototype resolution (BoundMaterial). Instances
// no binding collection reaches keep the per-prototype path, which matches UsdShade there.
//
// Remove when Blender's USD carries a fix: the bindings case's known-gap checks on Hydra's own bindings then
// stop reproducing (M1b plan, Phase E log: "Collection bindings inside instances").
#pragma once

#include <pxr/pxr.h>
#include <pxr/base/tf/token.h>
#include <pxr/usd/sdf/path.h>
#include <pxr/usd/usd/stage.h>

#include <array>
#include <optional>
#include <unordered_map>
#include <vector>

namespace hydra_bridge {

struct CopyBindings {
    // The instances whose copies are resolved here, outermost first among nested ones (USD paths; a nested
    // instance is an instance proxy).
    pxr::SdfPathVector instances;
    // UsdShade's bound material for each copy inside those instances (imageable prims and subsets, by USD
    // path), per material purpose in MaterialPurposeIndex order; an empty path binds nothing.
    std::unordered_map<pxr::SdfPath, std::array<pxr::SdfPath, 3>, pxr::SdfPath::Hash> materials;
};

// allPurpose (""), preview, full -> 0, 1, 2; nullopt for another purpose, which this workaround doesn't cover.
std::optional<size_t> MaterialPurposeIndex(const pxr::TfToken &purpose);

// Finds the instances binding collections reach and resolves their copies. Reads the whole stage through
// instance proxies; never call alongside reads of the graph or stage edits.
CopyBindings ComputeCopyBindings(const pxr::UsdStagePtr &stage);

}  // namespace hydra_bridge
