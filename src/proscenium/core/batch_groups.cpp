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
  const std::size_t copies = plan.copyObjects.size();
  for (std::size_t copy = 0; copy < copies; ++copy) {
    const int geometry = plan.copyGeometries[copy];
    if (geometry < 0) {  // a placeholder or marker
      single.push_back(static_cast<int>(copy));
      continue;
    }
    BatchGroup group;
    group.geometry = geometry;
    group.viewport = plan.copyViewport[copy];
    group.render = plan.copyRender[copy];
    std::string key;
    Append(key, group.geometry);
    Append(key, group.viewport);
    Append(key, group.render);
    // The world transform as the plan holds it, the float32 values Blender stores, so coincident copies are told apart
    // exactly as a pick sees them.
    std::string placed = key;
    for (std::size_t i = 16 * copy; i < 16 * (copy + 1); ++i) Append(placed, plan.copyWorlds[i]);
    group.repeat = repeats[placed]++;
    Append(key, group.repeat);
    const auto [found, added] = byKey.emplace(std::move(key), grouped.size());
    if (added) grouped.push_back(std::move(group));
    grouped[found->second].members.push_back(static_cast<int>(copy));
  }
  BatchGroups result;
  for (BatchGroup& group : grouped) {
    if (group.members.size() >= minimum)
      result.groups.push_back(std::move(group));
    else
      single.insert(single.end(), group.members.cbegin(), group.members.cend());
  }
  std::sort(single.begin(), single.end());
  result.single.assign(single.begin(), single.end());
  return result;
}

}  // namespace proscenium
