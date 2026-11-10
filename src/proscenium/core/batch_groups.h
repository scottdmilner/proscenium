// The drawn copies a batch shows as instances of one prototype (DECISIONS.md "Display representation", M4 D8), grouped
// in the core, as the bridge's batch_groups groups plan objects, so application needn't regroup every copy in Python.
//
// Copies share a group when they have the same geometry description and destinations. Provisional: material slots (M9)
// and object color and constant primvars' kinds (M10) join the key as the plan gains them, string primvars aside, which
// batches leave out. A placeholder or marker is in no group. Copies whose world transforms are equal in float32, as
// Blender stores them, go to separate groups, each a repeat: a pick names an instance by its prototype and world
// matrix.
#pragma once

#include <pxr/base/vt/array.h>
#include <pxr/pxr.h>

#include <cstddef>
#include <vector>

#include "plan.h"

namespace proscenium {

struct BatchGroup {
  // What the group's instances share.
  int geometry = -1;  // in Plan::geometries
  bool viewport = false;
  bool render = false;
  int coincidentCopyIndex = 0;  // among groups with the same key, by coincident world transform
  PXR_NS::VtIntArray members;   // copy indices, ascending
};

struct BatchGroups {
  std::vector<BatchGroup> groups;  // of at least the minimum members, in order of their first member
  PXR_NS::VtIntArray single;       // every other copy, ascending
};

// Groups `plan`'s copies, keeping a group of fewer than `minimum` copies as single copies. Runs without the GIL.
BatchGroups GroupForBatches(const Plan& plan, std::size_t minimum);

}  // namespace proscenium
