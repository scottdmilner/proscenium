// What a new plan changes from the plan of the generation the destination shows (change-matrix.md "Actions"), ported
// from the bridge's plan_diff for M7's content. Change discovery proposes what a capture re-reads; this comparison of
// planned content decides what a refresh writes (incremental.md "Affected Content"), so an unchanged plan changes
// nothing.
//
// Drawn copies are matched by identity, their source entity: the source path and instance context. A destination
// isn't part of it, so a change of participation is a local update of hide flags. A matched copy is compared in what
// application applies of it: whether its partition holds a bounds mesh and a shear parent, its world matrix and shear
// split, its local bounds, which its bounds mesh draws, and each destination's participation. Values compare by their
// bits, as the plan holds them in Blender's float32, since planning is deterministic over its inputs (PLAN-08). Each
// bounds mesh belongs to its copy's partition, so it compares with its counterpart's only, where the bridge's meshes,
// shared by content, matched any equal mesh by hash; M8's shared meshes bring that back. The comparison runs over the
// whole plan; narrowing it by notices is M13's.
#pragma once

#include <pxr/base/vt/array.h>
#include <pxr/pxr.h>

#include "plan.h"

namespace proscenium {

// Copy indices, each list in the order of the plan it indexes.
struct PlanDiff {
  // Per new copy: the previous plan's copy with its identity, or -1 for one to build. An identity the new plan repeats
  // matches once; the planner gives each copy its own.
  PXR_NS::VtIntArray previousCopyIndices;
  // New copies with a counterpart whose partition holds other resources, a bounds mesh or shear parent that appears or
  // vanishes, so the partition is prepared anew: a Blender object's type is fixed, and its parent would change.
  PXR_NS::VtIntArray rebuiltCopyIndices;
  // New copies with a counterpart whose partition holds the same resources, updated in place where they differ; a copy
  // can be in more than one list. Moved: its world matrix, and a sheared copy's split, differ. Bounds changed: its
  // local bounds differ, so its bounds mesh is replaced and its object pointed at the replacement. Participation
  // changed: whether it displays in either destination differs, so its hide flags change.
  PXR_NS::VtIntArray movedCopyIndices;
  PXR_NS::VtIntArray boundsChangedCopyIndices;
  PXR_NS::VtIntArray participationChangedCopyIndices;
  PXR_NS::VtIntArray removedPreviousCopyIndices;  // previous copies with no new counterpart
};

// Runs without the GIL.
PlanDiff DiffPlans(const Plan& previous, const Plan& plan);

}  // namespace proscenium
