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
// prim whose binding each material slot takes: the mesh, then each materialBind subset used, and `work` what the
// topology alone gave.
//
// With `previous`, an earlier build of the prim (E4): when its topology and point count are this one's, the
// topology isn't checked again, and the mesh shares its corners, faces, equal material slots, and the attributes
// of its equal primvars, rather than building them anew. The mesh and problems are the same either way.
std::optional<MeshData> BuildMesh(const PrimRecord &prim, const PrimRefs &subsets, Diagnostics &problems,
                                  PrimRefs &slots, TopologyWork &work, const MeshBuild *previous = nullptr);

}  // namespace hydra_bridge
