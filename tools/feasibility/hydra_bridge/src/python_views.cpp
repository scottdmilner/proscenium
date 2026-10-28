#include "python_views.h"

#include "prim_reader.h"

#include <pxr/base/tf/pyLock.h>
#include <pxr/imaging/hd/dataSource.h>
#include <pxr/imaging/hd/sceneIndexPrimView.h>
#include <pxr/imaging/hd/tokens.h>

#include <array>
#include <sstream>
#include <stdexcept>

PXR_NAMESPACE_USING_DIRECTIVE

namespace hydra_bridge {

namespace {

template <class Paths>
bp::list PathList(const Paths &paths) {
    bp::list result;
    for (const SdfPath &path : paths) result.append(path.GetString());
    return result;
}

// Empty paths become None.
bp::object PathOrNone(const SdfPath &path) { return path.IsEmpty() ? bp::object() : bp::object(path.GetString()); }

bp::object TimeOrNone(UsdTimeCode time) { return time.IsDefault() ? bp::object() : bp::object(time.GetValue()); }

bp::list DiagnosticList(const Diagnostics &diagnostics) {
    bp::list result;
    for (const Diagnostic &diagnostic : diagnostics) {
        bp::dict record;
        record["severity"] = SeverityName(diagnostic.severity);
        record["code"] = diagnostic.code;
        record["source"] = PathOrNone(diagnostic.source);
        record["message"] = diagnostic.message;
        result.append(record);
    }
    return result;
}

bp::dict Primvars(const std::vector<PrimvarRecord> &primvars) {
    bp::dict result;
    for (const PrimvarRecord &primvar : primvars) {
        bp::dict record;
        record["interpolation"] = primvar.interpolation.GetString();
        record["role"] = primvar.role.GetString();
        record["values"] = bp::object(primvar.values);
        record["indices"] = primvar.indices ? bp::object(*primvar.indices) : bp::object();
        result[primvar.name.GetString()] = record;
    }
    return result;
}

bp::dict Parameters(const std::vector<std::pair<TfToken, VtValue>> &parameters) {
    bp::dict result;
    for (const auto &[name, value] : parameters) result[name.GetString()] = bp::object(value);
    return result;
}

// A flat list, or a list of `tuple`-sized lists, as Blender nests array properties.
template <class T>
bp::list ListOf(const VtArray<T> &values, size_t tuple) {
    bp::list result;
    if (tuple == 0) {
        for (const T &value : values) result.append(value);
        return result;
    }
    for (size_t i = 0; i + tuple <= values.size(); i += tuple) {
        bp::list row;
        for (size_t j = 0; j < tuple; ++j) row.append(values[i + j]);
        result.append(row);
    }
    return result;
}

// Python values Blender assigns as ID properties directly: bool, int, float, str, or (nested) lists of them.
bp::dict Properties(const std::vector<std::pair<std::string, PropertyValue>> &properties) {
    bp::dict result;
    for (const auto &[name, property] : properties) {
        const VtValue &value = property.value;
        if (value.IsHolding<VtBoolArray>())
            result[name] = ListOf(value.UncheckedGet<VtBoolArray>(), property.tupleSize);
        else if (value.IsHolding<VtIntArray>())
            result[name] = ListOf(value.UncheckedGet<VtIntArray>(), property.tupleSize);
        else if (value.IsHolding<VtDoubleArray>())
            result[name] = ListOf(value.UncheckedGet<VtDoubleArray>(), property.tupleSize);
        else if (value.IsHolding<VtStringArray>())
            result[name] = ListOf(value.UncheckedGet<VtStringArray>(), property.tupleSize);
        else
            result[name] = bp::object(value);
    }
    return result;
}

bp::object RangeOrNone(const std::optional<GfRange3d> &range) {
    return range ? bp::object(bp::make_tuple(range->GetMin(), range->GetMax())) : bp::object();
}

bp::dict PrimDict(const PrimRecord &prim) {
    bp::dict record;
    record["type"] = prim.type.GetString();
    record["usd_type"] = prim.usdTypeName.GetString();
    record["origin"] = PathOrNone(prim.originPath);
    record["matrix"] = prim.matrix ? bp::object(*prim.matrix) : bp::object();
    record["visible"] = prim.visible;
    record["purpose"] = prim.purpose.GetString();
    record["is_gprim"] = prim.isGprim;
    bp::dict bindings;
    for (const auto &[purpose, material] : prim.materialBindings) bindings[purpose.GetString()] = material.GetString();
    record["material_bindings"] = bindings;  // flattened, per purpose ("" is allPurpose), without fallback
    bp::dict usdBindings;
    for (const auto &[purpose, material] : prim.usdBindings) usdBindings[purpose.GetString()] = material.GetString();
    record["usd_bindings"] = usdBindings;  // UsdShade's, per exact purpose, from the source-info filter
    bp::dict purposeVisibility;
    for (const auto &[purpose, visibility] : prim.purposeVisibility)
        purposeVisibility[purpose.GetString()] = visibility.GetString();
    record["purpose_visibility"] = purposeVisibility;  // authored opinions on this prim
    record["source_double_sided"] = prim.sourceDoubleSided ? bp::object(*prim.sourceDoubleSided) : bp::object();
    record["extent"] = RangeOrNone(prim.extent);
    record["primvars"] = Primvars(prim.primvars);
    if (const PrimvarRecord *points = prim.FindPrimvar(HdTokens->points)) record["points"] = bp::object(points->values);
    if (prim.mesh) {
        const PxOsdMeshTopology &topology = prim.mesh->topology;
        record["counts"] = topology.GetFaceVertexCounts();
        record["indices"] = topology.GetFaceVertexIndices();
        record["holes"] = topology.GetHoleIndices();
        record["orientation"] = topology.GetOrientation().GetString();
        record["scheme"] = topology.GetScheme().GetString();
        record["double_sided"] = prim.mesh->doubleSided;
    }
    if (prim.geomSubset) {
        bp::dict subset;
        subset["type"] = prim.geomSubset->type.GetString();
        subset["indices"] = prim.geomSubset->indices;
        subset["family_name"] = prim.geomSubset->familyName.GetString();
        record["subset"] = subset;
    }
    if (prim.instancedBy) {
        bp::dict by;
        by["instancers"] = PathList(prim.instancedBy->instancers);
        by["prototype_roots"] = PathList(prim.instancedBy->prototypeRoots);
        record["instanced_by"] = by;
    }
    if (prim.instancer) {
        bp::dict instancer;
        instancer["prototypes"] = PathList(prim.instancer->prototypes);
        bp::list indices;
        for (const VtIntArray &perPrototype : prim.instancer->instanceIndices) indices.append(perPrototype);
        instancer["instance_indices"] = indices;
        instancer["mask"] = prim.instancer->mask;
        instancer["locations"] = PathList(prim.instancer->instanceLocations);
        record["instancer"] = instancer;
    }
    if (prim.material) {
        bp::dict material;
        material["surface_identifier"] = prim.material->surfaceIdentifier.GetString();
        material["parameters"] = Parameters(prim.material->surfaceParameters);
        record["material"] = material;
    }
    return record;
}

}  // namespace

bp::object SnapshotView::Time() const { return TimeOrNone(data->time); }

bp::list SnapshotView::Paths() const {
    bp::list result;
    for (const SdfPath &path : HdSceneIndexPrimView(data->scene, SdfPath::AbsoluteRootPath()))
        if (data->scene->GetPrim(path).dataSource) result.append(path.GetString());
    return result;
}

bp::object SnapshotView::Prim(const std::string &path) const {
    PrimRecord record;
    if (!SdfPath::IsValidPathString(path) || !ReadPrim(*data->scene, SdfPath(path), record)) return {};
    return PrimDict(record);
}

bp::object SnapshotView::Dump(const std::string &path) const {
    if (!SdfPath::IsValidPathString(path)) return {};
    const HdSceneIndexPrim prim = data->scene->GetPrim(SdfPath(path));
    if (!prim.dataSource) return {};
    std::ostringstream out;
    HdDebugPrintDataSource(out, prim.dataSource);
    return bp::object(out.str());
}

bp::list SnapshotView::Events() const {
    bp::list result;
    for (const Event &event : data->events)
        result.append(bp::make_tuple(EventKindName(event.kind), event.path.GetString()));
    return result;
}

bp::dict SnapshotView::DirtyLocators() const {
    bp::dict result;
    for (const Event &event : data->events) {
        if (event.kind != EventKind::Dirtied) continue;
        bp::list locators = bp::extract<bp::list>(result.setdefault(event.path.GetString(), bp::list()));
        for (const std::string &locator : event.locators) locators.append(locator);
    }
    return result;
}

bp::list SnapshotView::Renames() const {
    bp::list result;
    for (const Event &event : data->events)
        if (event.kind == EventKind::Renamed)
            result.append(bp::make_tuple(event.oldPath.GetString(), event.path.GetString()));
    return result;
}

bp::list SnapshotView::Diagnostics() const { return DiagnosticList(data->diagnostics); }

bp::dict SnapshotView::CopyBindings() const {
    bp::dict result;
    bp::list instances;
    bp::dict materials;
    if (const auto &copies = data->copyBindings) {
        for (const SdfPath &path : copies->instances) instances.append(path.GetString());
        static const std::array kPurposes{"allPurpose", "preview", "full"};
        for (const auto &[path, bound] : copies->materials) {
            bp::dict perPurpose;
            for (size_t p = 0; p < bound.size(); ++p) perPurpose[kPurposes[p]] = bound[p].GetString();
            materials[path.GetString()] = perPurpose;
        }
    }
    result["instances"] = instances;
    result["materials"] = materials;
    return result;
}

bp::object PlanView::Time() const { return TimeOrNone(data->time); }

bp::list PlanView::Meshes() const {
    bp::list result;
    for (const MeshData &mesh : data->meshes) {
        bp::dict record;
        record["name"] = mesh.name;
        record["positions"] = mesh.positions;
        record["corner_verts"] = mesh.cornerVerts;
        record["face_offsets"] = mesh.faceOffsets;
        record["material_indices"] = mesh.materialIndices;
        record["slot_count"] = mesh.slotCount;
        bp::list attributes;
        for (const Attribute &attribute : mesh.attributes) {
            bp::dict entry;
            entry["name"] = attribute.name;
            entry["domain"] = DomainName(attribute.domain);
            entry["data_type"] = DataTypeName(attribute.type);
            entry["data"] = bp::object(attribute.data);
            attributes.append(entry);
        }
        record["attributes"] = attributes;
        record["subdivision_scheme"] = mesh.subdivisionScheme.GetString();
        record["double_sided"] = mesh.doubleSided;
        result.append(record);
    }
    return result;
}

bp::list PlanView::Materials() const {
    bp::list result;
    for (const MaterialData &material : data->materials) {
        bp::dict record;
        record["name"] = material.name;
        record["sources"] = PathList(material.sources);
        record["surface_identifier"] = material.surfaceIdentifier.GetString();
        record["parameters"] = Parameters(material.surfaceParameters);
        result.append(record);
    }
    return result;
}

bp::list PlanView::Objects() const {
    bp::list result;
    for (size_t i = 0; i < data->objects.size(); ++i) {
        const ObjectEntry &object = data->objects[i];
        bp::dict record;
        record["source"] = object.source.GetString();
        record["instance_context"] = bp::tuple(PathList(object.instanceContext));
        record["floor"] = data->correspondence.floors[i].GetString();
        record["mesh"] = object.mesh < 0 ? bp::object() : bp::object(object.mesh);
        record["placeholder_type"] =
            object.placeholderType.IsEmpty() ? bp::object() : bp::object(object.placeholderType.GetString());
        record["bounds"] = RangeOrNone(object.bounds);
        record["matrix"] = object.matrix;
        record["visible"] = object.visible;
        record["viewport"] = object.inViewport;
        record["render"] = object.inRender;
        record["purpose"] = object.purpose.GetString();
        bp::list slots;
        for (const int slot : object.materialSlots) slots.append(slot < 0 ? bp::object() : bp::object(slot));
        record["material_slots"] = slots;
        record["primvars"] = Parameters(object.constantPrimvars);
        record["properties"] = Properties(object.properties);
        result.append(record);
    }
    return result;
}

bp::list PlanView::Diagnostics() const { return DiagnosticList(data->diagnostics); }

bp::list PlanView::Universe() const { return PathList(data->correspondence.universe); }

namespace {

[[noreturn]] void Raise(PyObject *type, const std::string &message) {
    PyErr_SetString(type, message.c_str());
    bp::throw_error_already_set();
    throw std::logic_error("unreachable");
}

std::string String(const bp::object &value, const char *what) {
    const bp::extract<std::string> text(value);
    if (!text.check()) Raise(PyExc_TypeError, std::string(what) + " must be a string");
    return text();
}

// Prim purposes by their USD names; Hydra calls USD's default "geometry".
void SetPurposes(const bp::object &names, TfTokenVector &purposes) {
    if (names.is_none()) return;
    purposes.clear();
    const bp::list list(names);  // any iterable
    for (Py_ssize_t i = 0, n = bp::len(list); i < n; ++i) {
        const std::string name = String(list[i], "a purpose");
        if (name == "default")
            purposes.push_back(HdRenderTagTokens->geometry);
        else if (name == "proxy" || name == "render" || name == "guide")
            purposes.emplace_back(name);
        else
            Raise(PyExc_ValueError, "Unknown purpose '" + name + "': expected default, proxy, render, or guide");
    }
}

void SetMaterialPurpose(const bp::object &name, TfToken &purpose) {
    if (!name.is_none()) purpose = TfToken(String(name, "a material purpose"));
}

}  // namespace

PlanView MakePlan(const SnapshotView &snapshot, const bp::object &viewportPurposes,
                  const bp::object &viewportMaterialPurpose, const bp::object &renderPurposes,
                  const bp::object &renderMaterialPurpose) {
    PlanSettings settings;
    SetPurposes(viewportPurposes, settings.viewport.purposes);
    SetMaterialPurpose(viewportMaterialPurpose, settings.viewport.materialPurpose);
    SetPurposes(renderPurposes, settings.render.purposes);
    SetMaterialPurpose(renderMaterialPurpose, settings.render.materialPurpose);
    PlanPtr plan;
    {
        TF_PY_ALLOW_THREADS_IN_SCOPE();
        plan = BuildPlan(*snapshot.data, settings);
    }
    return PlanView{plan};
}

void WrapViews() {
    bp::class_<SnapshotView>("Snapshot", bp::no_init)
        .add_property("time", &SnapshotView::Time)
        .def("paths", &SnapshotView::Paths)
        .def("prim", &SnapshotView::Prim)
        .def("dump", &SnapshotView::Dump)
        .add_property("events", &SnapshotView::Events)
        .add_property(
            "copied", +[](const SnapshotView &view) { return view.data->copied; })
        .add_property("dirty_locators", &SnapshotView::DirtyLocators)
        .add_property("renames", &SnapshotView::Renames)
        .add_property("diagnostics", &SnapshotView::Diagnostics)
        .add_property("copy_bindings", &SnapshotView::CopyBindings);
    bp::class_<PlanView>("Plan", bp::no_init)
        .add_property("time", &PlanView::Time)
        .add_property("meshes", &PlanView::Meshes)
        .add_property("materials", &PlanView::Materials)
        .add_property("objects", &PlanView::Objects)
        .add_property("universe", &PlanView::Universe)
        .add_property("diagnostics", &PlanView::Diagnostics);
    bp::def("build_plan", MakePlan,
            (bp::arg("snapshot"), bp::arg("viewport_purposes") = bp::object(),
             bp::arg("viewport_material_purpose") = bp::object(), bp::arg("render_purposes") = bp::object(),
             bp::arg("render_material_purpose") = bp::object()));
}

}  // namespace hydra_bridge
