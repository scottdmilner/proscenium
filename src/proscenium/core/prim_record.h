// Plain records of what planning reads from a snapshot, as the bridge's are (M6 plan, B3): fields are null-checked
// once when read, so planning works on values rather than nullable schema handles. Paths are Hydra paths. Phase C
// adds the fields its planning reads.
#pragma once

#include <pxr/base/gf/matrix4d.h>
#include <pxr/base/gf/range3d.h>
#include <pxr/base/tf/token.h>
#include <pxr/base/vt/array.h>
#include <pxr/base/vt/value.h>
#include <pxr/pxr.h>
#include <pxr/usd/sdf/path.h>

#include <cstddef>
#include <optional>
#include <unordered_map>
#include <vector>

namespace proscenium {

struct PrimvarRecord {
  PXR_NS::TfToken name;
  // Unflattened values; `indices` is set only for an indexed primvar.
  PXR_NS::VtValue values;
  std::optional<PXR_NS::VtIntArray> indices;
};

struct InstancedByRecord {
  PXR_NS::VtArray<PXR_NS::SdfPath> instancers;
  PXR_NS::VtArray<PXR_NS::SdfPath> prototypeRoots;
};

struct InstancerRecord {
  PXR_NS::VtArray<PXR_NS::SdfPath> prototypes;
  std::vector<PXR_NS::VtIntArray> instanceIndices;     // per prototype
  PXR_NS::VtArray<PXR_NS::SdfPath> instanceLocations;  // native instancers only
};

struct PrimRecord {
  PXR_NS::SdfPath path;
  PXR_NS::TfToken type;
  bool isGprim = false;           // source-info filter: a gprim by its USD type, for a prim Hydra doesn't image
  bool resetsXformStack = false;  // source-info filter: USD's resetXformStack, which flattening hides
  PXR_NS::SdfPath originPath;     // primOrigin/scenePath: prototype-relative inside prototypes
  std::optional<PXR_NS::GfMatrix4d> matrix;  // flattened
  std::optional<PXR_NS::GfRange3d> extent;   // local
  std::vector<PrimvarRecord> primvars;       // the snapshot's, PlannedPrimvars() only
  std::optional<InstancedByRecord> instancedBy;
  std::optional<InstancerRecord> instancer;

  // Null when the prim has no such primvar.
  [[nodiscard]] const PrimvarRecord* FindPrimvar(const PXR_NS::TfToken& name) const;
};

// Every prim of a snapshot, depth-first with parents before children, and indexed by path.
struct PrimTable {
  std::vector<PrimRecord> prims;
  std::unordered_map<PXR_NS::SdfPath, std::size_t, PXR_NS::SdfPath::Hash> index;

  [[nodiscard]] const PrimRecord* Find(const PXR_NS::SdfPath& path) const;  // null when the table has no such prim
};

}  // namespace proscenium
