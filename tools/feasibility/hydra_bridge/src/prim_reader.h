// Reads the schemas planning uses out of a scene index into plain records.
#pragma once

#include "prim_record.h"

#include <pxr/pxr.h>
#include <pxr/base/tf/token.h>
#include <pxr/imaging/hd/sceneIndex.h>
#include <pxr/usd/sdf/path.h>

namespace hydra_bridge {

// The top-level schema containers ReadPrim reads; capture copies exactly these into the snapshot.
const pxr::TfTokenVector &PlannedSchemas();

// Fills `record` from the prim at `path`; returns false for a path with no prim.
bool ReadPrim(const pxr::HdSceneIndexBase &scene, const pxr::SdfPath &path, PrimRecord &record);

// Every prim, read in parallel. Call without the GIL.
PrimTable ReadPrims(const pxr::HdSceneIndexBaseRefPtr &scene);

}  // namespace hydra_bridge
