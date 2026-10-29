#include "batch_groups.h"

#include <pxr/base/gf/matrix4f.h>
#include <pxr/base/gf/vec4f.h>
#include <pxr/base/vt/types.h>

#include <algorithm>
#include <cstring>
#include <optional>
#include <unordered_map>

PXR_NAMESPACE_USING_DIRECTIVE

namespace hydra_bridge {

namespace {

// The point attribute data type that holds a constant primvar's property value, as batch.attribute_type
// decides it; nullopt if none can.
std::optional<std::string> AttributeType(const PropertyValue &property) {
    const VtValue &value = property.value;
    if (value.IsHolding<bool>()) return "BOOLEAN";
    if (value.IsHolding<int>()) return "INT";
    if (value.IsHolding<double>()) return "FLOAT";
    if (value.IsHolding<VtDoubleArray>() && property.tupleSize == 0) {
        const size_t size = value.UncheckedGet<VtDoubleArray>().size();
        if (size == 2) return "FLOAT2";
        if (size == 3) return "FLOAT_VECTOR";
    }
    return std::nullopt;
}

// apply.object_color's: the constant displayColor and displayOpacity of one value each, or opaque white.
std::array<double, 4> ObjectColor(const ObjectEntry &object) {
    std::array<double, 4> color{1.0, 1.0, 1.0, 1.0};
    for (const auto &[name, property] : object.properties) {
        const VtValue &value = property.value;
        if (name == "displayColor" && value.IsHolding<VtDoubleArray>() && property.tupleSize == 0) {
            const auto &rgb = value.UncheckedGet<VtDoubleArray>();
            if (rgb.size() == 3) std::copy(rgb.cbegin(), rgb.cend(), color.begin());
        } else if (name == "displayOpacity" && value.IsHolding<double>()) {
            color[3] = value.UncheckedGet<double>();
        }
    }
    return color;
}

// The bytes of a value, appended to a key.
template <class T>
void Append(std::string &key, const T &value) {
    std::array<char, sizeof(T)> bytes{};
    std::memcpy(bytes.data(), &value, sizeof(T));
    key.append(bytes.data(), bytes.size());
}

void Append(std::string &key, const std::string &text) {
    Append(key, text.size());
    key += text;
}

}  // namespace

BatchGroups GroupForBatches(const Plan &plan, std::size_t minimum) {
    std::vector<BatchGroup> grouped;
    std::unordered_map<std::string, size_t> byKey;  // a group's key and repeat -> its index in `grouped`
    std::unordered_map<std::string, int> repeats;   // a key and float32 transform -> the repeats so far
    std::vector<int> single;
    for (size_t i = 0; i < plan.objects.size(); ++i) {
        const ObjectEntry &object = plan.objects[i];
        BatchGroup group;
        bool batchable = object.mesh >= 0;
        for (const auto &[name, property] : object.properties) {
            if (!batchable) break;
            if (property.value.IsHolding<std::string>()) continue;
            if (std::optional<std::string> type = AttributeType(property))
                group.kinds.emplace_back(name, std::move(*type));
            else
                batchable = false;
        }
        if (!batchable) {
            single.push_back(static_cast<int>(i));
            continue;
        }
        std::sort(group.kinds.begin(), group.kinds.end());
        group.mesh = object.mesh;
        group.materialSlots = object.materialSlots;
        group.inViewport = object.inViewport;
        group.inRender = object.inRender;
        group.color = ObjectColor(object);
        std::string key;
        Append(key, group.mesh);
        Append(key, group.materialSlots.size());
        for (const int slot : group.materialSlots) Append(key, slot);
        Append(key, group.inViewport);
        Append(key, group.inRender);
        for (const double channel : group.color) Append(key, channel);
        for (const auto &[name, type] : group.kinds) {
            Append(key, name);
            Append(key, type);
        }
        // The transform as Blender stores it, so coincident copies are told apart exactly as a pick sees them.
        const GfMatrix4f stored(object.matrix);
        std::string placed = key;
        for (int row = 0; row < 4; ++row) Append(placed, stored.GetRow(row));
        group.repeat = repeats[placed]++;
        Append(key, group.repeat);
        auto [found, added] = byKey.emplace(std::move(key), grouped.size());
        if (added) grouped.push_back(std::move(group));
        grouped[found->second].members.push_back(static_cast<int>(i));
    }
    BatchGroups result;
    for (BatchGroup &group : grouped) {
        if (group.members.size() >= minimum)
            result.groups.push_back(std::move(group));
        else
            single.insert(single.end(), group.members.begin(), group.members.end());
    }
    std::sort(single.begin(), single.end());
    result.single = std::move(single);
    return result;
}

}  // namespace hydra_bridge
