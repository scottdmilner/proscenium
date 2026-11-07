#include "plan.h"

#include <pxr/base/gf/range3d.h>
#include <pxr/imaging/hd/tokens.h>

#include <algorithm>
#include <cmath>
#include <optional>
#include <stdexcept>
#include <utility>
#include <vector>

#include "instancing.h"
#include "prim_reader.h"

PXR_NAMESPACE_USING_DIRECTIVE

namespace proscenium {
namespace {

// Temporary: what M5's minimal planner reads of a drawn copy of a gprim.
struct DrawnGprim {
  SdfPath source;                   // on the composed stage, never a Hydra path
  SdfPathVector instanceContext;    // native-instance roots, outermost first
  GfMatrix4d world{1.0};            // USD's row-vector convention
  std::optional<GfRange3d> bounds;  // local; absent when Hydra gives the gprim no extent
};

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
    for (const DrawnCopy& copy : copies) {
      DrawnGprim gprim{copy.Map(prim.path), copy.context, resets ? local : local * copy.world, prim.extent};
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

PlanningContext::PlanningContext(double scale, int version) : unitScale(scale), representationVersion(version) {
  if (!std::isfinite(unitScale) || unitScale <= 0.0) throw std::invalid_argument("A unit scale is positive and finite");
}

PlanPtr BuildPlan(const Snapshot& snapshot, const PlanningContext& context) {
  if (context.representationVersion != 1)
    throw std::invalid_argument("The planner plans representation version 1 only");
  auto plan = std::make_shared<Plan>(Plan{snapshot.time, context, {}, {}, {}, {}});
  const PrimTable table = ReadPrims(snapshot);
  InstanceResolver instances(table, /*honorResets=*/true);
  for (const DrawnGprim& gprim : DrawnGprims(table, instances)) {
    // Each copy has one object, and its source entity is its source path, an instance-proxy path inside instances.
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
    plan->correspondence.push_back({placeholder.object, gprim.source, gprim.instanceContext});
    plan->placeholders.push_back(std::move(placeholder));
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
