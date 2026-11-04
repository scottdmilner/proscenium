#include "plan.h"

#include <cmath>
#include <stdexcept>
#include <utility>

PXR_NAMESPACE_USING_DIRECTIVE

namespace proscenium {

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
  for (const DrawnGprim& gprim : snapshot.gprims) {
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
