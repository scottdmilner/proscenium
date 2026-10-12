// Converts a captured Hydra mesh into Blender's arrays: corner order, material slots from
// GeomSubsets, and primvars as attributes on Blender's domains.
#pragma once

#include "diagnostics.h"
#include "plan.h"
#include "prim_record.h"

#include <pxr/usd/sdf/path.h>

#include <functional>
#include <optional>
#include <vector>

namespace hydra_bridge {

// The plan's index for a bound Hydra material path; -1 for none.
using MaterialLookup = std::function<int(const pxr::SdfPath &)>;

// nullopt when the mesh is invalid. Problems go to `problems` with the mesh's Hydra path as source;
// an invalid primvar or subset is skipped with a diagnostic and the mesh still builds.
std::optional<MeshData> BuildMesh(const PrimRecord &prim, const std::vector<const PrimRecord *> &subsets,
                                  const MaterialLookup &materialIndex, Diagnostics &problems);

}  // namespace hydra_bridge
