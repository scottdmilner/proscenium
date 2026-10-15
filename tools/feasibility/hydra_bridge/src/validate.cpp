#include "validate.h"

#include <pxr/imaging/hd/primvarSchema.h>
#include <pxr/imaging/pxOsd/meshTopologyValidation.h>
#include <pxr/imaging/pxOsd/tokens.h>

#include <limits>

PXR_NAMESPACE_USING_DIRECTIVE

namespace hydra_bridge {

namespace {

constexpr size_t kMaxIndex = static_cast<size_t>(std::numeric_limits<int>::max());

std::string Describe(const char *what, size_t at, long long value, size_t limit) {
    return std::string(what) + " " + std::to_string(at) + " is " + std::to_string(value) + ", outside [0, " +
           std::to_string(limit) + ")";
}

}  // namespace

std::string ValidateTopology(const PxOsdMeshTopology &topology, size_t pointCount) {
    // Corner counts of at least three, non-negative indices matching the counts, hole indices, and the
    // scheme and orientation tokens. Validate accepts only OpenSubdiv's refinement schemes, but USD's
    // "none" (no subdivision) is valid; no other check depends on the scheme, so it validates as bilinear.
    const bool unsubdivided = topology.GetScheme() == PxOsdOpenSubdivTokens->none;
    const PxOsdMeshTopology checked = unsubdivided ? topology.WithScheme(PxOsdOpenSubdivTokens->bilinear) : topology;
    if (PxOsdMeshTopologyValidation validation = checked.Validate(); !validation) return validation.begin()->message;
    // USD can't check indices against points it doesn't have. The corner sum is recomputed in size_t,
    // since an int sum of huge counts could overflow and still match the index count.
    if (pointCount > kMaxIndex) return "More points than Blender can index";
    const VtIntArray &counts = topology.GetFaceVertexCounts();
    const VtIntArray &indices = topology.GetFaceVertexIndices();
    size_t corners = 0;
    for (int count : counts) {
        corners += static_cast<size_t>(count);
        if (corners > kMaxIndex) return "More corners than Blender can index";
    }
    if (corners != indices.size())
        return "Face corner counts sum to " + std::to_string(corners) + " but there are " +
               std::to_string(indices.size()) + " face-vertex indices";
    for (size_t corner = 0; corner < indices.size(); ++corner) {
        const int index = indices[corner];
        if (index < 0 || static_cast<size_t>(index) >= pointCount)
            return Describe("Face-vertex index", corner, index, pointCount);
    }
    return {};
}

std::string ValidatePrimvar(const PrimvarRecord &primvar, const MeshCounts &counts) {
    const TfToken &interpolation = primvar.interpolation;
    size_t expected = 0;
    if (interpolation == HdPrimvarSchemaTokens->constant)
        expected = 1;
    else if (interpolation == HdPrimvarSchemaTokens->uniform)
        expected = counts.faces;
    else if (interpolation == HdPrimvarSchemaTokens->vertex || interpolation == HdPrimvarSchemaTokens->varying)
        expected = counts.points;
    else if (interpolation == HdPrimvarSchemaTokens->faceVarying)
        expected = counts.corners;
    else
        return "Unknown interpolation '" + interpolation.GetString() + "'";
    const size_t valueCount = primvar.values.GetArraySize();
    const size_t elementCount = primvar.indices ? primvar.indices->size() : valueCount;
    if (elementCount != expected)
        return std::string(primvar.indices ? "Index" : "Value") + " count " + std::to_string(elementCount) +
               " does not match " + interpolation.GetString() + " interpolation's " + std::to_string(expected);
    if (primvar.indices) {
        for (size_t i = 0; i < primvar.indices->size(); ++i) {
            const int index = (*primvar.indices)[i];
            if (index < 0 || static_cast<size_t>(index) >= valueCount) return Describe("Index", i, index, valueCount);
        }
    }
    return {};
}

std::string ValidateSubset(const GeomSubsetRecord &subset, size_t faceCount) {
    for (size_t i = 0; i < subset.indices.size(); ++i) {
        const int face = subset.indices[i];
        if (face < 0 || static_cast<size_t>(face) >= faceCount) return Describe("Subset face index", i, face, faceCount);
    }
    return {};
}

}  // namespace hydra_bridge
