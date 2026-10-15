// Reverse mapping from Hydra's native instancers to USD sources with instance context, as
// HdxPrimOriginInfo does: walk instancedBy upward and fold in instanceLocations at each level.
// Source identity could come from HdxPrimOriginInfo itself, but in v26.03 it is quadratic in the
// instance count (non-const VtArray indexing in hdx/pickTask.cpp detaches the cached arrays on every
// hit). Switch to it once the USD Blender bundles has OpenUSD dev's cdata() fix; see the M1b plan's
// Phase B log. Transforms, visibility, and inherited primvars stay here either way.
#pragma once

#include "diagnostics.h"
#include "plan.h"
#include "prim_record.h"

#include <pxr/pxr.h>
#include <pxr/base/gf/matrix4d.h>
#include <pxr/usd/sdf/path.h>

#include <string>
#include <unordered_map>
#include <vector>

namespace hydra_bridge {

// One drawn copy of a prototype's contents: where its Hydra namespace sits in USD, and the
// transform, visibility, and per-instance primvars it inherits from its instance roots.
struct Frame {
    pxr::SdfPath hydraRoot = pxr::SdfPath::AbsoluteRootPath();
    pxr::SdfPath usdRoot = pxr::SdfPath::AbsoluteRootPath();
    pxr::SdfPathVector context;  // instance roots, outermost first
    pxr::GfMatrix4d world{1.0};
    bool visible = true;
    ConstantPrimvars instancePrimvars;  // innermost instance first, one entry per name

    pxr::SdfPath Map(const pxr::SdfPath &hydraPath) const { return hydraPath.ReplacePrefix(hydraRoot, usdRoot); }
};

class InstanceResolver {
public:
    // Diagnostics about malformed or unsupported instancers go to `diagnostics`.
    InstanceResolver(const PrimTable &table, Diagnostics &diagnostics);

    // Every drawn copy of `prim`: one identity frame outside instancing, none when unresolvable.
    const std::vector<Frame> &FramesOf(const PrimRecord &prim);

private:
    const std::vector<Frame> &FramesOf(const PrimRecord &prim, int depth);
    // The frames of everything under `prototypeRoot`, one per instance of each frame of `instancer`.
    const std::vector<Frame> &FramesUnder(const pxr::SdfPath &instancer, const pxr::SdfPath &prototypeRoot, int depth);
    std::vector<Frame> Expand(const PrimRecord &instancer, const pxr::SdfPath &prototypeRoot, int depth);
    void Report(const PrimRecord &prim, const std::string &code, const std::string &message);

    const PrimTable &table_;
    Diagnostics &diagnostics_;
    const std::vector<Frame> top_{Frame()};
    const std::vector<Frame> none_;
    std::unordered_map<pxr::SdfPath, std::vector<Frame>, pxr::SdfPath::Hash> cache_;  // by prototype root
};

}  // namespace hydra_bridge
