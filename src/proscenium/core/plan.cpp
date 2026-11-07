#include "plan.h"

#include <pxr/base/gf/range3d.h>
#include <pxr/imaging/hd/extentSchema.h>
#include <pxr/imaging/hd/instancedBySchema.h>
#include <pxr/imaging/hd/primOriginSchema.h>
#include <pxr/imaging/hd/sceneIndexPrimView.h>
#include <pxr/imaging/hd/tokens.h>
#include <pxr/imaging/hd/xformSchema.h>

#include <algorithm>
#include <cmath>
#include <optional>
#include <stdexcept>
#include <utility>
#include <vector>

#include "source_facts.h"

PXR_NAMESPACE_USING_DIRECTIVE

namespace proscenium {
namespace {

// The snapshot's data sources are static copies; offset 0 is their only sample.
constexpr HdSampledDataSource::Time kNow = 0.0F;

// Temporary: what M5's minimal planner reads of a drawn gprim outside native and point instancing.
struct DrawnGprim {
  SdfPath source;                   // on the composed stage, never a Hydra path
  GfMatrix4d world{1.0};            // USD's row-vector convention
  std::optional<GfRange3d> bounds;  // local; absent when Hydra gives the gprim no extent
};

// Whether the prim is a gprim: by its Hydra type, or for a prim Hydra doesn't image, by its USD type.
bool IsGprim(const HdSceneIndexPrim& prim) {
  if (HdPrimTypeIsGprim(prim.primType)) return true;
  const auto info = HdContainerDataSource::Cast(prim.dataSource->Get(SourceInfoTokens::Schema()));
  const auto isGprim = info ? HdBoolDataSource::Cast(info->Get(SourceInfoTokens::IsGprim())) : nullptr;
  return isGprim && isGprim->GetTypedValue(kNow);
}

// The gprim's values, or nothing for a prim the minimal planner doesn't draw: one that isn't a gprim, or one under
// native or point instancing, whose source and instance context M6's planner derives.
std::optional<DrawnGprim> ReadGprim(const HdSceneIndexPrim& prim, const SdfPath& path) {
  if (!prim.dataSource || !IsGprim(prim)) return std::nullopt;
  if (HdInstancedBySchema::GetFromParent(prim.dataSource)) return std::nullopt;
  DrawnGprim gprim;
  // Outside instancing, the stage scene index names a prim by its USD path, and the filtering scene indices that
  // convert it keep that.
  const SdfPath origin =
      HdPrimOriginSchema::GetFromParent(prim.dataSource).GetOriginPath(HdPrimOriginSchemaTokens->scenePath);
  gprim.source = origin.IsEmpty() ? path : origin;
  if (const HdMatrixDataSourceHandle matrix = HdXformSchema::GetFromParent(prim.dataSource).GetMatrix())
    gprim.world = matrix->GetTypedValue(kNow);
  if (const HdExtentSchema extent = HdExtentSchema::GetFromParent(prim.dataSource)) {
    const HdVec3dDataSourceHandle min = extent.GetMin();
    const HdVec3dDataSourceHandle max = extent.GetMax();
    if (min && max) gprim.bounds = GfRange3d(min->GetTypedValue(kNow), max->GetTypedValue(kNow));
  }
  return gprim;
}

std::vector<DrawnGprim> DrawnGprims(const Snapshot& snapshot) {
  std::vector<DrawnGprim> gprims;
  for (const SdfPath& path : HdSceneIndexPrimView(snapshot.scene, SdfPath::AbsoluteRootPath())) {
    if (std::optional<DrawnGprim> gprim = ReadGprim(snapshot.scene->GetPrim(path), path))
      gprims.push_back(std::move(*gprim));
  }
  std::sort(gprims.begin(), gprims.end(), [](const DrawnGprim& a, const DrawnGprim& b) { return a.source < b.source; });
  return gprims;
}

}  // namespace

const char* RoleName(Role role) {
  switch (role) {
    case Role::kObject:
      return "object";
    case Role::kBoundsMesh:
      return "bounds mesh";
  }
  throw std::invalid_argument("Not a representation role");
}

PlanningContext::PlanningContext(double scale, int version) : unitScale(scale), representationVersion(version) {
  if (!std::isfinite(unitScale) || unitScale <= 0.0) throw std::invalid_argument("A unit scale is positive and finite");
}

PlanPtr BuildPlan(const Snapshot& snapshot, const PlanningContext& context) {
  if (context.representationVersion != 1)
    throw std::invalid_argument("The planner plans representation version 1 only");
  auto plan = std::make_shared<Plan>(Plan{snapshot.time, context, {}, {}, {}, {}});
  for (const DrawnGprim& gprim : DrawnGprims(snapshot)) {
    // M5 captures no instancing, so each copy has one object, and its source entity is its source path.
    const std::size_t object = plan->resources.size();
    Placeholder placeholder{object, object + 1, gprim.world, {}};
    if (gprim.bounds) {
      const GfVec3d& min = gprim.bounds->GetMin();
      const GfVec3d& max = gprim.bounds->GetMax();
      placeholder.bounds = {static_cast<float>(min[0]), static_cast<float>(min[1]), static_cast<float>(min[2]),
                            static_cast<float>(max[0]), static_cast<float>(max[1]), static_cast<float>(max[2])};
    }
    plan->partitions.push_back({{placeholder.object, placeholder.boundsMesh}});
    plan->resources.push_back({Role::kObject, gprim.source, 0, {gprim.source}, {placeholder.boundsMesh}});
    plan->resources.push_back({Role::kBoundsMesh, gprim.source, 0, {gprim.source}, {}});
    plan->correspondence.push_back({placeholder.object, gprim.source});
    plan->placeholders.push_back(std::move(placeholder));
  }
  return plan;
}

}  // namespace proscenium
