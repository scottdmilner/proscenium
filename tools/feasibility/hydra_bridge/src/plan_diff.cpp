#include "plan_diff.h"

#include "mesh_sharing.h"

#include <pxr/base/tf/hash.h>

#include <cstddef>
#include <string>
#include <tuple>
#include <unordered_map>

PXR_NAMESPACE_USING_DIRECTIVE

namespace hydra_bridge {

namespace {

struct Identity {
    const ObjectEntry &entry;

    bool operator==(const Identity &other) const {
        return entry.source == other.entry.source && entry.instanceContext == other.entry.instanceContext &&
               entry.inViewport == other.entry.inViewport && entry.inRender == other.entry.inRender;
    }
};

struct IdentityHash {
    std::size_t operator()(const Identity &identity) const {
        const ObjectEntry &entry = identity.entry;
        return TfHash::Combine(entry.source, entry.instanceContext, entry.inViewport, entry.inRender);
    }
};

bool SameMaterial(const MaterialData &a, const MaterialData &b) {
    return std::tie(a.name, a.sources, a.surfaceIdentifier, a.surfaceParameters) ==
           std::tie(b.name, b.sources, b.surfaceIdentifier, b.surfaceParameters);
}

bool SameProperties(const ObjectEntry &a, const ObjectEntry &b) {
    if (a.properties.size() != b.properties.size()) return false;
    for (std::size_t i = 0; i < a.properties.size(); ++i) {
        const auto &[name, value] = a.properties[i];
        const auto &[otherName, other] = b.properties[i];
        if (name != otherName || value.tupleSize != other.tupleSize || value.value != other.value) return false;
    }
    return true;
}

// Everything apply.py sets from an object entry; its mesh and slots are compared through the diff's mappings.
bool SameObject(const ObjectEntry &next, const ObjectEntry &old, const PlanDiff &diff) {
    const int mesh = next.mesh == -1 ? -1 : diff.meshes[static_cast<std::size_t>(next.mesh)];
    if (mesh != old.mesh || (next.mesh != -1 && mesh == -1)) return false;
    if (next.materialSlots.size() != old.materialSlots.size()) return false;
    for (std::size_t i = 0; i < next.materialSlots.size(); ++i) {
        const int slot = next.materialSlots[i];
        const int material = slot == -1 ? -1 : diff.materials[static_cast<std::size_t>(slot)];
        if (material != old.materialSlots[i] || (slot != -1 && material == -1)) return false;
    }
    return std::tie(next.placeholderType, next.bounds, next.matrix, next.visible, next.purpose,
                    next.constantPrimvars) ==
               std::tie(old.placeholderType, old.bounds, old.matrix, old.visible, old.purpose, old.constantPrimvars) &&
           SameProperties(next, old);
}

}  // namespace

PlanDiff DiffPlans(const Plan &published, const Plan &next) {
    PlanDiff diff;
    MeshContents contents;
    for (std::size_t i = 0; i < published.meshes.size(); ++i)
        contents.Add(published.meshHashes[i], static_cast<int>(i));
    diff.meshes.reserve(next.meshes.size());
    for (std::size_t i = 0; i < next.meshes.size(); ++i)
        diff.meshes.push_back(contents.Find(next.meshes[i], next.meshHashes[i], published.meshes));

    // Each material compares in full only against those with its name.
    std::unordered_multimap<std::string, int> materialsByName;
    for (std::size_t i = 0; i < published.materials.size(); ++i)
        materialsByName.emplace(published.materials[i].name, static_cast<int>(i));
    diff.materials.reserve(next.materials.size());
    for (const MaterialData &material : next.materials) {
        int same = -1;
        const auto [begin, end] = materialsByName.equal_range(material.name);
        for (auto it = begin; it != end && same == -1; ++it)
            if (SameMaterial(material, published.materials[static_cast<std::size_t>(it->second)])) same = it->second;
        diff.materials.push_back(same);
    }

    std::unordered_map<Identity, int, IdentityHash> objectsByIdentity;
    for (std::size_t i = 0; i < published.objects.size(); ++i)
        objectsByIdentity.emplace(Identity{published.objects[i]}, static_cast<int>(i));
    std::vector<bool> matched(published.objects.size(), false);
    diff.objects.reserve(next.objects.size());
    for (std::size_t i = 0; i < next.objects.size(); ++i) {
        const auto found = objectsByIdentity.find(Identity{next.objects[i]});
        // An identity the new plan repeats matches once; the planner gives each object its own.
        const int old =
            found == objectsByIdentity.end() || matched[static_cast<std::size_t>(found->second)] ? -1 : found->second;
        diff.objects.push_back(old);
        if (old == -1) continue;
        matched[static_cast<std::size_t>(old)] = true;
        if (!SameObject(next.objects[i], published.objects[static_cast<std::size_t>(old)], diff))
            diff.changed.push_back(static_cast<int>(i));
    }
    for (std::size_t i = 0; i < matched.size(); ++i)
        if (!matched[i]) diff.removed.push_back(static_cast<int>(i));
    return diff;
}

}  // namespace hydra_bridge
