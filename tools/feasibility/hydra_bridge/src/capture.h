// Capture: advance the scene-index graph, then one parallel read pass that copies values into a Snapshot.
#pragma once

#include "scene_index_graph.h"
#include "snapshot.h"

namespace hydra_bridge {

// Call without the GIL. Tf errors and warnings posted during the capture become snapshot
// diagnostics, attributed to the prim being read when they were posted. At UsdTimeCode::Default(),
// every sample-time query reports false, so time-variance detection (Phase D) needs a numeric time.
SnapshotPtr Capture(SceneIndexGraph &graph, pxr::UsdTimeCode time);

}  // namespace hydra_bridge
