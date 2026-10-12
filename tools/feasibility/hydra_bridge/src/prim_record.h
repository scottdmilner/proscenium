// Plain records of the schemas planning reads, extracted from a snapshot's frozen scene index. Fields
// are null-checked once here, so planning works on values rather than nullable schema handles. Paths
// are Hydra paths.
#pragma once

#include <pxr/pxr.h>
#include <pxr/base/gf/matrix4d.h>
#include <pxr/base/tf/token.h>
#include <pxr/base/vt/array.h>
#include <pxr/base/vt/value.h>
#include <pxr/imaging/pxOsd/meshTopology.h>
#include <pxr/usd/sdf/path.h>

#include <optional>
#include <unordered_map>
#include <utility>
#include <vector>

namespace hydra_bridge {

struct PrimvarRecord {
    pxr::TfToken name;
    pxr::TfToken interpolation;
    pxr::TfToken role;
    // Unflattened values; `indices` is set only for an indexed primvar.
    pxr::VtValue values;
    std::optional<pxr::VtIntArray> indices;
};

struct MeshRecord {
    // Scheme, orientation, counts, indices, and holes; subdivision tags are not read, since the
    // prototype doesn't transfer them.
    pxr::PxOsdMeshTopology topology;
    bool doubleSided = false;
};

struct GeomSubsetRecord {
    pxr::TfToken type;
    pxr::VtIntArray indices;
};

struct InstancedByRecord {
    pxr::VtArray<pxr::SdfPath> instancers;
    pxr::VtArray<pxr::SdfPath> prototypeRoots;
};

struct InstancerRecord {
    pxr::VtArray<pxr::SdfPath> prototypes;
    std::vector<pxr::VtIntArray> instanceIndices;  // per prototype
    pxr::VtBoolArray mask;                         // empty: all visible
    pxr::VtArray<pxr::SdfPath> instanceLocations;  // native instancers only
};

struct MaterialRecord {
    pxr::TfToken surfaceIdentifier;  // empty when the network has no surface terminal
    std::vector<std::pair<pxr::TfToken, pxr::VtValue>> surfaceParameters;
};

struct PrimRecord {
    pxr::SdfPath path;
    pxr::TfToken type;
    pxr::TfToken usdTypeName;  // __usdPrimInfo: the USD type before filters converted it
    pxr::SdfPath originPath;   // primOrigin/scenePath: prototype-relative inside prototypes
    std::optional<pxr::GfMatrix4d> matrix;
    bool visible = true;
    pxr::TfToken purpose;
    std::vector<PrimvarRecord> primvars;
    pxr::SdfPath materialBinding;  // allPurpose
    std::optional<MeshRecord> mesh;
    std::optional<GeomSubsetRecord> geomSubset;
    std::optional<InstancedByRecord> instancedBy;
    std::optional<InstancerRecord> instancer;
    std::optional<MaterialRecord> material;

    const PrimvarRecord *FindPrimvar(const pxr::TfToken &name) const;
};

// Every prim of a scene index, depth-first with parents before children, and indexed by path.
struct PrimTable {
    std::vector<PrimRecord> prims;
    std::unordered_map<pxr::SdfPath, size_t, pxr::SdfPath::Hash> index;

    const PrimRecord *Find(const pxr::SdfPath &path) const;
};

}  // namespace hydra_bridge
