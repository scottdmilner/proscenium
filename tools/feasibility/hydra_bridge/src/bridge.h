// The object Python holds: a caller's stage and the retained scene-index graph over it.
#pragma once

#include "scene_index_graph.h"
#include "snapshot.h"

#include <pxr/pxr.h>
#include <pxr/usd/usd/stage.h>

#include <memory>

namespace hydra_bridge {

class Bridge {
public:
    // Raises Tf errors posted while building the graph.
    explicit Bridge(const pxr::UsdStageRefPtr &stage);

    // Weak: the caller owns the stage. Null once it has expired.
    pxr::UsdStagePtr Stage() const { return stage_; }

    // Drops the graph, whose stage scene index holds a strong stage reference, so a
    // caller-released stage can expire.
    void Release() { graph_.reset(); }

    // Call without the GIL.
    SnapshotPtr Capture(pxr::UsdTimeCode time);

private:
    pxr::UsdStagePtr stage_;
    std::unique_ptr<SceneIndexGraph> graph_;
};

}  // namespace hydra_bridge
