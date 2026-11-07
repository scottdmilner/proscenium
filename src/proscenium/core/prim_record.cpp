#include "prim_record.h"

#include <algorithm>

PXR_NAMESPACE_USING_DIRECTIVE

namespace proscenium {

const PrimvarRecord* PrimRecord::FindPrimvar(const TfToken& name) const {
  const auto found =
      std::find_if(primvars.cbegin(), primvars.cend(), [&](const PrimvarRecord& p) { return p.name == name; });
  return found == primvars.cend() ? nullptr : &*found;
}

const PrimRecord* PrimTable::Find(const SdfPath& path) const {
  const auto found = index.find(path);
  return found == index.end() ? nullptr : &prims[found->second];
}

}  // namespace proscenium
