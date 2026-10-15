#include "prim_record.h"

#include <pxr/usd/usdGeom/primvar.h>

#include <algorithm>

PXR_NAMESPACE_USING_DIRECTIVE

namespace hydra_bridge {

const PrimvarRecord *PrimRecord::FindPrimvar(const TfToken &name) const {
    auto found = std::find_if(primvars.begin(), primvars.end(), [&](const PrimvarRecord &p) { return p.name == name; });
    return found == primvars.end() ? nullptr : &*found;
}

const TfToken *PrimRecord::PurposeVisibilityOf(const TfToken &forPurpose) const {
    for (const auto &[authored, visibility] : purposeVisibility)
        if (authored == forPurpose) return &visibility;
    return nullptr;
}

bool FlattenedConstant(const PrimvarRecord &primvar, VtValue &value, std::string &error) {
    if (!primvar.indices) {
        value = primvar.values;
        return true;
    }
    return UsdGeomPrimvar::ComputeFlattened(&value, primvar.values, *primvar.indices, &error);
}

const PrimRecord *PrimTable::Find(const SdfPath &path) const {
    auto found = index.find(path);
    return found == index.end() ? nullptr : &prims[found->second];
}

}  // namespace hydra_bridge
