// Plain records of the schemas planning reads, extracted from a snapshot's frozen scene index. Fields
// are null-checked once here, so planning works on values rather than nullable schema handles. Paths
// are Hydra paths.
#pragma once

#include <pxr/pxr.h>
#include <pxr/base/gf/matrix4d.h>
#include <pxr/base/gf/range3d.h>
#include <pxr/base/tf/token.h>
#include <pxr/base/vt/array.h>
#include <pxr/base/vt/value.h>
#include <pxr/imaging/pxOsd/meshTopology.h>
#include <pxr/usd/sdf/path.h>

#include <optional>
#include <string>
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
    bool doubleSided = false;  // as Hydra reports it; PrimRecord::sourceDoubleSided is USD's
};

struct GeomSubsetRecord {
    pxr::TfToken type;
    pxr::VtIntArray indices;
    pxr::TfToken familyName;  // from the source-info filter; Hydra drops it
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

// (purpose, token) pairs, for each purpose with an opinion.
using PurposeVisibility = std::vector<std::pair<pxr::TfToken, pxr::TfToken>>;

struct PrimRecord {
    pxr::SdfPath path;
    pxr::TfToken type;
    // The USD type before filters converted it: __usdPrimInfo, else the source-info filter's, which
    // also covers prims Hydra doesn't image.
    pxr::TfToken usdTypeName;
    bool isGprim = false;  // source-info filter
    // Hydra's piPropagatedPrototypes marker: a point instancer's prototype original, drawn only as its copies.
    bool pointInstancerPrototype = false;
    std::string materialBindFamilyIssue;  // source-info filter: why USD rejects this mesh's materialBind family
    pxr::TfTokenVector droppedAttributes;  // source-info filter: authored attributes UsdImaging drops
    pxr::SdfPath originPath;  // primOrigin/scenePath: prototype-relative inside prototypes
    std::optional<pxr::GfMatrix4d> matrix;
    bool visible = true;
    pxr::TfToken purpose;
    PurposeVisibility purposeVisibility;  // authored guide/proxy/render visibility; Hydra doesn't image it
    std::optional<bool> sourceDoubleSided;  // USD's, fallback included; Hydra's can be wrong
    std::optional<pxr::GfRange3d> extent;   // local
    std::vector<PrimvarRecord> primvars;
    // Hydra's flattened bindings by material purpose (the empty purpose is allPurpose). Kept for evidence;
    // planning uses usdBindings.
    std::vector<std::pair<pxr::TfToken, pxr::SdfPath>> materialBindings;
    // The source-info filter's: UsdShade's binding for each purpose exactly (an empty path is a binding to
    // something that isn't a Material, which binds nothing), and the purposes this prim binds
    // strongerThanDescendants.
    std::vector<std::pair<pxr::TfToken, pxr::SdfPath>> usdBindings;
    pxr::TfTokenVector strongBindingPurposes;
    std::optional<MeshRecord> mesh;
    std::optional<GeomSubsetRecord> geomSubset;
    std::optional<InstancedByRecord> instancedBy;
    std::optional<InstancerRecord> instancer;
    std::optional<MaterialRecord> material;

    const PrimvarRecord *FindPrimvar(const pxr::TfToken &name) const;
    const pxr::TfToken *PurposeVisibilityOf(const pxr::TfToken &forPurpose) const;
};

// A constant primvar's value as the prim sees it: flattened through its indices with USD's own
// UsdGeomPrimvar::ComputeFlattened, which reports bad indices in `error` (and returns false) rather than
// substituting defaults as Hydra's flattening does. An unindexed value is returned as is.
bool FlattenedConstant(const PrimvarRecord &primvar, pxr::VtValue &value, std::string &error);

// Every prim of a scene index, depth-first with parents before children, and indexed by path.
struct PrimTable {
    std::vector<PrimRecord> prims;
    std::unordered_map<pxr::SdfPath, size_t, pxr::SdfPath::Hash> index;

    const PrimRecord *Find(const pxr::SdfPath &path) const;
};

}  // namespace hydra_bridge
