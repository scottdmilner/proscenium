// M4: content deduplication. Built meshes with equal content are one geometry resource: Blender would hold
// the same mesh data for each. Everything that differs per drawn copy (transform, constant primvars,
// materials, visibility) is on the objects, so it never keeps two meshes apart.
#pragma once

#include "plan.h"

#include <cstddef>
#include <unordered_map>
#include <vector>

namespace hydra_bridge {

// A mesh's content: positions, corners, faces, each face's material slot and the slot count, attributes (in
// any order), subdivision scheme, and sidedness, byte for byte. Its name is left out.
std::size_t ContentHash(const MeshData &mesh);
bool SameContent(const MeshData &a, const MeshData &b);

// The plan's meshes by content, as they are added.
class MeshContents {
public:
    // The index into `meshes` of a mesh with `mesh`'s content, whose hash is `hash`, or -1 for none.
    [[nodiscard]] int Find(const MeshData &mesh, std::size_t hash, const std::vector<MeshData> &meshes) const;
    void Add(std::size_t hash, int index);

private:
    std::unordered_multimap<std::size_t, int> byHash_;
};

}  // namespace hydra_bridge
