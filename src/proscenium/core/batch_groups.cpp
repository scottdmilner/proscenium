#include "batch_groups.h"

#include <algorithm>
#include <array>
#include <cstring>
#include <string>
#include <unordered_map>
#include <utility>

PXR_NAMESPACE_USING_DIRECTIVE

namespace proscenium {
namespace {

// The bytes of a value, appended to a key.
template <class T>
void Append(std::string& key, const T& value) {
  std::array<char, sizeof(T)> bytes{};
  std::memcpy(bytes.data(), &value, sizeof(T));
  key.append(bytes.data(), bytes.size());
}

}  // namespace

BatchGroups GroupForBatches(const Plan& plan, std::size_t minimum) {
  std::vector<BatchGroup> grouped;
  std::unordered_map<std::string, std::size_t> byKey;  // a group's key and repeat -> its index in `grouped`
  std::unordered_map<std::string, int> repeats;        // a key and float32 transform -> the repeats so far
  std::vector<int> single;
  const std::size_t copies = plan.copyObjectResourceIndices.size();
  for (std::size_t copy = 0; copy < copies; ++copy) {
    const int geometry = plan.copyGeometryIndices[copy];
    if (geometry < 0) {  // a placeholder or marker
      single.push_back(static_cast<int>(copy));
      continue;
    }
    BatchGroup group;
    group.geometryIndex = geometry;
    group.visibleInViewport = plan.copyVisibleInViewport[copy];
    group.visibleInRender = plan.copyVisibleInRender[copy];
    std::string key;
    Append(key, group.geometryIndex);
    Append(key, group.visibleInViewport);
    Append(key, group.visibleInRender);
    // The world transform as the plan holds it, the float32 values Blender stores, so coincident copies are told apart
    // exactly as a pick sees them.
    std::string placed = key;
    for (std::size_t i = 16 * copy; i < 16 * (copy + 1); ++i) Append(placed, plan.copyWorldMatrices[i]);
    group.coincidentCopyIndex = repeats[placed]++;
    Append(key, group.coincidentCopyIndex);
    const auto [found, added] = byKey.emplace(std::move(key), grouped.size());
    if (added) grouped.push_back(std::move(group));
    grouped[found->second].copyIndices.push_back(static_cast<int>(copy));
  }
  BatchGroups result;
  for (BatchGroup& group : grouped) {
    if (group.copyIndices.size() >= minimum)
      result.groups.push_back(std::move(group));
    else
      single.insert(single.end(), group.copyIndices.cbegin(), group.copyIndices.cend());
  }
  std::sort(single.begin(), single.end());
  result.unbatchedCopyIndices.assign(single.begin(), single.end());
  return result;
}

}  // namespace proscenium
