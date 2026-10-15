#include "mesh_builder.h"

#include "validate.h"

#include <pxr/base/gf/half.h>
#include <pxr/base/gf/vec2f.h>
#include <pxr/base/gf/vec3d.h>
#include <pxr/base/gf/vec3f.h>
#include <pxr/base/gf/vec3h.h>
#include <pxr/base/gf/vec4f.h>
#include <pxr/imaging/hd/geomSubsetSchema.h>
#include <pxr/imaging/hd/primvarSchema.h>
#include <pxr/imaging/hd/tokens.h>
#include <pxr/imaging/pxOsd/tokens.h>

#include <algorithm>
#include <numeric>
#include <string>

PXR_NAMESPACE_USING_DIRECTIVE

namespace hydra_bridge {

namespace {

// How each Blender corner and face relates to the captured topology.
struct Layout {
    MeshCounts counts;
    std::vector<size_t> sourceCorner;  // the captured corner each Blender corner takes its data from
    std::vector<size_t> faceOfCorner;
    VtIntArray cornerVerts;
    VtIntArray faceOffsets;
};

template <class From>
std::optional<VtVec3fArray> ConvertPoints(const VtValue &values) {
    if (!values.IsHolding<VtArray<From>>()) return std::nullopt;
    const auto &from = values.UncheckedGet<VtArray<From>>();
    VtVec3fArray points(from.size());
    std::transform(from.cbegin(), from.cend(), points.begin(), [](const From &point) { return GfVec3f(point); });
    return points;
}

std::optional<VtVec3fArray> Positions(const PrimRecord &prim) {
    const PrimvarRecord *points = prim.FindPrimvar(HdTokens->points);
    if (!points || points->indices) return std::nullopt;
    if (points->values.IsHolding<VtVec3fArray>()) return points->values.UncheckedGet<VtVec3fArray>();
    if (auto converted = ConvertPoints<GfVec3d>(points->values)) return converted;
    return ConvertPoints<GfVec3h>(points->values);
}

// Blender winds every face right-handed; a left-handed face is reversed, keeping its first corner.
Layout MakeLayout(const PxOsdMeshTopology &topology, size_t pointCount) {
    const VtIntArray &counts = topology.GetFaceVertexCounts();
    const VtIntArray &indices = topology.GetFaceVertexIndices();
    Layout layout;
    layout.counts = {pointCount, counts.size(), indices.size()};
    const bool reverse = topology.GetOrientation() == PxOsdOpenSubdivTokens->leftHanded;
    layout.sourceCorner.resize(layout.counts.corners);
    layout.faceOfCorner.resize(layout.counts.corners);
    layout.cornerVerts.resize(layout.counts.corners);
    layout.faceOffsets.resize(layout.counts.faces);
    size_t offset = 0;
    for (size_t face = 0; face < layout.counts.faces; ++face) {
        const auto size = static_cast<size_t>(counts[face]);
        layout.faceOffsets[face] = static_cast<int>(offset);
        for (size_t j = 0; j < size; ++j) {
            const size_t corner = offset + j;
            layout.sourceCorner[corner] = reverse && j > 0 ? offset + size - j : corner;
            layout.faceOfCorner[corner] = face;
            layout.cornerVerts[corner] = indices[layout.sourceCorner[corner]];
        }
        offset += size;
    }
    return layout;
}

std::vector<size_t> Iota(size_t count) {
    std::vector<size_t> result(count);
    std::iota(result.begin(), result.end(), size_t{0});
    return result;
}

// The source element (before primvar indices) of each element of `domain`.
std::vector<size_t> SourceElements(Domain domain, const TfToken &interpolation, const Layout &layout) {
    if (domain != Domain::Corner) return Iota(domain == Domain::Point ? layout.counts.points : layout.counts.faces);
    if (interpolation == HdPrimvarSchemaTokens->faceVarying) return layout.sourceCorner;
    if (interpolation == HdPrimvarSchemaTokens->uniform) return layout.faceOfCorner;
    return std::vector<size_t>(layout.cornerVerts.begin(), layout.cornerVerts.end());
}

// Validated beforehand: every source element and index is in range.
template <class In, class Out, class Convert>
VtValue Gather(const PrimvarRecord &primvar, const std::vector<size_t> &sources, Convert convert) {
    const auto &values = primvar.values.UncheckedGet<VtArray<In>>();
    VtArray<Out> out(sources.size());
    Out *data = out.data();
    for (size_t i = 0; i < sources.size(); ++i) {
        const size_t element = primvar.indices ? static_cast<size_t>((*primvar.indices)[sources[i]]) : sources[i];
        data[i] = convert(values[element]);
    }
    return VtValue(std::move(out));
}

const auto kSame = [](const auto &value) { return value; };

// nullopt for a value type the prototype doesn't transfer.
std::optional<Attribute> ToAttribute(const PrimvarRecord &primvar, const Layout &layout) {
    const TfToken &interpolation = primvar.interpolation;
    const bool texcoord = primvar.role == HdPrimvarRoleTokens->textureCoordinate;
    Domain domain = Domain::Point;
    if (texcoord || interpolation == HdPrimvarSchemaTokens->faceVarying)
        domain = Domain::Corner;  // Blender keeps UV maps on corners
    else if (interpolation == HdPrimvarSchemaTokens->uniform)
        domain = Domain::Face;
    const std::vector<size_t> sources = SourceElements(domain, interpolation, layout);
    const VtValue &values = primvar.values;
    Attribute attribute{primvar.name.GetString(), domain, DataType::Float, {}};
    if (values.IsHolding<VtVec2fArray>()) {
        attribute.type = DataType::Float2;
        attribute.data = Gather<GfVec2f, GfVec2f>(primvar, sources, kSame);
    } else if (values.IsHolding<VtVec3fArray>() && primvar.role == HdPrimvarRoleTokens->color) {
        attribute.type = DataType::FloatColor;
        attribute.data = Gather<GfVec3f, GfVec4f>(primvar, sources, [](const GfVec3f &c) { return GfVec4f(c[0], c[1], c[2], 1.0f); });
    } else if (values.IsHolding<VtVec3fArray>()) {
        attribute.type = DataType::FloatVector;
        attribute.data = Gather<GfVec3f, GfVec3f>(primvar, sources, kSame);
    } else if (values.IsHolding<VtFloatArray>()) {
        attribute.data = Gather<float, float>(primvar, sources, kSame);
    } else if (values.IsHolding<VtIntArray>()) {
        attribute.type = DataType::Int;
        attribute.data = Gather<int, int>(primvar, sources, kSame);
    } else {
        return std::nullopt;
    }
    return attribute;
}

bool ReservedName(const std::string &name) {
    return name.empty() || name[0] == '.' || name == "position" || name == "material_index";
}

// Slot 0 is the mesh's own binding, for faces in no subset. A face in several subsets keeps the first.
void AssignMaterials(const PrimRecord &prim, const std::vector<const PrimRecord *> &subsets, size_t faceCount,
                     const MaterialLookup &materialIndex, MeshData &data, Diagnostics &problems) {
    std::vector<SdfPath> slots{prim.materialBinding};
    auto slotOf = [&](const SdfPath &material) {
        auto found = std::find(slots.begin(), slots.end(), material);
        if (found != slots.end()) return static_cast<int>(found - slots.begin());
        slots.push_back(material);
        return static_cast<int>(slots.size() - 1);
    };
    std::vector<int> faceSlot(faceCount, -1);
    bool overlap = false;
    for (const PrimRecord *subset : subsets) {
        const GeomSubsetRecord &record = *subset->geomSubset;
        if (record.type != HdGeomSubsetSchemaTokens->typeFaceSet) continue;
        if (std::string problem = ValidateSubset(record, faceCount); !problem.empty()) {
            problems.push_back({Severity::Error, "invalid-subset", prim.path, subset->path.GetName() + ": " + problem});
            continue;
        }
        const int slot = slotOf(subset->materialBinding);
        for (int face : record.indices) {
            int &assigned = faceSlot[static_cast<size_t>(face)];
            if (assigned == -1)
                assigned = slot;
            else if (assigned != slot)
                overlap = true;
        }
    }
    if (overlap)
        problems.push_back({Severity::Warning, "overlapping-subsets", prim.path,
                            "Faces in several bound subsets keep the first subset's material"});
    data.materialIndices.resize(faceCount);
    for (size_t face = 0; face < faceCount; ++face) data.materialIndices[face] = std::max(faceSlot[face], 0);
    for (const SdfPath &material : slots) data.materialSlots.push_back(materialIndex(material));
}

}  // namespace

std::optional<MeshData> BuildMesh(const PrimRecord &prim, const std::vector<const PrimRecord *> &subsets,
                                  const MaterialLookup &materialIndex, Diagnostics &problems) {
    const MeshRecord &mesh = *prim.mesh;
    auto fail = [&](const std::string &message) {
        problems.push_back({Severity::Error, "invalid-mesh", prim.path, message});
        return std::nullopt;
    };
    std::optional<VtVec3fArray> positions = Positions(prim);
    if (!positions) return fail("No float3 points");
    if (std::string problem = ValidateTopology(mesh.topology, positions->size()); !problem.empty()) return fail(problem);

    Layout layout = MakeLayout(mesh.topology, positions->size());
    MeshData data;
    data.name = prim.path.GetName();
    data.positions = std::move(*positions);
    data.cornerVerts = layout.cornerVerts;
    data.faceOffsets = layout.faceOffsets;
    data.subdivisionScheme = mesh.topology.GetScheme();
    data.doubleSided = mesh.doubleSided;
    if (!mesh.topology.GetHoleIndices().empty())
        problems.push_back({Severity::Warning, "holes-ignored", prim.path, "Hole faces are kept as ordinary faces"});
    AssignMaterials(prim, subsets, layout.counts.faces, materialIndex, data, problems);

    for (const PrimvarRecord &primvar : prim.primvars) {
        // Positions are handled above; constants travel with each object, not the shared mesh.
        if (primvar.name == HdTokens->points || primvar.interpolation == HdPrimvarSchemaTokens->constant) continue;
        auto skip = [&](Severity severity, const char *code, const std::string &why) {
            problems.push_back({severity, code, prim.path, "Primvar '" + primvar.name.GetString() + "': " + why});
        };
        if (std::string problem = ValidatePrimvar(primvar, layout.counts); !problem.empty()) {
            skip(Severity::Error, "invalid-primvar", problem);
        } else if (primvar.name == HdTokens->normals || ReservedName(primvar.name.GetString())) {
            skip(Severity::Info, "untransferred-primvar", "not transferred by the prototype");
        } else if (std::optional<Attribute> attribute = ToAttribute(primvar, layout)) {
            data.attributes.push_back(std::move(*attribute));
        } else {
            skip(Severity::Info, "untransferred-primvar", "type " + primvar.values.GetTypeName() + " is not transferred");
        }
    }
    return data;
}

}  // namespace hydra_bridge
