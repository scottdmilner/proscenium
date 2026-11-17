// Provisional (M6 plan, B3 and C11; M10 completes them): the drawn copies of a prim inside native instances or a point
// instancer's prototypes, mapped back from Hydra's instancers to composed-stage sources, as HdxPrimOriginInfo does:
// walk instancedBy upward and fold in each level's instanceLocations and instance transforms, or a point instancer's
// points. Sources and contexts are never Hydra paths or instance indices: a point instancer's copy is named by its
// point-instance path (DECISIONS.md "Point instancers").
#pragma once

#include <pxr/base/gf/matrix4d.h>
#include <pxr/pxr.h>
#include <pxr/usd/sdf/path.h>

#include <cstddef>
#include <string>
#include <unordered_map>
#include <vector>

#include "diagnostics.h"
#include "prim_record.h"

namespace proscenium {

// One drawn copy of a prototype's contents: where its Hydra namespace sits on the composed stage, its instance
// context, and the transform and visibility it takes from its instance roots.
struct DrawnCopy {
  PXR_NS::SdfPath hydraNamespaceRoot = PXR_NS::SdfPath::AbsoluteRootPath();
  PXR_NS::SdfPath sourceNamespaceRoot = PXR_NS::SdfPath::AbsoluteRootPath();
  PXR_NS::SdfPathVector instanceContext;        // native-instance roots on the composed stage, outermost first
  PXR_NS::GfMatrix4d instanceWorldMatrix{1.0};  // the innermost instance root's, USD's row-vector convention
  // The innermost native-instance root's Hydra path; empty outside native instancing and for a point's copy.
  PXR_NS::SdfPath hydraInstanceRoot;
  bool visible = true;  // every enclosing instancer's mask, which folds in each instance root's visibility
  // The nearest authored guide, proxy, and render visibility at or above the innermost instance root, per purpose.
  PurposeVisibility purposeVisibility;

  // The composed-stage path of the Hydra prim at `hydraPath` in this copy: an instance-proxy path inside instances.
  [[nodiscard]] PXR_NS::SdfPath MapHydraPathToSource(const PXR_NS::SdfPath& hydraPath) const {
    return hydraPath.ReplacePrefix(hydraNamespaceRoot, sourceNamespaceRoot);
  }
};

// The nearest authored visibility opinion for the prim's own purpose, in one drawn copy: in the prototype, then up
// through the instance roots. Null for a prim of the default purpose (Hydra's geometry), and for no opinion. Hydra
// doesn't image UsdGeomVisibilityAPI, so the opinions come from the source-info filter.
const PXR_NS::TfToken* PurposeVisibilityOpinion(const PrimTable& table, const PrimRecord& prim, const DrawnCopy& copy);

// UsdGeomImageable::ComputeEffectiveVisibility for the prim's own purpose, in one drawn copy: invisible if its
// visibility or its copy's is; otherwise a default-purpose prim is visible, and any other takes its nearest opinion,
// "inherited" included, as in UsdGeom. With none, a guide is invisible and a proxy or render prim visible. A guide
// is visible only when explicitly so (VIS-04).
bool EffectivelyVisible(const PrimTable& table, const PrimRecord& prim, const DrawnCopy& copy);

class InstanceResolver {
 public:
  // Reads instancers from `table`, which must outlive the resolver. `honorResets` false composes transforms as Hydra
  // does, ignoring a reset inside an instance: only the known-gap check for OpenUSD #862 asks for it.
  InstanceResolver(const PrimTable& table, bool honorResets);

  // Every drawn copy of `prim`, all with one hydraNamespaceRoot: outside instancing one, the identity; none under a
  // point instancer, and none when Hydra's instancing data can't be resolved, which the resolver reports once.
  const std::vector<DrawnCopy>& CopiesOf(const PrimRecord& prim);

  // WORKAROUND for OpenUSD #862: whether `path` or an ancestor below `prototypeRoot` resets the transform stack, so a
  // prim drawn in a copy rooted there takes its flattened transform alone. In UsdGeom a reset inside an instance drops
  // every ancestor's transform, the instance roots' included, but Hydra's instancers apply the instance's transform
  // anyway, and its flattening marks every transform as resetting the stack, so the reset comes from the source-info
  // filter. bpy_free/test_core_instancing.py's known-gap check fails once Hydra honors it. Always false without
  // honorResets_, and outside instancing, where the flattened transform is the world transform either way.
  [[nodiscard]] bool ResetsBelow(PXR_NS::SdfPath path, const PXR_NS::SdfPath& prototypeRoot) const;

  // What it found unresolvable so far, as the bridge's resolver reports it, in the order found.
  [[nodiscard]] const std::vector<Diagnostic>& Diagnostics() const { return diagnostics_; }

 private:
  const std::vector<DrawnCopy>& CopiesOf(const PrimRecord& prim, int depth);
  // The copies of everything under `prototypeRoot`, one per instance of each copy of `instancer`; Expand reads
  // `topology`, the instancer's own.
  const std::vector<DrawnCopy>& CopiesUnder(const PXR_NS::SdfPath& instancer, const PXR_NS::SdfPath& prototypeRoot,
                                            int depth);
  std::vector<DrawnCopy> Expand(const PrimRecord& instancer, const InstancerRecord& topology,
                                const PXR_NS::SdfPath& prototypeRoot, int depth);
  // A point instancer's copies of prototype `p`: one per point drawing it, of each copy of the instancer.
  std::vector<DrawnCopy> ExpandPoints(const PrimRecord& instancer, const InstancerRecord& topology, std::size_t p,
                                      int depth);
  // Instancers are reported by Hydra path in the message: a native instancer has no source entity.
  void Report(const PXR_NS::SdfPath& hydraPath, DiagnosticCode code, const std::string& message);

  const PrimTable& table_;
  bool honorResets_;
  const std::vector<DrawnCopy> top_{DrawnCopy()};
  const std::vector<DrawnCopy> none_;
  std::unordered_map<PXR_NS::SdfPath, std::vector<DrawnCopy>, PXR_NS::SdfPath::Hash> cache_;  // by prototype root
  std::vector<Diagnostic> diagnostics_;
};

}  // namespace proscenium
