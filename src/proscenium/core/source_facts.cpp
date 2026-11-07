#include "source_facts.h"

#include <pxr/base/gf/vec3d.h>
#include <pxr/base/vt/array.h>
#include <pxr/imaging/hd/extentSchema.h>
#include <pxr/imaging/hd/retainedDataSource.h>
#include <pxr/usd/usdGeom/boundable.h>
#include <pxr/usd/usdGeom/gprim.h>
#include <pxr/usd/usdGeom/mesh.h>
#include <pxr/usd/usdGeom/nurbsPatch.h>
#include <pxr/usd/usdGeom/pointBased.h>
#include <pxr/usd/usdGeom/xformable.h>

#include <utility>
#include <vector>

PXR_NAMESPACE_USING_DIRECTIVE

namespace proscenium {

const TfToken& SourceInfoTokens::Schema() {
  static const TfToken token("prosceniumSource");
  return token;
}

const TfToken& SourceInfoTokens::IsGprim() {
  static const TfToken token("isGprim");
  return token;
}

const TfToken& SourceInfoTokens::ResetsXformStack() {
  static const TfToken token("resetsXformStack");
  return token;
}

LazyContainer::LazyContainer(std::function<HdContainerDataSourceHandle()> build, std::function<uint64_t()> generation)
    : build_(std::move(build)), generation_(std::move(generation)) {}

HdContainerDataSourceHandle LazyContainer::Built() {
  const uint64_t generation = generation_();
  const std::scoped_lock lock(mutex_);
  if (!valid_ || generation != builtAt_) {
    built_ = build_();
    builtAt_ = generation;
    valid_ = true;
  }
  return built_;
}

TfTokenVector LazyContainer::GetNames() {
  const HdContainerDataSourceHandle built = Built();
  return built ? built->GetNames() : TfTokenVector();
}

HdDataSourceBaseHandle LazyContainer::Get(const TfToken& name) {
  const HdContainerDataSourceHandle built = Built();
  return built ? built->Get(name) : nullptr;
}

HdContainerDataSourceHandle SourceInfo(const UsdPrim& prim, bool imaged) {
  TfTokenVector names;
  std::vector<HdDataSourceBaseHandle> values;
  const HdDataSourceBaseHandle yes = HdRetainedTypedSampledDataSource<bool>::New(true);
  // A HermiteCurves is a gprim Hydra has no adapter data for, so the planner can still give it a placeholder.
  if (!imaged && prim.IsA<UsdGeomGprim>()) {
    names.push_back(SourceInfoTokens::IsGprim());
    values.push_back(yes);
  }
  // WORKAROUND for OpenUSD #862 (ResetsBelow in instancing.h): Hydra marks every flattened transform as resetting the
  // stack, so only USD can say which prims reset it.
  if (const UsdGeomXformable xformable{prim}; xformable && xformable.GetResetXformStack()) {
    names.push_back(SourceInfoTokens::ResetsXformStack());
    values.push_back(yes);
  }
  if (names.empty()) return nullptr;
  return HdRetainedContainerDataSource::New(names.size(), names.data(), values.data());
}

// Point instancers and volumes are left out: their extents would mean evaluating prototypes or reading field files
// merely for a placeholder.
bool ComputesExtent(const UsdPrim& prim) {
  return prim.IsA<UsdGeomPointBased>() && !prim.IsA<UsdGeomMesh>() && !prim.IsA<UsdGeomNurbsPatch>();
}

HdContainerDataSourceHandle ComputedExtent(const UsdPrim& prim, UsdTimeCode time) {
  if (!ComputesExtent(prim)) return nullptr;
  VtVec3fArray extent;
  if (!UsdGeomBoundable::ComputeExtentFromPlugins(UsdGeomBoundable(prim), time, &extent) || extent.size() != 2)
    return nullptr;
  return HdRetainedContainerDataSource::New(
      HdExtentSchema::GetSchemaToken(), HdExtentSchema::Builder()
                                            .SetMin(HdRetainedTypedSampledDataSource<GfVec3d>::New(GfVec3d(extent[0])))
                                            .SetMax(HdRetainedTypedSampledDataSource<GfVec3d>::New(GfVec3d(extent[1])))
                                            .Build());
}

}  // namespace proscenium
