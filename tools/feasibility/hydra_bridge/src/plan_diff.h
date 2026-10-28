// M4: what a new plan changes from the published one. Change discovery proposes work; this comparison of
// evaluated content decides it (spec incremental.md, Affected Content), so an unchanged plan changes nothing.
#pragma once

#include "plan.h"

#include <vector>

namespace hydra_bridge {

struct PlanDiff {
    // Per new mesh: an old mesh with equal content (B5's), or -1 for one to build.
    std::vector<int> meshes;
    // Per new material: an old material equal in everything the plan holds, or -1 for one to build.
    std::vector<int> materials;
    // Per new object: the old object with its identity (source, instance context, and the destinations it
    // displays in), or -1 for an added one.
    std::vector<int> objects;
    // New objects with an old counterpart that differs in anything the plan holds, its mesh and materials
    // compared through `meshes` and `materials`, in plan order.
    std::vector<int> changed;
    std::vector<int> removed;  // old objects with no new counterpart, in plan order
};

// Call without the GIL.
PlanDiff DiffPlans(const Plan &published, const Plan &next);

}  // namespace hydra_bridge
