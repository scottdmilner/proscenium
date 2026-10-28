// Converts a captured Hydra mesh into Blender's arrays: corner order, material slots from
// GeomSubsets, and primvars as attributes on Blender's domains.
#pragma once

#include "diagnostics.h"
#include "plan.h"
#include "prim_record.h"

#include <pxr/usd/sdf/path.h>

#include <optional>
#include <vector>

namespace hydra_bridge {

// nullopt when the mesh is invalid. Problems go to `problems` with the mesh's Hydra path as source;
// an invalid primvar or subset is skipped with a diagnostic and the mesh still builds. `slots` receives the
// prim whose binding each material slot takes: the mesh, then each materialBind subset used.
std::optional<MeshData> BuildMesh(const PrimRecord &prim, const PrimRefs &subsets, Diagnostics &problems,
                                  PrimRefs &slots);

}  // namespace hydra_bridge
