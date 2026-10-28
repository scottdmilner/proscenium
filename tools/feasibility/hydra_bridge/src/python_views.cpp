#include "python_views.h"

#include "plan_diff.h"
#include "prim_reader.h"

#include <pxr/base/tf/pyLock.h>
#include <pxr/imaging/hd/dataSource.h>
#include <pxr/imaging/hd/sceneIndexPrimView.h>
#include <pxr/imaging/hd/tokens.h>

#include <array>
#include <optional>
#include <sstream>
#include <stdexcept>
#include <utility>

PXR_NAMESPACE_USING_DIRECTIVE

namespace hydra_bridge {

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

// The absolute root or an absolute prim path, from an Sdf.Path or a string through Sdf's own converter; any other
// path raises ValueError, unless `lenient`, when it is the empty path.
SdfPath PrimPath(const bp::object &value, bool lenient = false) {
    // Sdf's converter prints a warning for a malformed string, so strings are checked first.
    const bp::extract<std::string> text(value);
    const bool wellFormed = !text.check() || SdfPath::IsValidPathString(text());
    const bp::extract<SdfPath> path(value);
    if (!path.check()) Raise(PyExc_TypeError, "a path must be an Sdf.Path or a string");
    if (wellFormed) {
        SdfPath result = path();
        if (result.IsAbsolutePath() && result.IsAbsoluteRootOrPrimPath()) return result;
    }
    if (lenient) return {};
    Raise(PyExc_ValueError,
          "'" + bp::extract<std::string>(bp::str(value))() + "' is not the absolute root or an absolute prim path");
}

SdfPathVector PrimPaths(const bp::object &values, bool lenient = false) {
    const bp::list list(values);  // any iterable
    SdfPathVector paths;
    for (Py_ssize_t i = 0, n = bp::len(list); i < n; ++i) paths.push_back(PrimPath(list[i], lenient));
    return paths;
}

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

bp::object SnapshotView::Prim(const bp::object &path) const {
    const SdfPath primPath = PrimPath(path, true);
    PrimRecord record;
    if (primPath.IsEmpty() || !ReadPrim(*data->scene, primPath, record)) return {};
    return PrimDict(record);
}

bp::object SnapshotView::Dump(const bp::object &path) const {
    const SdfPath primPath = PrimPath(path, true);
    if (primPath.IsEmpty()) return {};
    const HdSceneIndexPrim prim = data->scene->GetPrim(primPath);
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

std::size_t Element(const bp::object &value) {
    const bp::extract<std::size_t> element(value);
    if (!element.check()) Raise(PyExc_TypeError, "an element must be a non-negative integer");
    return element();
}

std::optional<TfToken> Level(const bp::object &value) {
    if (value.is_none()) return std::nullopt;
    TfToken level(String(value, "a level"));
    try {
        Interaction::CheckLevel(level);
    } catch (const std::invalid_argument &error) {
        Raise(PyExc_ValueError, error.what());
    }
    return level;
}

// Runs `call` without the GIL, and raises the source's unavailability as RuntimeError.
template <class Call>
auto Unlocked(const Call &call) {
    std::optional<std::string> unavailable;
    std::optional<decltype(call())> result;
    {
        TF_PY_ALLOW_THREADS_IN_SCOPE();
        try {
            result = call();
        } catch (const SourceUnavailableError &error) {
            unavailable = error.what();
        }
    }
    if (unavailable) Raise(PyExc_RuntimeError, *unavailable);
    return std::move(*result);
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

InteractionView::InteractionView(const UsdStagePtr &stage, const PlanView &plan)
    : interaction(stage, plan.data) {
    if (!stage) Raise(PyExc_ValueError, "the live stage is invalid");
}

bp::object InteractionView::ResolvePick(std::size_t element) const {
    const std::optional<Entity> entity = Unlocked([&] { return interaction.ResolvePick(element); });
    if (!entity) return {};
    bp::dict record;
    record["source"] = entity->source.GetString();
    record["instance_context"] = bp::tuple(PathList(entity->instanceContext));
    record["floor"] = Floor(*entity).GetString();
    return std::move(record);
}

bp::list InteractionView::SelectTargets(const bp::object &entities, const bp::object &level) const {
    std::vector<Entity> values;
    const bp::list list(entities);
    for (Py_ssize_t i = 0, n = bp::len(list); i < n; ++i) {
        const bp::tuple pair(list[i]);
        if (bp::len(pair) != 2) Raise(PyExc_TypeError, "an entity must be a (source, instance context) pair");
        values.push_back(Entity{PrimPath(pair[0]), PrimPaths(pair[1])});
    }
    const std::optional<TfToken> kind = Level(level);
    return PathList(Unlocked([&] { return interaction.SelectTargets(values, kind); }));
}

bp::list InteractionView::Displayed(const bp::object &paths) const {
    const SdfPathVector values = PrimPaths(paths, true);
    bp::list result;
    for (const bool displayed : Unlocked([&] { return interaction.Displayed(values); })) result.append(displayed);
    return result;
}

bp::list InteractionView::HighlightTargets(const bp::object &targets) const {
    const SdfPathVector values = PrimPaths(targets);
    bp::list result;
    for (const std::size_t element : Unlocked([&] { return interaction.HighlightTargets(values); }))
        result.append(element);
    return result;
}

bp::dict InteractionView::SelectionFromBlender(const bp::object &selected, const bp::object &active,
                                               const bp::object &level) const {
    std::vector<std::size_t> elements;
    const bp::list list(selected);
    for (Py_ssize_t i = 0, n = bp::len(list); i < n; ++i) elements.push_back(Element(list[i]));
    const std::optional<std::size_t> activeElement =
        active.is_none() ? std::nullopt : std::optional<std::size_t>(Element(active));
    const std::optional<TfToken> kind = Level(level);
    const SourceSelection selection =
        Unlocked([&] { return interaction.SelectionFromBlender(elements, activeElement, kind); });
    bp::dict result;
    result["targets"] = PathList(selection.targets);
    result["active"] = PathOrNone(selection.active);
    return result;
}

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

bp::dict DiffPlanViews(const PlanView &published, const PlanView &next) {
    PlanDiff diff;
    {
        TF_PY_ALLOW_THREADS_IN_SCOPE();
        diff = DiffPlans(*published.data, *next.data);
    }
    const auto list = [](const std::vector<int> &values) {
        bp::list result;
        for (const int value : values) result.append(value);
        return result;
    };
    bp::dict result;
    result["meshes"] = list(diff.meshes);
    result["materials"] = list(diff.materials);
    result["objects"] = list(diff.objects);
    result["changed"] = list(diff.changed);
    result["removed"] = list(diff.removed);
    return result;
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
    bp::class_<InteractionView>("Interaction", bp::init<UsdStagePtr, PlanView>())
        .def("resolve_pick", &InteractionView::ResolvePick)
        .def("select_targets", &InteractionView::SelectTargets, (bp::arg("entities"), bp::arg("level") = bp::object()))
        .def("displayed", &InteractionView::Displayed)
        .def("highlight_targets", &InteractionView::HighlightTargets)
        .def("selection_from_blender", &InteractionView::SelectionFromBlender,
             (bp::arg("selected"), bp::arg("active") = bp::object(), bp::arg("level") = bp::object()));
    bp::def("build_plan", MakePlan,
            (bp::arg("snapshot"), bp::arg("viewport_purposes") = bp::object(),
             bp::arg("viewport_material_purpose") = bp::object(), bp::arg("render_purposes") = bp::object(),
             bp::arg("render_material_purpose") = bp::object()));
    bp::def("diff_plans", DiffPlanViews, (bp::arg("published"), bp::arg("next")));
}

}  // namespace hydra_bridge
