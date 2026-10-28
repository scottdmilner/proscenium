// Capture: advance the scene-index graph, then one parallel read pass that copies values into a Snapshot.
#pragma once

#include "scene_index_graph.h"
#include "snapshot.h"

namespace hydra_bridge {

// Call without the GIL. Tf errors and warnings posted during the capture become snapshot
// diagnostics, attributed to the prim being read when they were posted. At UsdTimeCode::Default(),
// every sample-time query reports false, so time-variance detection (Phase D) needs a numeric time.
//
// With `previous` (null for a full capture), the snapshot this graph produced last, the capture is incremental: prims
// that no notice since then named (added, dirtied, or under a removed or renamed path) share the previous snapshot's
// static copies instead of being copied again. Notices may over-report but are trusted not to miss a change;
// cases/edits.py checks that against full captures.
//
// `carried` are diagnostics posted before this capture, outside any capture (while the graph was built). They
// join the graph's own, unattributed to a prim.
SnapshotPtr Capture(SceneIndexGraph &graph, pxr::UsdTimeCode time, const Snapshot *previous = nullptr,
                    Diagnostics carried = {});

}  // namespace hydra_bridge
