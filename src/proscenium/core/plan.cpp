#include "plan.h"

#include <pxr/base/gf/range3d.h>
#include <pxr/imaging/hd/tokens.h>
#include <pxr/usd/usdGeom/imageable.h>
#include <pxr/usd/usdGeom/tokens.h>

#include <algorithm>
#include <cmath>
#include <cstddef>
#include <optional>
#include <stdexcept>
#include <unordered_map>
#include <utility>
#include <vector>

#include "instancing.h"
#include "prim_reader.h"

PXR_NAMESPACE_USING_DIRECTIVE

namespace proscenium {
namespace {

// What the planner reads of a drawn copy of a gprim.
struct DrawnGprim {
  SdfPath source;                   // on the composed stage, never a Hydra path
  SdfPathVector instanceContext;    // native-instance roots, outermost first
  GfMatrix4d world{1.0};            // USD's row-vector convention
  std::optional<GfRange3d> bounds;  // local; absent when Hydra gives the gprim no extent
  const PrimRecord* mesh;           // the Hydra mesh it is a copy of; null for any other gprim
  TfToken purpose;                  // USD's name
  bool visible;                     // effectively, for its own purpose
  bool explicitGuide;               // a guide whose nearest guideVisibility opinion is visible
};

// (min x, min y, min z, max x, max y, max z) appended to `values`.
void AppendBounds(const GfRange3d& bounds, VtFloatArray& values) {
  for (const GfVec3d& corner : {bounds.GetMin(), bounds.GetMax()})
    for (std::size_t i = 0; i < GfVec3d::dimension; ++i) values.push_back(static_cast<float>(corner[i]));
}

// The matrix's 16 elements appended to `values` in USD's row-major layout, which is Blender's column-major one: USD
// multiplies row vectors and Blender column vectors, so each holds the other's transpose.
void AppendWorld(const GfMatrix4d& world, VtFloatArray& values) {
  for (int row = 0; row < 4; ++row) {
    const GfVec4d elements = world.GetRow(row);
    for (std::size_t column = 0; column < GfVec4d::dimension; ++column)
      values.push_back(static_cast<float>(elements[column]));
  }
}

// The prim's purpose in USD's names: Hydra names USD's default geometry, and an unimaged prim can lack one.
TfToken UsdPurpose(const PrimRecord& prim) {
  return prim.purpose.IsEmpty() || prim.purpose == HdRenderTagTokens->geometry ? UsdGeomTokens->default_ : prim.purpose;
}

bool Includes(const TfTokenVector& purposes, const TfToken& purpose) {
  return std::find(purposes.begin(), purposes.end(), purpose) != purposes.end();
}

// Whether the prim is a gprim: by its Hydra type, or for a prim Hydra doesn't image, by its USD type.
bool IsGprim(const PrimRecord& prim) { return HdPrimTypeIsGprim(prim.type) || prim.isGprim; }

// A drawn copy of each gprim in `table`, sorted by source, with its world transform composed by `instances`.
std::vector<DrawnGprim> DrawnGprims(const PrimTable& table, InstanceResolver& instances) {
  std::vector<DrawnGprim> gprims;
  for (const PrimRecord& prim : table.prims) {
    if (!IsGprim(prim)) continue;
    const std::vector<DrawnCopy>& copies = instances.CopiesOf(prim);
    if (copies.empty()) continue;
    // Flattened: in its prototype's namespace inside instances, else the world.
    const GfMatrix4d local = prim.matrix.value_or(GfMatrix4d(1.0));
    // A reset inside the prototype drops the instance's transform too (WORKAROUND for OpenUSD #862). Every copy has
    // the same hydraRoot, so it is checked once.
    const bool resets = instances.ResetsBelow(prim.path, copies.front().hydraRoot);
    const PrimRecord* mesh = prim.type == HdPrimTypeTokens->mesh ? &prim : nullptr;
    const TfToken purpose = UsdPurpose(prim);
    for (const DrawnCopy& copy : copies) {
      const TfToken* opinion = PurposeVisibilityOpinion(table, prim, copy);
      const bool explicitGuide = purpose == UsdGeomTokens->guide && opinion && *opinion == UsdGeomTokens->visible;
      DrawnGprim gprim{copy.Map(prim.path),
                       copy.context,
                       resets ? local : local * copy.world,
                       prim.extent,
                       mesh,
                       purpose,
                       EffectivelyVisible(table, prim, copy),
                       explicitGuide};
      // Outside instancing, the stage scene index names a prim by its USD path, and the filtering scene indices
      // that convert it keep that.
      if (copy.context.empty() && !prim.originPath.IsEmpty()) gprim.source = prim.originPath;
      gprims.push_back(std::move(gprim));
    }
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

PlanSettings::PlanSettings(TfTokenVector viewport, TfTokenVector render)
    : viewportPurposes(std::move(viewport)), renderPurposes(std::move(render)) {
  for (TfTokenVector* purposes : {&viewportPurposes, &renderPurposes}) {
    for (const TfToken& purpose : *purposes)
      if (!Includes(UsdGeomImageable::GetOrderedPurposeTokens(), purpose))
        throw std::invalid_argument("Not a USD purpose: " + purpose.GetString());
    std::sort(purposes->begin(), purposes->end());
    purposes->erase(std::unique(purposes->begin(), purposes->end()), purposes->end());
  }
}

PlanningContext::PlanningContext(double scale, int version) : unitScale(scale), representationVersion(version) {
  if (!std::isfinite(unitScale) || unitScale <= 0.0) throw std::invalid_argument("A unit scale is positive and finite");
}

PlanPtr BuildPlan(const Snapshot& snapshot, const PlanSettings& settings, const PlanningContext& context) {
  if (context.representationVersion != 1)
    throw std::invalid_argument("The planner plans representation version 1 only");
  auto plan = std::make_shared<Plan>(Plan{snapshot.time, context, {}, {}, {}, {}, {}, {}, {}, {}, {}, {}, {}});
  TfTokenVector viewport = settings.viewportPurposes;
  if (!Includes(viewport, UsdGeomTokens->guide)) viewport.push_back(UsdGeomTokens->guide);
  const PrimTable table = ReadPrims(snapshot);
  InstanceResolver instances(table, /*honorResets=*/true);
  const std::vector<DrawnGprim> gprims = DrawnGprims(table, instances);
  plan->copyWorlds.reserve(16 * gprims.size());
  // Each mesh's description, made for its first copy in source order, so its source is deterministic.
  std::unordered_map<const PrimRecord*, int> geometries;
  for (const DrawnGprim& gprim : gprims) {
    const bool inViewport = Includes(viewport, gprim.purpose);
    const bool inRender = Includes(settings.renderPurposes, gprim.purpose);
    // A guide shows only where it is explicitly visible, so one that isn't is never displayed.
    if ((!inViewport && !inRender) || (gprim.purpose == UsdGeomTokens->guide && !gprim.explicitGuide)) continue;
    plan->copyViewport.push_back(gprim.visible && inViewport);
    plan->copyRender.push_back(gprim.visible && inRender);
    // Each copy has one object, and its source entity is its source path, an instance-proxy path inside instances.
    const std::size_t object = plan->resources.size();
    const std::size_t boundsMesh = object + 1;
    plan->partitions.push_back({{object, boundsMesh}});
    plan->resources.push_back({Role::kObject, gprim.source, 0, {gprim.source}, {boundsMesh}});
    plan->resources.push_back({Role::kBoundsMesh, gprim.source, 0, {gprim.source}, {}});
    plan->correspondence.push_back({object, gprim.source, gprim.instanceContext});
    AppendWorld(gprim.world, plan->copyWorlds);
    plan->copyObjects.push_back(static_cast<int>(object));
    int geometry = -1;
    int placeholder = -1;
    if (gprim.mesh) {
      const auto [found, added] = geometries.try_emplace(gprim.mesh, static_cast<int>(plan->geometries.size()));
      if (added) {
        GeometryDescription description{gprim.source, {}, gprim.source.GetString()};
        if (gprim.bounds) AppendBounds(*gprim.bounds, description.extent);
        plan->geometries.push_back(std::move(description));
      }
      geometry = found->second;
    } else if (gprim.bounds) {
      placeholder = static_cast<int>(plan->placeholderBounds.size() / 6);
      AppendBounds(*gprim.bounds, plan->placeholderBounds);
    }
    plan->copyGeometries.push_back(geometry);
    plan->copyPlaceholders.push_back(placeholder);
  }
  return plan;
}

std::vector<std::pair<SdfPath, GfMatrix4d>> HydraComposedWorlds(const Snapshot& snapshot) {
  const PrimTable table = ReadPrims(snapshot);
  InstanceResolver instances(table, /*honorResets=*/false);
  std::vector<std::pair<SdfPath, GfMatrix4d>> worlds;
  for (const DrawnGprim& gprim : DrawnGprims(table, instances)) worlds.emplace_back(gprim.source, gprim.world);
  return worlds;
}

}  // namespace proscenium
