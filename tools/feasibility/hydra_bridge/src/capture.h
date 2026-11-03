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
//
// With `timeDependencies` (M4 Phase E, E3), the snapshot's events also dirty everything that depends on time, as a
// time change would, so a plan of this one time code says what may vary over others. The read pass registers each
// value UsdImaging finds might vary (ValueMightBeTimeVarying, equal samples included) with the stage scene index,
// which dirties exactly those on a time change, or when forced at the current one, and Hydra forwards each dirtied
// locator to the values it computes from it (flattened transforms and visibility, instance roots, skinned points,
// extents). Those dirtied locators make Hydra's flattening forget what they name until it is read again, so the next
// capture is handed them too, and copies those prims again.
SnapshotPtr Capture(SceneIndexGraph &graph, pxr::UsdTimeCode time, const Snapshot *previous = nullptr,
                    Diagnostics carried = {}, bool timeDependencies = false);

}  // namespace hydra_bridge
