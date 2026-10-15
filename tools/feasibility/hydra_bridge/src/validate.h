// Geometry validation before anything reaches Blender: Hydra passes USD's arrays through
// unchecked, and an out-of-range index in C++ or in Blender would terminate the host.
#pragma once

#include "prim_record.h"

#include <cstddef>
#include <string>
#include <vector>

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

// Faces that are valid USD but that Blender's Mesh.validate() deletes (measured): one that uses a point more
// than once, and each later face on the same points as an earlier one, whatever its winding, since Blender
// keeps the first. Leaving them out is Blender's own repair. Call after ValidateTopology succeeds.
struct RejectedFaces {
    std::vector<bool> drop;  // per captured face
    size_t repeatedPoint = 0;
    size_t duplicate = 0;
    std::string example;  // the first of each kind, for the diagnostic
};
RejectedFaces FacesBlenderDeletes(const pxr::PxOsdMeshTopology &topology);

}  // namespace hydra_bridge
