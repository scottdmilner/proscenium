// M4 Phase D (D8): the plan objects that batch.py's batched display shows as instances of one batch, grouped in
// the planner's module so an update needn't convert and regroup every plan record in Python.
//
// Objects share a group when they have the same mesh, material slots, and destinations, the same object color
// (their constant displayColor and displayOpacity of one value each, or opaque white), and constant primvars of
// the same names and attribute kinds, strings aside, which batches leave out. A placeholder, and an object with a
// primvar no point attribute holds, are in no group. Objects whose transforms are equal in float32, as Blender
// stores them, go to separate groups, each a repeat: a pick names an instance by its prototype and world matrix.
#pragma once

#include "plan.h"

#include <array>
#include <cstddef>
#include <string>
#include <utility>
#include <vector>

namespace hydra_bridge {

struct BatchGroup {
    // What the group's instances share, as batch.py keys a batch.
    int mesh = -1;
    std::vector<int> materialSlots;  // -1 for no material
    bool inViewport = false;
    bool inRender = false;
    std::array<double, 4> color{1.0, 1.0, 1.0, 1.0};
    // (primvar, Blender attribute data type), by name: BOOLEAN, INT, FLOAT, FLOAT2, or FLOAT_VECTOR.
    std::vector<std::pair<std::string, std::string>> kinds;
    int repeat = 0;            // among groups with the same key, by coincident transform
    std::vector<int> members;  // plan object indices, ascending
};

struct BatchGroups {
    std::vector<BatchGroup> groups;  // of at least `minimum` members, in order of their first member
    std::vector<int> single;         // every other object, ascending
};

// Call without the GIL.
BatchGroups GroupForBatches(const Plan &plan, std::size_t minimum);

}  // namespace hydra_bridge
