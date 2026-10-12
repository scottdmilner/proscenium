#include "python_views.h"

#include "prim_reader.h"

#include <pxr/base/tf/pyLock.h>
#include <pxr/imaging/hd/dataSource.h>
#include <pxr/imaging/hd/sceneIndexPrimView.h>
#include <pxr/imaging/hd/tokens.h>

#include <sstream>

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

bp::dict PrimDict(const PrimRecord &prim) {
    bp::dict record;
    record["type"] = prim.type.GetString();
    record["usd_type"] = prim.usdTypeName.GetString();
    record["origin"] = PathOrNone(prim.originPath);
    record["matrix"] = prim.matrix ? bp::object(*prim.matrix) : bp::object();
    record["visible"] = prim.visible;
    record["purpose"] = prim.purpose.GetString();
    record["material_binding"] = PathOrNone(prim.materialBinding);
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
    if (!SdfPath::IsValidPathString(path) || !ReadPrim(*data->scene, SdfPath(path), record)) return bp::object();
    return PrimDict(record);
}

bp::object SnapshotView::Dump(const std::string &path) const {
    if (!SdfPath::IsValidPathString(path)) return bp::object();
    HdSceneIndexPrim prim = data->scene->GetPrim(SdfPath(path));
    if (!prim.dataSource) return bp::object();
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
        bp::list slots;
        for (int slot : mesh.materialSlots) slots.append(slot < 0 ? bp::object() : bp::object(slot));
        record["material_slots"] = slots;
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
    for (const ObjectEntry &object : data->objects) {
        bp::dict record;
        record["source"] = object.source.GetString();
        record["instance_context"] = bp::tuple(PathList(object.instanceContext));
        record["mesh"] = object.mesh < 0 ? bp::object() : bp::object(object.mesh);
        record["placeholder_type"] = object.placeholderType.IsEmpty() ? bp::object() : bp::object(object.placeholderType.GetString());
        record["matrix"] = object.matrix;
        record["visible"] = object.visible;
        record["purpose"] = object.purpose.GetString();
        record["primvars"] = Parameters(object.constantPrimvars);
        result.append(record);
    }
    return result;
}

bp::list PlanView::Diagnostics() const { return DiagnosticList(data->diagnostics); }

PlanView MakePlan(const SnapshotView &snapshot) {
    PlanPtr plan;
    {
        TF_PY_ALLOW_THREADS_IN_SCOPE();
        plan = BuildPlan(*snapshot.data);
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
        .add_property("dirty_locators", &SnapshotView::DirtyLocators)
        .add_property("renames", &SnapshotView::Renames)
        .add_property("diagnostics", &SnapshotView::Diagnostics);
    bp::class_<PlanView>("Plan", bp::no_init)
        .add_property("time", &PlanView::Time)
        .add_property("meshes", &PlanView::Meshes)
        .add_property("materials", &PlanView::Materials)
        .add_property("objects", &PlanView::Objects)
        .add_property("diagnostics", &PlanView::Diagnostics);
    bp::def("build_plan", MakePlan);
}

}  // namespace hydra_bridge
