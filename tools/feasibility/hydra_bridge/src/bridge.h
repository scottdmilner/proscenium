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
    // Raises Tf errors posted while building the graph. The stage arrives as a weak pointer: Tf's Python
    // converter for a TfRefPtr argument moves ownership from the Python object into C++, so a bridge
    // taking a TfRefPtr would destroy a stage its caller still holds when the bridge released it.
    explicit Bridge(const pxr::UsdStagePtr &stage);

    // Weak: the caller owns the stage. Null once it has expired.
    pxr::UsdStagePtr Stage() const { return stage_; }

    // Drops the graph, whose stage scene index holds a strong stage reference, so a
    // caller-released stage can expire.
    void Release() {
        graph_.reset();
        last_.reset();
    }

    // Call without the GIL. Incremental captures share unchanged prims with the previous capture.
    SnapshotPtr Capture(pxr::UsdTimeCode time, bool incremental = false);

private:
    pxr::UsdStagePtr stage_;
    std::unique_ptr<SceneIndexGraph> graph_;
    SnapshotPtr last_;  // the graph's notices since this capture are the ones not yet taken
};

}  // namespace hydra_bridge
