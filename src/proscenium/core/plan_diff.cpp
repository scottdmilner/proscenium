#include "plan_diff.h"

#include <pxr/base/tf/hash.h>

#include <array>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <unordered_map>
#include <vector>

PXR_NAMESPACE_USING_DIRECTIVE

namespace proscenium {
namespace {

constexpr std::size_t kMatrixSize = 16;
constexpr std::size_t kBoundsSize = 6;

struct Identity {
  const CorrespondenceEntry& entry;

  bool operator==(const Identity& other) const {
    return entry.sourcePath == other.entry.sourcePath && entry.instanceContext == other.entry.instanceContext;
  }
};

struct IdentityHash {
  std::size_t operator()(const Identity& identity) const {
    return TfHash::Combine(identity.entry.sourcePath, identity.entry.instanceContext);
  }
};

std::uint32_t Bits(float value) {
  std::uint32_t bits = 0;
  std::memcpy(&bits, &value, sizeof bits);
  return bits;
}

// Whether `count` floats from `a`'s element `aStart` and `b`'s `bStart` have the same bits.
bool SameBits(const VtFloatArray& a, std::size_t aStart, const VtFloatArray& b, std::size_t bStart, std::size_t count) {
  for (std::size_t i = 0; i < count; ++i)
    if (Bits(a[aStart + i]) != Bits(b[bStart + i])) return false;
  return true;
}

// A copy's local bounds as its bounds mesh draws them: its geometry description's extent or its placeholder's bounds,
// absent for a mesh Hydra gives no extent, whose bounds mesh has no vertices, and for a marker, which has no bounds
// mesh.
struct LocalBounds {
  std::array<float, kBoundsSize> values{};
  bool present = false;
};

LocalBounds BoundsOf(const Plan& plan, std::size_t copy) {
  LocalBounds bounds;
  const VtFloatArray* source = nullptr;  // null for none
  std::size_t start = 0;
  if (const int geometry = plan.copyGeometryIndices[copy]; geometry >= 0) {
    source = &plan.geometries[static_cast<std::size_t>(geometry)].extent;
  } else if (const int placeholder = plan.copyPlaceholderBoundsIndices[copy]; placeholder >= 0) {
    source = &plan.placeholderBounds;
    start = kBoundsSize * static_cast<std::size_t>(placeholder);
  }
  if (source == nullptr || source->size() < start + kBoundsSize) return bounds;
  for (std::size_t i = 0; i < kBoundsSize; ++i) bounds.values.at(i) = (*source)[start + i];
  bounds.present = true;
  return bounds;
}

bool SameBounds(const LocalBounds& a, const LocalBounds& b) {
  if (a.present != b.present) return false;
  for (std::size_t i = 0; i < kBoundsSize; ++i)
    if (Bits(a.values.at(i)) != Bits(b.values.at(i))) return false;
  return true;
}

// Whether the copy's partition holds a bounds mesh, and a shear parent: what a local update can't change.
bool SameResources(const Plan& plan, std::size_t copy, const Plan& previous, std::size_t old) {
  return (plan.copyBoundsMeshResourceIndices[copy] < 0) == (previous.copyBoundsMeshResourceIndices[old] < 0) &&
         (plan.copyShearParentResourceIndices[copy] < 0) == (previous.copyShearParentResourceIndices[old] < 0);
}

// Whether the copy's world matrix, and if it shears, its split, differ. Its partition holds the same resources, so it
// shears in both plans or neither.
bool Moved(const Plan& plan, std::size_t copy, const Plan& previous, std::size_t old) {
  if (!SameBits(plan.copyWorldMatrices, kMatrixSize * copy, previous.copyWorldMatrices, kMatrixSize * old, kMatrixSize))
    return true;
  const int shear = plan.copyShearSplitIndices[copy];
  const int oldShear = previous.copyShearSplitIndices[old];
  if (shear < 0 || oldShear < 0) return false;
  const std::size_t split = kMatrixSize * static_cast<std::size_t>(shear);
  const std::size_t oldSplit = kMatrixSize * static_cast<std::size_t>(oldShear);
  return !SameBits(plan.shearParentWorldMatrices, split, previous.shearParentWorldMatrices, oldSplit, kMatrixSize) ||
         !SameBits(plan.shearObjectBasisMatrices, split, previous.shearObjectBasisMatrices, oldSplit, kMatrixSize);
}

}  // namespace

PlanDiff DiffPlans(const Plan& previous, const Plan& plan) {
  PlanDiff diff;
  std::unordered_map<Identity, int, IdentityHash> copiesByIdentity;
  copiesByIdentity.reserve(previous.correspondence.size());
  for (std::size_t i = 0; i < previous.correspondence.size(); ++i)
    copiesByIdentity.emplace(Identity{previous.correspondence[i]}, static_cast<int>(i));
  std::vector<bool> matched(previous.correspondence.size(), false);
  diff.previousCopyIndices.reserve(plan.correspondence.size());
  for (std::size_t copy = 0; copy < plan.correspondence.size(); ++copy) {
    const auto found = copiesByIdentity.find(Identity{plan.correspondence[copy]});
    const int old =
        found == copiesByIdentity.end() || matched[static_cast<std::size_t>(found->second)] ? -1 : found->second;
    diff.previousCopyIndices.push_back(old);
    if (old == -1) continue;
    const auto before = static_cast<std::size_t>(old);
    matched[before] = true;
    const int index = static_cast<int>(copy);
    if (!SameResources(plan, copy, previous, before)) {
      diff.rebuiltCopyIndices.push_back(index);
      continue;
    }
    if (Moved(plan, copy, previous, before)) diff.movedCopyIndices.push_back(index);
    if (!SameBounds(BoundsOf(plan, copy), BoundsOf(previous, before))) diff.boundsChangedCopyIndices.push_back(index);
    if (plan.copyVisibleInViewport[copy] != previous.copyVisibleInViewport[before] ||
        plan.copyVisibleInRender[copy] != previous.copyVisibleInRender[before])
      diff.participationChangedCopyIndices.push_back(index);
  }
  for (std::size_t i = 0; i < matched.size(); ++i)
    if (!matched[i]) diff.removedPreviousCopyIndices.push_back(static_cast<int>(i));
  return diff;
}

}  // namespace proscenium
