// Provisional (M6 plan, B3; M10 completes them): the drawn copies of a prim inside native instances, mapped back from
// Hydra's instancers to composed-stage sources, as HdxPrimOriginInfo does: walk instancedBy upward and fold in each
// level's instanceLocations and instance transforms. Sources and contexts are never Hydra paths or instance indices.
// Visibility through instancers is C2's; a point instancer's prototypes have no copies (DEFER-01).
#pragma once

#include <pxr/base/gf/matrix4d.h>
#include <pxr/pxr.h>
#include <pxr/usd/sdf/path.h>

#include <unordered_map>
#include <vector>

#include "prim_record.h"

namespace proscenium {

// One drawn copy of a prototype's contents: where its Hydra namespace sits on the composed stage, its instance
// context, and the transform it takes from its instance roots.
struct DrawnCopy {
  PXR_NS::SdfPath hydraRoot = PXR_NS::SdfPath::AbsoluteRootPath();
  PXR_NS::SdfPath usdRoot = PXR_NS::SdfPath::AbsoluteRootPath();
  PXR_NS::SdfPathVector context;  // native-instance roots on the composed stage, outermost first
  PXR_NS::GfMatrix4d world{1.0};  // the innermost instance root's, USD's row-vector convention

  // The composed-stage path of the Hydra prim at `hydraPath` in this copy: an instance-proxy path inside instances.
  [[nodiscard]] PXR_NS::SdfPath Map(const PXR_NS::SdfPath& hydraPath) const {
    return hydraPath.ReplacePrefix(hydraRoot, usdRoot);
  }
};

class InstanceResolver {
 public:
  // Reads instancers from `table`, which must outlive the resolver. `honorResets` false composes transforms as Hydra
  // does, ignoring a reset inside an instance: only the known-gap check for OpenUSD #862 asks for it.
  InstanceResolver(const PrimTable& table, bool honorResets);

  // Every drawn copy of `prim`, all with one hydraRoot: outside instancing one, the identity; none under a point
  // instancer, and none when Hydra's instancing data can't be resolved (C6 reports it).
  const std::vector<DrawnCopy>& CopiesOf(const PrimRecord& prim);

  // WORKAROUND for OpenUSD #862: whether `path` or an ancestor below `prototypeRoot` resets the transform stack, so a
  // prim drawn in a copy rooted there takes its flattened transform alone. In UsdGeom a reset inside an instance drops
  // every ancestor's transform, the instance roots' included, but Hydra's instancers apply the instance's transform
  // anyway, and its flattening marks every transform as resetting the stack, so the reset comes from the source-info
  // filter. bpy_free/test_core_instancing.py's known-gap check fails once Hydra honors it. Always false without
  // honorResets_, and outside instancing, where the flattened transform is the world transform either way.
  [[nodiscard]] bool ResetsBelow(PXR_NS::SdfPath path, const PXR_NS::SdfPath& prototypeRoot) const;

 private:
  const std::vector<DrawnCopy>& CopiesOf(const PrimRecord& prim, int depth);
  // The copies of everything under `prototypeRoot`, one per instance of each copy of `instancer`; Expand reads
  // `topology`, the instancer's own.
  const std::vector<DrawnCopy>& CopiesUnder(const PXR_NS::SdfPath& instancer, const PXR_NS::SdfPath& prototypeRoot,
                                            int depth);
  std::vector<DrawnCopy> Expand(const PrimRecord& instancer, const InstancerRecord& topology,
                                const PXR_NS::SdfPath& prototypeRoot, int depth);

  const PrimTable& table_;
  bool honorResets_;
  const std::vector<DrawnCopy> top_{DrawnCopy()};
  const std::vector<DrawnCopy> none_;
  std::unordered_map<PXR_NS::SdfPath, std::vector<DrawnCopy>, PXR_NS::SdfPath::Hash> cache_;  // by prototype root
};

}  // namespace proscenium
