// M4: what a new plan changes from the published one. Change discovery proposes work; this comparison of
// evaluated content decides it (spec incremental.md, Affected Content), so an unchanged plan changes nothing.
#pragma once

#include "plan.h"

#include <vector>

namespace hydra_bridge {

struct PlanDiff {
    // Per new mesh: an old mesh with equal content (B5's), or -1 for one to build.
    std::vector<int> previousMeshIndices;
    // Per new material: an old material equal in everything the plan holds, or -1 for one to build.
    std::vector<int> previousMaterialIndices;
    // Per new object: the old object with its identity (source, instance context, and the destinations it
    // displays in), or -1 for an added one.
    std::vector<int> previousObjectIndices;
    // New objects with an old counterpart that differs in anything the plan holds, its mesh and materials
    // compared through `previousMeshIndices` and `previousMaterialIndices`, in plan order.
    std::vector<int> changedObjectIndices;
    // The changed objects that differ only in their mesh or materials: users of a rebuilt one, which an update
    // may move onto it rather than replace. In plan order.
    std::vector<int> repointableObjectIndices;
    // The changed objects whose world matrix differs, and otherwise at most their mesh or materials: what an update
    // may keep and move, repointing it too if its data changed (M4 Phase E). In plan order.
    std::vector<int> movedObjectIndices;
    std::vector<int> removedPreviousObjectIndices;  // old objects with no new counterpart, in plan order
};

// Call without the GIL.
PlanDiff DiffPlans(const Plan &published, const Plan &next);

}  // namespace hydra_bridge
