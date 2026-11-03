// The correspondence layer's part of a plan (interaction contract, "Two Layers and the Live Stage"). Each
// object is one display element, and its source and instance context are its source entity; this holds what
// the contract derives from them. Paths are USD paths.
#pragma once

#include <pxr/pxr.h>
#include <pxr/usd/sdf/path.h>

#include <cstddef>
#include <utility>
#include <vector>

namespace hydra_bridge {

struct Plan;

struct Correspondence {
    // Per plan object, by index: its source entity's floor, the outermost native-instance root enclosing it
    // (the first of its instance context), or the source itself outside instance contents.
    pxr::SdfPathVector floors;
    // The browsing universe: the floors of the viewport's display elements and every prefix of them but the
    // absolute root. Sorted and unique; SdfPath's order keeps each prim's subtree one contiguous range.
    pxr::SdfPathVector universe;
    // The viewport's display elements as (floor, plan object index), sorted, so the elements beneath a prim
    // are one range, as in the universe.
    std::vector<std::pair<pxr::SdfPath, std::size_t>> elements;
};

Correspondence BuildCorrespondence(const Plan &plan);

}  // namespace hydra_bridge
