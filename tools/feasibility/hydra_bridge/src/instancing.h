// Reverse mapping from Hydra's instancers to USD sources with instance context, as HdxPrimOriginInfo does:
// walk instancedBy upward and fold in instanceLocations at each level, or a point instancer's points.
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
//
// A point instancer's copies (M4 Phase D, for measurement only: the spec defers point instancers) have no
// instance root, so each point adds two context entries: the instancer's path, then a child of it named
// PointName(point), which no prim has. The instancer is then the copy's floor, which interaction resolves, and
// each point's copies keep their own identity (source, instance context).
struct DrawnCopy {
    pxr::SdfPath hydraNamespaceRoot = pxr::SdfPath::AbsoluteRootPath();
    pxr::SdfPath sourceNamespaceRoot = pxr::SdfPath::AbsoluteRootPath();
    pxr::SdfPathVector instanceContext;  // instance roots, or a point instancer and its point, outermost first
    // The Hydra prim behind each context entry: an instance root's, or for both of a point's entries its instancer.
    pxr::SdfPathVector hydraContext;
    pxr::GfMatrix4d instanceWorldMatrix{1.0};
    bool visible = true;
    ConstantPrimvars instancePrimvars;  // innermost instance first, one entry per name
    // The nearest authored guide/proxy/render visibility at or above the instance root, per purpose.
    PurposeVisibility purposeVisibility;
    // The instance root's own bindings, per purpose, resolved in the enclosing namespace, and the purposes
    // bound strongerThanDescendants at or above the instance root (see BoundMaterial).
    std::vector<std::pair<pxr::TfToken, pxr::SdfPath>> bindings;
    pxr::TfTokenVector strongPurposes;

    [[nodiscard]] pxr::SdfPath Map(const pxr::SdfPath &hydraPath) const {
        return hydraPath.ReplacePrefix(hydraNamespaceRoot, sourceNamespaceRoot);
    }
};

// UsdGeomImageable::ComputeEffectiveVisibility for the prim's own purpose, in one drawn copy: invisible if
// visibility is; otherwise default-purpose prims are visible, and the others take the nearest authored
// opinion for their purpose, in the prototype then up through the instance roots. With none, guides are
// invisible and proxy and render prims visible. Hydra doesn't image UsdGeomVisibilityAPI, so the opinions
// come from the source-info filter.
bool EffectivelyVisible(const PrimTable &table, const PrimRecord &prim, const DrawnCopy &copy);

// The material bound to a prim drawn in `copy`, for `purpose` falling back to allPurpose as UsdShade does.
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
pxr::SdfPath BoundMaterial(const PrimTable &table, const PrimRecord &prim, const DrawnCopy &copy,
                           const pxr::TfToken &purpose);

// WORKAROUND for OpenUSD #862: true if `path` or an ancestor below `prototypeRoot` resets the transform stack.
// In UsdGeom a reset inside an instance drops every ancestor's transform, the instance roots' included, but
// Hydra's instancers apply the instance's transform anyway, and its flattening marks every transform as
// resetting the stack, so the reset comes from the source-info filter. A prim drawn in a copy then takes its
// own flattened transform alone. Checked by tests/isolated/test_baseline.py, which also asserts the gap.
bool ResetsBelow(const PrimTable &table, pxr::SdfPath path, const pxr::SdfPath &prototypeRoot);

// The name of a point instancer's point `point` in a copy's instance context (see DrawnCopy).
pxr::TfToken PointName(size_t point);

class InstanceResolver {
public:
    // Diagnostics about malformed or unsupported instancers go to `diagnostics`. A point instancer's instances
    // have copies only with `pointInstancers` (PlanSettings).
    InstanceResolver(const PrimTable &table, Diagnostics &diagnostics, bool pointInstancers);

    // Every drawn copy of `prim`: outside instancing one, the identity, and none when unresolvable.
    const std::vector<DrawnCopy> &CopiesOf(const PrimRecord &prim);

private:
    const std::vector<DrawnCopy> &CopiesOf(const PrimRecord &prim, int depth);
    // The copies of everything under `prototypeRoot`, one per instance of each copy of `instancer`.
    const std::vector<DrawnCopy> &CopiesUnder(const pxr::SdfPath &instancer, const pxr::SdfPath &prototypeRoot,
                                              int depth);
    std::vector<DrawnCopy> Expand(const PrimRecord &instancer, const pxr::SdfPath &prototypeRoot, int depth);
    // Expand for a point instancer, whose topology is `topology`: one copy per point of prototype `prototype`,
    // in each copy of the instancer.
    std::vector<DrawnCopy> ExpandPoints(const PrimRecord &instancer, const InstancerRecord &topology, size_t prototype,
                                        int depth);
    void Report(const PrimRecord &prim, const std::string &code, const std::string &message);

    const PrimTable &table_;
    Diagnostics &diagnostics_;
    bool pointInstancers_;
    const std::vector<DrawnCopy> top_{DrawnCopy()};
    const std::vector<DrawnCopy> none_;
    std::unordered_map<pxr::SdfPath, std::vector<DrawnCopy>, pxr::SdfPath::Hash> cache_;  // by prototype root
};

}  // namespace hydra_bridge
