#include "prim_record.h"

#include <algorithm>

PXR_NAMESPACE_USING_DIRECTIVE

namespace hydra_bridge {

const PrimvarRecord *PrimRecord::FindPrimvar(const TfToken &name) const {
    auto found = std::find_if(primvars.begin(), primvars.end(), [&](const PrimvarRecord &p) { return p.name == name; });
    return found == primvars.end() ? nullptr : &*found;
}

const PrimRecord *PrimTable::Find(const SdfPath &path) const {
    auto found = index.find(path);
    return found == index.end() ? nullptr : &prims[found->second];
}

}  // namespace hydra_bridge
