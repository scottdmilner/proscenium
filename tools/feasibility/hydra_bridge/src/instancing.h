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
    // The nearest authored guide/proxy/render visibility at or above the instance root, per purpose.
    PurposeVisibility purposeVisibility;
    // The instance root's own bindings, per purpose, resolved in the enclosing namespace, and the purposes
    // bound strongerThanDescendants at or above the instance root (see BoundMaterial).
    std::vector<std::pair<pxr::TfToken, pxr::SdfPath>> bindings;
    pxr::TfTokenVector strongPurposes;

    [[nodiscard]] pxr::SdfPath Map(const pxr::SdfPath &hydraPath) const {
        return hydraPath.ReplacePrefix(hydraRoot, usdRoot);
    }
};

// UsdGeomImageable::ComputeEffectiveVisibility for the prim's own purpose, in one drawn copy: invisible if
// visibility is; otherwise default-purpose prims are visible, and the others take the nearest authored
// opinion for their purpose, in the prototype then up through the instance roots. With none, guides are
// invisible and proxy and render prims visible. Hydra doesn't image UsdGeomVisibilityAPI, so the opinions
// come from the source-info filter.
bool EffectivelyVisible(const PrimTable &table, const PrimRecord &prim, const Frame &frame);

// The material bound to a prim drawn in `frame`, for `purpose` falling back to allPurpose as UsdShade does.
// Hydra's flattened bindings aren't used: inside prototypes they miss collection bindings and, from a v26.03
// propagation bug (also in dev 5bc38c9), re-root an inner instance root's binding to a material in the
// enclosing prototype into the inner prototype, naming a missing material or a different one that shares its
// relative path. Instead, for each purpose:
// - a strongerThanDescendants binding at or above the instance root wins;
// - otherwise UsdShade's binding inside the prototype (the source-info filter's, which covers collections,
//   strength, and bindings without MaterialBindingAPI there);
// - otherwise the instance root's own, which sits in the enclosing namespace and is resolved the same way.
// A binding to something that isn't a Material binds nothing and ends the search, as in UsdShade.
// M1b plan, Phase C log: "Nested-instance binding bug"; checked by cases/instances.py.
// This misses collections that name paths inside an instance (OpenUSD #3690): the planner resolves the copies
// they reach through the workaround in copy_bindings.h instead.
pxr::SdfPath BoundMaterial(const PrimTable &table, const PrimRecord &prim, const Frame &frame,
                           const pxr::TfToken &purpose);

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
