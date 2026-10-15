#include "mesh_builder.h"

#include "fact_timings.h"

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
#include <optional>
#include <string>

PXR_NAMESPACE_USING_DIRECTIVE

namespace hydra_bridge {

namespace {

// How each Blender corner and face relates to the captured topology. Faces Blender would delete are left out,
// so Blender's faces and corners can be fewer than the captured ones.
struct Layout {
    MeshCounts source;  // the captured mesh's, which primvars are validated against
    MeshCounts counts;  // Blender's
    std::vector<size_t> sourceCorner;  // the captured corner each Blender corner takes its data from
    std::vector<size_t> faceOfCorner;  // the captured face of each Blender corner
    std::vector<size_t> sourceFace;    // the captured face of each Blender face
    std::vector<int> blenderFace;      // the Blender face of each captured face; -1 when left out
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

// Blender winds every face right-handed; a left-handed face is reversed, keeping its first corner. Faces in
// `drop` are left out.
Layout MakeLayout(const PxOsdMeshTopology &topology, size_t pointCount, const std::vector<bool> &drop) {
    const VtIntArray &counts = topology.GetFaceVertexCounts();
    const VtIntArray &indices = topology.GetFaceVertexIndices();
    Layout layout;
    layout.source = {pointCount, counts.size(), indices.size()};
    const bool reverse = topology.GetOrientation() == PxOsdOpenSubdivTokens->leftHanded;
    layout.blenderFace.assign(counts.size(), -1);
    layout.sourceFace.reserve(counts.size());
    layout.faceOffsets.reserve(counts.size());
    layout.sourceCorner.reserve(indices.size());
    layout.faceOfCorner.reserve(indices.size());
    layout.cornerVerts.reserve(indices.size());
    size_t sourceOffset = 0;
    for (size_t face = 0; face < counts.size(); ++face) {
        const auto size = static_cast<size_t>(counts[face]);
        if (!drop[face]) {
            layout.blenderFace[face] = static_cast<int>(layout.sourceFace.size());
            layout.sourceFace.push_back(face);
            layout.faceOffsets.push_back(static_cast<int>(layout.sourceCorner.size()));
            for (size_t j = 0; j < size; ++j) {
                const size_t corner = sourceOffset + (reverse && j > 0 ? size - j : j);
                layout.sourceCorner.push_back(corner);
                layout.faceOfCorner.push_back(face);
                layout.cornerVerts.push_back(indices[corner]);
            }
        }
        sourceOffset += size;
    }
    layout.counts = {pointCount, layout.sourceFace.size(), layout.sourceCorner.size()};
    return layout;
}

std::vector<size_t> Iota(size_t count) {
    std::vector<size_t> result(count);
    std::iota(result.begin(), result.end(), size_t{0});
    return result;
}

// The source element (before primvar indices) of each element of `domain`.
std::vector<size_t> SourceElements(Domain domain, const TfToken &interpolation, const Layout &layout) {
    if (domain == Domain::Point) return Iota(layout.counts.points);
    if (domain == Domain::Face) return layout.sourceFace;
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

// nullopt for a value type the prototype doesn't transfer. `name` is the Blender attribute's.
std::optional<Attribute> ToAttribute(const PrimvarRecord &primvar, const std::string &name, const Layout &layout) {
    const TfToken &interpolation = primvar.interpolation;
    const bool texcoord = primvar.role == HdPrimvarRoleTokens->textureCoordinate;
    Domain domain = Domain::Point;
    if (texcoord || interpolation == HdPrimvarSchemaTokens->faceVarying)
        domain = Domain::Corner;  // Blender keeps UV maps on corners
    else if (interpolation == HdPrimvarSchemaTokens->uniform)
        domain = Domain::Face;
    const std::vector<size_t> sources = SourceElements(domain, interpolation, layout);
    const VtValue &values = primvar.values;
    Attribute attribute{name, domain, DataType::Float, {}};
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

// The Blender attribute a primvar becomes: authored normals are Blender's custom normals, which Blender 5.2
// takes on points, faces or corners, and per-point velocities Blender's velocity, which is per point.
// Others, velocities on another domain included, keep their name.
std::string BlenderName(const PrimvarRecord &primvar) {
    static const TfToken kVelocities("velocities");
    if (primvar.name == HdTokens->normals) return "custom_normal";
    const bool perPoint = primvar.interpolation == HdPrimvarSchemaTokens->vertex ||
                          primvar.interpolation == HdPrimvarSchemaTokens->varying;
    if (primvar.name == kVelocities && perPoint) return "velocity";
    return primvar.name.GetString();
}

// Names Blender gives a meaning of its own: a primvar with one would change shading, creases, or seams.
bool ReservedName(const std::string &name) {
    static const char *const kBuiltIn[] = {"position",          "material_index",    "sharp_face",  "sharp_edge",
                                           "crease_vert",       "crease_edge",       "uv_seam",     "custom_normal",
                                           "bevel_weight_vert", "bevel_weight_edge", "freestyle_edge", "freestyle_face"};
    return name.empty() || name[0] == '.' ||
           std::find(std::begin(kBuiltIn), std::end(kBuiltIn), name) != std::end(kBuiltIn);
}

// Slot 0 is the mesh's own binding, for faces in no subset, and each materialBind subset gets the next
// slot. Slots follow subsets rather than materials because each destination binds its own materials, and
// may group the faces differently. Only the materialBind family assigns materials, as in UsdShade; Hydra
// binds a subset of any family, so the family comes from the source-info filter. A face in several subsets
// keeps the first.
void AssignSlots(const PrimRecord &prim, const std::vector<const PrimRecord *> &subsets, const Layout &layout,
                 MeshData &data, Diagnostics &problems, std::vector<const PrimRecord *> &slots) {
    const size_t faceCount = layout.counts.faces;
    static const TfToken kMaterialBind("materialBind");
    slots.assign(1, &prim);
    std::vector<int> faceSlot(faceCount, -1);
    bool overlap = false;
    // In path order, so which overlapping subset wins doesn't depend on the order Hydra lists children in.
    std::vector<const PrimRecord *> ordered(subsets);
    std::sort(ordered.begin(), ordered.end(), [](const PrimRecord *a, const PrimRecord *b) { return a->path < b->path; });
    for (const PrimRecord *subset : ordered) {
        const GeomSubsetRecord &record = *subset->geomSubset;
        if (record.familyName != kMaterialBind) continue;
        if (record.type != HdGeomSubsetSchemaTokens->typeFaceSet) {
            problems.push_back({Severity::Warning, "unsupported-subset", prim.path,
                                subset->path.GetName() + ": a materialBind subset must list faces; it is ignored"});
            continue;
        }
        if (std::string problem = ValidateSubset(record, layout.source.faces); !problem.empty()) {
            problems.push_back({Severity::Error, "invalid-subset", prim.path, subset->path.GetName() + ": " + problem});
            continue;
        }
        const int slot = static_cast<int>(slots.size());
        slots.push_back(subset);
        for (int sourceFace : record.indices) {
            const int face = layout.blenderFace[static_cast<size_t>(sourceFace)];
            if (face < 0) continue;  // left out, as Blender would delete it
            int &assigned = faceSlot[static_cast<size_t>(face)];
            if (assigned == -1)
                assigned = slot;
            else
                overlap = true;
        }
    }
    if (overlap)
        problems.push_back({Severity::Warning, "overlapping-subsets", prim.path,
                            "Faces in several materialBind subsets keep the material of the first, by name"});
    data.materialIndices.resize(faceCount);
    for (size_t face = 0; face < faceCount; ++face) data.materialIndices[face] = std::max(faceSlot[face], 0);
    data.slotCount = static_cast<int>(slots.size());
}

}  // namespace

std::optional<MeshData> BuildMesh(const PrimRecord &prim, const std::vector<const PrimRecord *> &subsets,
                                  Diagnostics &problems, std::vector<const PrimRecord *> &slots) {
    const MeshRecord &mesh = *prim.mesh;
    auto fail = [&](const std::string &message) {
        problems.push_back({Severity::Error, "invalid-mesh", prim.path, message});
        return std::nullopt;
    };
    std::optional<VtVec3fArray> positions = Positions(prim);
    if (!positions) return fail("No float3 points");
    // UsdImaging reads a points attribute of another type as an empty array.
    if (positions->empty() && !mesh.topology.GetFaceVertexIndices().empty())
        return fail("No points (a points attribute that isn't point3f reads as empty)");
    std::optional<ScopedFactTiming> validateTiming(std::in_place, FactTiming::MeshValidate);
    if (std::string problem = ValidateTopology(mesh.topology, positions->size()); !problem.empty()) return fail(problem);
    validateTiming.reset();
    // Valid USD that Blender's Mesh.validate() would repair by deleting faces: the same repair, warned.
    std::optional<ScopedFactTiming> deletedTiming(std::in_place, FactTiming::MeshDeletedFaces);
    const RejectedFaces rejected = FacesBlenderDeletes(mesh.topology);
    deletedTiming.reset();
    if (rejected.repeatedPoint + rejected.duplicate > 0)
        problems.push_back({Severity::Warning, "faces-left-out", prim.path,
                            std::to_string(rejected.repeatedPoint) + " face(s) using a point more than once and " +
                                std::to_string(rejected.duplicate) +
                                " face(s) on an earlier face's points are left out, as Blender's Mesh.validate() "
                                "deletes them (" + rejected.example + ")"});

    std::optional<ScopedFactTiming> layoutTiming(std::in_place, FactTiming::MeshLayout);
    Layout layout = MakeLayout(mesh.topology, positions->size(), rejected.drop);
    MeshData data;
    data.name = prim.path.GetName();
    data.positions = std::move(*positions);
    data.cornerVerts = layout.cornerVerts;
    data.faceOffsets = layout.faceOffsets;
    data.subdivisionScheme = mesh.topology.GetScheme();
    // USD's value where the source-info filter has it: the implicit-surface filter can lose an authored true
    // (M1b plan, Phase C log: "Results by case"; checked by cases/implicit.py).
    data.doubleSided = prim.sourceDoubleSided.value_or(mesh.doubleSided);
    if (!mesh.topology.GetHoleIndices().empty())
        problems.push_back({Severity::Warning, "holes-ignored", prim.path, "Hole faces are kept as ordinary faces"});
    layoutTiming.reset();
    {
        const ScopedFactTiming timing(FactTiming::MeshSlots);
        AssignSlots(prim, subsets, layout, data, problems, slots);
    }
    const ScopedFactTiming primvarTiming(FactTiming::MeshPrimvars);

    static const TfToken kVelocities("velocities"), kAccelerations("accelerations");
    const bool subdivided = data.subdivisionScheme != PxOsdOpenSubdivTokens->none;
    for (const PrimvarRecord &primvar : prim.primvars) {
        // Positions are handled above; constants travel with each object, not the shared mesh.
        if (primvar.name == HdTokens->points || primvar.interpolation == HdPrimvarSchemaTokens->constant) continue;
        auto skip = [&](Severity severity, const char *code, const std::string &why) {
            problems.push_back({severity, code, prim.path, "Primvar '" + primvar.name.GetString() + "': " + why});
        };
        const std::string name = BlenderName(primvar);
        if (std::string problem = ValidatePrimvar(primvar, layout.source); !problem.empty()) {
            skip(Severity::Error, "invalid-primvar", problem);
        } else if (primvar.name == HdTokens->normals && subdivided) {
            // UsdGeomMesh: a subdivision surface's normals come from the subdivision, not from authored ones.
            skip(Severity::Info, "ignored-normals", "ignored on a subdivision surface, as USD specifies");
        } else if (primvar.name != HdTokens->normals && ReservedName(primvar.name.GetString())) {
            skip(Severity::Warning, "untransferred-primvar", "the name is one Blender gives a meaning of its own");
        } else if (primvar.name == kVelocities && name != primvar.name.GetString() && prim.FindPrimvar(TfToken(name))) {
            skip(Severity::Warning, "name-collision", "Blender's '" + name + "' is taken by the primvar of that name");
        } else if (primvar.name == HdTokens->normals && !primvar.values.IsHolding<VtVec3fArray>()) {
            skip(Severity::Warning, "untransferred-primvar", "normals of type " + primvar.values.GetTypeName() + " are not transferred");
        } else if (std::optional<Attribute> attribute = ToAttribute(primvar, name, layout)) {
            data.attributes.push_back(std::move(*attribute));
            if (primvar.name == kAccelerations)
                skip(Severity::Warning, "no-blender-equivalent",
                     "Blender has no acceleration attribute; kept as a generic attribute, which Blender doesn't use");
        } else {
            skip(Severity::Info, "untransferred-primvar", "type " + primvar.values.GetTypeName() + " is not transferred");
        }
    }
    return data;
}

}  // namespace hydra_bridge
