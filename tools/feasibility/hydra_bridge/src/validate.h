// Geometry validation before anything reaches Blender: Hydra passes USD's arrays through
// unchecked, and an out-of-range index in C++ or in Blender would terminate the host.
#pragma once

#include "prim_record.h"

#include <cstddef>
#include <string>

namespace hydra_bridge {

struct MeshCounts {
    size_t points = 0;
    size_t faces = 0;
    size_t corners = 0;
};

// Each returns an empty string when valid, else the first problem found.

// USD's own topology checks (PxOsdMeshTopology::Validate), then indices within the points and every
// count within Blender's int indices.
std::string ValidateTopology(const pxr::PxOsdMeshTopology &topology, size_t pointCount);

// The value count for the interpolation (or the index count when indexed), and indices within the values.
std::string ValidatePrimvar(const PrimvarRecord &primvar, const MeshCounts &counts);

// Face indices within the mesh.
std::string ValidateSubset(const GeomSubsetRecord &subset, size_t faceCount);

}  // namespace hydra_bridge
