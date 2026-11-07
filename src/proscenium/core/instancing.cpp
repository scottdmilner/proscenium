#include "instancing.h"

#include <pxr/base/gf/matrix4f.h>
#include <pxr/base/vt/array.h>
#include <pxr/imaging/hd/tokens.h>

#include <algorithm>
#include <cstddef>
#include <optional>
#include <utility>

PXR_NAMESPACE_USING_DIRECTIVE

namespace proscenium {
namespace {

// Deeper nesting than any real scene; malformed data must not recurse without bound.
constexpr int kMaxDepth = 64;

std::optional<VtMatrix4dArray> InstanceTransforms(const PrimRecord& instancer) {
  const PrimvarRecord* primvar = instancer.FindPrimvar(HdInstancerTokens->instanceTransforms);
  if (!primvar || primvar->indices) return std::nullopt;
  if (primvar->values.IsHolding<VtMatrix4dArray>()) return primvar->values.UncheckedGet<VtMatrix4dArray>();
  if (primvar->values.IsHolding<VtMatrix4fArray>()) {
    const auto& single = primvar->values.UncheckedGet<VtMatrix4fArray>();
    VtMatrix4dArray transforms(single.size());
    std::transform(single.cbegin(), single.cend(), transforms.begin(),
                   [](const GfMatrix4f& m) { return GfMatrix4d(m); });
    return transforms;
  }
  return std::nullopt;
}

}  // namespace

InstanceResolver::InstanceResolver(const PrimTable& table, bool honorResets)
    : table_(table), honorResets_(honorResets) {}

const std::vector<DrawnCopy>& InstanceResolver::CopiesOf(const PrimRecord& prim) { return CopiesOf(prim, 0); }

bool InstanceResolver::ResetsBelow(SdfPath path, const SdfPath& prototypeRoot) const {
  if (!honorResets_ || prototypeRoot.IsAbsoluteRootPath()) return false;
  for (; !path.IsEmpty() && path != prototypeRoot && !path.IsAbsoluteRootPath(); path = path.GetParentPath())
    if (const PrimRecord* prim = table_.Find(path); prim && prim->resetsXformStack) return true;
  return false;
}

// CopiesOf, CopiesUnder, and Expand recurse once per nesting level, bounded by kMaxDepth.
const std::vector<DrawnCopy>& InstanceResolver::CopiesOf(const PrimRecord& prim,  // NOLINT(misc-no-recursion)
                                                         int depth) {
  if (!prim.instancedBy) return top_;
  const InstancedByRecord& by = *prim.instancedBy;
  // Native instancing gives each prototype copy exactly one instancer.
  if (by.instancers.size() != 1 || by.prototypeRoots.size() != 1) return none_;
  return CopiesUnder(by.instancers[0], by.prototypeRoots[0], depth);
}

const std::vector<DrawnCopy>& InstanceResolver::CopiesUnder(  // NOLINT(misc-no-recursion)
    const SdfPath& instancer, const SdfPath& prototypeRoot, int depth) {
  if (auto found = cache_.find(prototypeRoot); found != cache_.end()) return found->second;
  // Inserted before expanding, so a cycle in malformed data ends with no copies. References into an unordered_map
  // survive later insertions.
  std::vector<DrawnCopy>& copies = cache_[prototypeRoot];
  const PrimRecord* record = table_.Find(instancer);
  if (record && record->instancer && depth <= kMaxDepth)
    copies = Expand(*record, *record->instancer, prototypeRoot, depth);
  return copies;
}

std::vector<DrawnCopy> InstanceResolver::Expand(  // NOLINT(misc-no-recursion)
    const PrimRecord& instancer, const InstancerRecord& topology, const SdfPath& prototypeRoot, int depth) {
  const auto found = std::find(topology.prototypes.cbegin(), topology.prototypes.cend(), prototypeRoot);
  const auto p = static_cast<std::size_t>(found - topology.prototypes.cbegin());
  if (found == topology.prototypes.cend() || p >= topology.instanceIndices.size()) return {};
  // A point instancer has no instance locations; its prototypes are deferred (DEFER-01).
  const VtArray<SdfPath>& locations = topology.instanceLocations;
  const std::optional<VtMatrix4dArray> transforms = InstanceTransforms(instancer);
  if (locations.empty() || !transforms) return {};
  const std::vector<DrawnCopy>& outers = CopiesOf(instancer, depth + 1);
  if (outers.empty()) return {};
  // The instances in range, and whether each instance root or an ancestor inside the outer prototype resets the
  // stack (WORKAROUND for OpenUSD #862). Every outer copy has the same hydraRoot, so each is checked once.
  std::vector<std::pair<std::size_t, bool>> instances;
  for (const int k : topology.instanceIndices[p]) {
    const auto index = static_cast<std::size_t>(k);
    if (k < 0 || index >= locations.size() || index >= transforms->size()) continue;
    instances.emplace_back(index, ResetsBelow(locations[index], outers.front().hydraRoot));
  }
  std::vector<DrawnCopy> copies;
  copies.reserve(outers.size() * instances.size());
  for (const DrawnCopy& outer : outers) {
    for (const auto& [index, resets] : instances) {
      DrawnCopy copy;
      copy.hydraRoot = prototypeRoot;
      copy.usdRoot = outer.Map(locations[index]);
      copy.context = outer.context;
      copy.context.push_back(copy.usdRoot);
      // Row vectors: the instance's own transform first, then the outer copy's, unless it resets.
      const GfMatrix4d& own = (*transforms)[index];
      copy.world = resets ? own : own * outer.world;
      copies.push_back(std::move(copy));
    }
  }
  return copies;
}

}  // namespace proscenium
