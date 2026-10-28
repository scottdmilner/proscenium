// BuildCorrespondence: floors and the browsing universe, from a plan's objects.
#include "correspondence.h"

#include "plan.h"

#include <algorithm>

PXR_NAMESPACE_USING_DIRECTIVE

namespace hydra_bridge {

Correspondence BuildCorrespondence(const Plan &plan) {
    Correspondence correspondence;
    correspondence.floors.reserve(plan.objects.size());
    for (const ObjectEntry &object : plan.objects) {
        const SdfPath &floor = object.instanceContext.empty() ? object.source : object.instanceContext.front();
        correspondence.floors.push_back(floor);
        // Only the viewport destination's elements make prims browsable; render-only content doesn't.
        if (!object.inViewport) continue;
        for (SdfPath path = floor; !path.IsEmpty() && !path.IsAbsoluteRootPath(); path = path.GetParentPath())
            correspondence.universe.push_back(path);
    }
    SdfPathVector &universe = correspondence.universe;
    std::sort(universe.begin(), universe.end());
    universe.erase(std::unique(universe.begin(), universe.end()), universe.end());
    return correspondence;
}

}  // namespace hydra_bridge
