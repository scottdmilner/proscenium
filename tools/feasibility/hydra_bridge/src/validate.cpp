#include "validate.h"

#include "fact_timings.h"

#include <pxr/imaging/hd/primvarSchema.h>
#include <pxr/imaging/pxOsd/meshTopologyValidation.h>
#include <pxr/imaging/pxOsd/tokens.h>

#include <algorithm>
#include <functional>
#include <utility>
#include <limits>
#include <numeric>
#include <optional>
#include <vector>

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
    std::optional<ScopedFactTiming> usdTiming(std::in_place, FactTiming::MeshUsdValidate);
    if (PxOsdMeshTopologyValidation validation = checked.Validate(); !validation) return validation.begin()->message;
    usdTiming.reset();
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

RejectedFaces FacesBlenderDeletes(const PxOsdMeshTopology &topology) {
    const VtIntArray &counts = topology.GetFaceVertexCounts();
    const VtIntArray &indices = topology.GetFaceVertexIndices();
    RejectedFaces rejected;
    rejected.drop.assign(counts.size(), false);
    std::string repeatedExample, duplicateExample;
    // Faces are compared by their sorted points, sorted in place in one copy of the indices.
    std::vector<int> sorted(indices.cbegin(), indices.cend());
    std::vector<size_t> offsets(counts.size() + 1, 0);
    for (size_t face = 0; face < counts.size(); ++face) {
        offsets[face + 1] = offsets[face] + static_cast<size_t>(counts[face]);
        const auto begin = sorted.begin() + static_cast<std::ptrdiff_t>(offsets[face]);
        const auto end = sorted.begin() + static_cast<std::ptrdiff_t>(offsets[face + 1]);
        std::sort(begin, end);
        if (std::adjacent_find(begin, end) != end) {
            rejected.drop[face] = true;
            if (rejected.repeatedPoint++ == 0) repeatedExample = "face " + std::to_string(face) + " uses a point more than once";
        }
    }
    // Faces with equal hashes end up adjacent after one sort of (hash, face) pairs, earliest face first; only
    // those are compared, and a face matching an earlier kept one is dropped.
    std::vector<std::pair<size_t, size_t>> keyed;
    keyed.reserve(counts.size());
    for (size_t face = 0; face < counts.size(); ++face) {
        if (rejected.drop[face]) continue;
        size_t seed = static_cast<size_t>(counts[face]);
        for (size_t corner = offsets[face]; corner < offsets[face + 1]; ++corner)
            seed ^= std::hash<int>()(sorted[corner]) + 0x9e3779b9 + (seed << 6) + (seed >> 2);
        keyed.emplace_back(seed, face);
    }
    std::sort(keyed.begin(), keyed.end());
    auto same = [&](size_t a, size_t b) {
        return std::equal(sorted.cbegin() + static_cast<std::ptrdiff_t>(offsets[a]),
                          sorted.cbegin() + static_cast<std::ptrdiff_t>(offsets[a + 1]),
                          sorted.cbegin() + static_cast<std::ptrdiff_t>(offsets[b]),
                          sorted.cbegin() + static_cast<std::ptrdiff_t>(offsets[b + 1]));
    };
    for (size_t i = 1; i < keyed.size(); ++i) {
        const size_t face = keyed[i].second;
        for (size_t j = i; j-- > 0 && keyed[j].first == keyed[i].first;) {
            const size_t earlier = keyed[j].second;
            if (rejected.drop[earlier] || !same(earlier, face)) continue;
            rejected.drop[face] = true;
            if (rejected.duplicate++ == 0)
                duplicateExample = "face " + std::to_string(face) + " uses the points of face " + std::to_string(earlier);
            break;
        }
    }
    rejected.example = repeatedExample;
    if (!duplicateExample.empty()) rejected.example += (rejected.example.empty() ? "" : "; ") + duplicateExample;
    return rejected;
}

}  // namespace hydra_bridge
