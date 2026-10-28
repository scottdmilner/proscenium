#include "mesh_sharing.h"

#include <pxr/base/arch/hash.h>
#include <pxr/base/gf/vec2f.h>
#include <pxr/base/gf/vec3f.h>
#include <pxr/base/gf/vec4f.h>
#include <pxr/base/vt/array.h>
#include <pxr/base/vt/types.h>
#include <pxr/base/vt/value.h>

#include <algorithm>
#include <cstdint>
#include <functional>
#include <string_view>

PXR_NAMESPACE_USING_DIRECTIVE

namespace hydra_bridge {

namespace {

// An array's elements as bytes.
template <class T>
std::string_view Bytes(const VtArray<T> &array) {
    // NOLINTNEXTLINE(cppcoreguidelines-pro-type-reinterpret-cast): the elements are compared as raw bytes
    return {reinterpret_cast<const char *>(array.cdata()), array.size() * sizeof(T)};
}

// An attribute's elements as bytes; its data holds one of the array types plan.h lists.
std::string_view Bytes(const VtValue &data) {
    if (data.IsHolding<VtFloatArray>()) return Bytes(data.UncheckedGet<VtFloatArray>());
    if (data.IsHolding<VtVec2fArray>()) return Bytes(data.UncheckedGet<VtVec2fArray>());
    if (data.IsHolding<VtVec3fArray>()) return Bytes(data.UncheckedGet<VtVec3fArray>());
    if (data.IsHolding<VtVec4fArray>()) return Bytes(data.UncheckedGet<VtVec4fArray>());
    if (data.IsHolding<VtIntArray>()) return Bytes(data.UncheckedGet<VtIntArray>());
    return {};
}

std::uint64_t Hash(std::string_view bytes, std::uint64_t seed) { return ArchHash64(bytes.data(), bytes.size(), seed); }

template <class T>
std::uint64_t HashValue(const T &value, std::uint64_t seed) {
    // NOLINTNEXTLINE(cppcoreguidelines-pro-type-reinterpret-cast): the value is hashed as raw bytes
    return Hash({reinterpret_cast<const char *>(&value), sizeof(value)}, seed);
}

// Vt arrays share storage, so equal content is often one buffer, which needs no comparison.
bool Same(std::string_view a, std::string_view b) { return a.size() == b.size() && (a.data() == b.data() || a == b); }

using AttributeRefs = std::vector<std::reference_wrapper<const Attribute>>;

// The attributes by name: Blender's names are unique on a mesh, so the order is the same for equal content.
AttributeRefs ByName(const MeshData &mesh) {
    AttributeRefs sorted(mesh.attributes.begin(), mesh.attributes.end());
    std::sort(sorted.begin(), sorted.end(), [](const Attribute &a, const Attribute &b) { return a.name < b.name; });
    return sorted;
}

}  // namespace

std::size_t ContentHash(const MeshData &mesh) {
    // Binds every field, so a field added to MeshData fails to compile here until this hash and SameContent
    // cover it. The name is left out of the content.
    [[maybe_unused]] const auto &[name, positions, cornerVerts, faceOffsets, materialIndices, slotCount, attributes,
                                  subdivisionScheme, doubleSided] = mesh;
    // Everything SameContent compares, so meshes differing in any of it rarely share a bucket.
    std::uint64_t hash = HashValue(slotCount, 0);
    hash = HashValue(subdivisionScheme.Hash(), hash);
    hash = HashValue(doubleSided, hash);
    hash = Hash(Bytes(positions), hash);
    hash = Hash(Bytes(cornerVerts), hash);
    hash = Hash(Bytes(faceOffsets), hash);
    hash = Hash(Bytes(materialIndices), hash);
    for (const Attribute &attribute : ByName(mesh)) {
        hash = Hash(attribute.name, hash);
        hash = HashValue(attribute.domain, hash);
        hash = HashValue(attribute.type, hash);
        hash = Hash(Bytes(attribute.data), hash);
    }
    return static_cast<std::size_t>(hash);
}

bool SameContent(const MeshData &a, const MeshData &b) {
    if (a.slotCount != b.slotCount || a.subdivisionScheme != b.subdivisionScheme || a.doubleSided != b.doubleSided ||
        a.attributes.size() != b.attributes.size() || !Same(Bytes(a.positions), Bytes(b.positions)) ||
        !Same(Bytes(a.cornerVerts), Bytes(b.cornerVerts)) || !Same(Bytes(a.faceOffsets), Bytes(b.faceOffsets)) ||
        !Same(Bytes(a.materialIndices), Bytes(b.materialIndices)))
        return false;
    const AttributeRefs left = ByName(a), right = ByName(b);
    return std::equal(left.begin(), left.end(), right.begin(), [](const Attribute &x, const Attribute &y) {
        return x.name == y.name && x.domain == y.domain && x.type == y.type && x.data.GetType() == y.data.GetType() &&
               Same(Bytes(x.data), Bytes(y.data));
    });
}

int MeshContents::Find(const MeshData &mesh, std::size_t hash, const std::vector<MeshData> &meshes) const {
    const auto [begin, end] = byHash_.equal_range(hash);
    for (auto it = begin; it != end; ++it)
        if (SameContent(mesh, meshes[static_cast<std::size_t>(it->second)])) return it->second;
    return -1;
}

void MeshContents::Add(std::size_t hash, int index) { byHash_.emplace(hash, index); }

}  // namespace hydra_bridge
