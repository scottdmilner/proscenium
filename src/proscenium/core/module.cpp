// The compiled core's Python module, proscenium.core._core. It links only Blender's usd_ms.
//
// Each entry point translates errors as errors.h describes. Paths reach Python as strings, as the records store them.
#include <pxr/base/tf/diagnostic.h>
#include <pxr/base/tf/pyLock.h>
#include <pxr/pxr.h>

#include <memory>
#include <pxr/external/boost/python.hpp>
#include <pxr/external/boost/python/stl_iterator.hpp>
#include <stdexcept>
#include <string>
#include <vector>

#include "batch_groups.h"
#include "errors.h"
#include "plan.h"
#include "scene_index_chain.h"
#include "snapshot.h"
#include "stage_handle.h"

PXR_NAMESPACE_USING_DIRECTIVE

namespace bp = pxr_boost::python;

namespace proscenium {
namespace {

// Python's handles on the immutable snapshot and plan, which they keep alive.
struct SnapshotView {
  SnapshotPtr data;
};

struct PlanView {
  PlanPtr data;
};

// The OpenUSD release the module was compiled against, comparable with the host's pxr.Usd.GetVersion().
bp::tuple UsdVersion() { return bp::make_tuple(PXR_MAJOR_VERSION, PXR_MINOR_VERSION, PXR_PATCH_VERSION); }

// For tests of error translation only: posts a Tf runtime error, which the entry point raises, and then, if asked,
// throws a C++ exception, which joins it.
void PostTfError(const std::string& message, bool thenThrow) {
  Guarded([&] {
    TF_RUNTIME_ERROR("%s", message.c_str());
    if (thenThrow) throw std::runtime_error("Thrown after the Tf error");
  });
}

// The stage, or None once it has expired.
bp::object StageOrNone(const UsdStagePtr& stage) { return stage ? bp::object(stage) : bp::object(); }

template <class T>
bp::tuple ToTuple(const std::vector<T>& values) {
  bp::list items;
  for (const T& value : values) items.append(value);
  return bp::tuple(items);
}

bp::tuple PathStrings(const SdfPathVector& paths) {
  bp::list items;
  for (const SdfPath& path : paths) items.append(path.GetString());
  return bp::tuple(items);
}

// Building the chain reads the stage, so it can post Tf errors.
std::shared_ptr<SceneIndexChain> NewSceneIndexChain(const UsdStagePtr& stage) {
  return Guarded([&] { return std::make_shared<SceneIndexChain>(stage); });
}

SnapshotView Capture(SceneIndexChain& chain, const UsdTimeCode& time) {
  return Guarded([&] {
    TF_PY_ALLOW_THREADS_IN_SCOPE();
    return SnapshotView{chain.Capture(time)};
  });
}

// Each purpose name in an iterable of strings.
TfTokenVector Tokens(const bp::object& names) {
  TfTokenVector tokens;
  for (bp::stl_input_iterator<std::string> name(names), end; name != end; ++name) tokens.emplace_back(*name);
  return tokens;
}

bp::tuple TokenStrings(const TfTokenVector& tokens) {
  bp::list items;
  for (const TfToken& token : tokens) items.append(token.GetString());
  return bp::tuple(items);
}

std::shared_ptr<PlanSettings> NewPlanSettings(const bp::object& viewport, const bp::object& render, bool conversion) {
  TfTokenVector viewportPurposes = Tokens(viewport);
  TfTokenVector renderPurposes = Tokens(render);
  return Guarded([&] { return std::make_shared<PlanSettings>(viewportPurposes, renderPurposes, conversion); });
}

// The plan's batch groups, which Python reads as plain values and Vt buffers.
bp::tuple PlanBatchGroups(const PlanView& plan, std::size_t minimum) {
  const BatchGroups grouped = Guarded([&] {
    TF_PY_ALLOW_THREADS_IN_SCOPE();
    return GroupForBatches(*plan.data, minimum);
  });
  return bp::make_tuple(ToTuple(grouped.groups), grouped.unbatchedCopyIndices);
}

PlanView MakePlan(const SnapshotView& snapshot, const PlanSettings& settings, const PlanningContext& context) {
  return Guarded([&] {
    TF_PY_ALLOW_THREADS_IN_SCOPE();
    return PlanView{BuildPlan(*snapshot.data, settings, context)};
  });
}

// EXCEPTION to the rule against test-only API (with the user, 2026-11-06); see HydraComposedWorlds in plan.h.
bp::dict HydraComposedWorldsDict(const SnapshotView& snapshot) {
  const auto worlds = Guarded([&] { return HydraComposedWorlds(*snapshot.data); });
  bp::dict result;
  for (const auto& [source, world] : worlds) result[source.GetString()] = world;
  return result;
}

void WrapPlan() {
  bp::class_<Diagnostic>("Diagnostic", bp::no_init)
      .add_property(
          "code", +[](const Diagnostic& d) { return DiagnosticCodeName(d.code); })
      .add_property(
          "source_path", +[](const Diagnostic& d) { return d.sourcePath.GetString(); })
      .add_property(
          "message", +[](const Diagnostic& d) { return d.message; })
      .add_property(
          "property_path", +[](const Diagnostic& d) { return d.propertyPath.GetString(); })
      .add_property(
          "asset_identifier", +[](const Diagnostic& d) { return d.assetIdentifier; })
      .add_property("fallback_description", +[](const Diagnostic& d) { return d.fallbackDescription; });
  bp::def(
      "diagnostic_codes", +[] {
        bp::list names;
        for (const DiagnosticCode code : kDiagnosticCodes) names.append(DiagnosticCodeName(code));
        return bp::tuple(names);
      });
  bp::class_<PlanSettings, std::shared_ptr<PlanSettings>>("PlanSettings", bp::no_init)
      .def("__init__", bp::make_constructor(&NewPlanSettings, bp::default_call_policies(),
                                            (bp::arg("viewport_purposes"), bp::arg("render_purposes"),
                                             bp::arg("coordinate_conversion") = false)))
      .add_property(
          "viewport_purposes", +[](const PlanSettings& s) { return TokenStrings(s.viewportPurposes); })
      .add_property(
          "render_purposes", +[](const PlanSettings& s) { return TokenStrings(s.renderPurposes); })
      .add_property("coordinate_conversion", +[](const PlanSettings& s) { return s.coordinateConversion; });
  bp::class_<PlanningContext>("PlanningContext",
                              bp::init<double, int>((bp::arg("unit_scale"), bp::arg("representation_version"))))
      .add_property(
          "unit_scale", +[](const PlanningContext& c) { return c.unitScale; })
      .add_property("representation_version", +[](const PlanningContext& c) { return c.representationVersion; });
  bp::class_<PlannedResource>("PlannedResource", bp::no_init)
      .add_property(
          "role", +[](const PlannedResource& r) { return RoleName(r.role); })
      .add_property(
          "source_entity_path", +[](const PlannedResource& r) { return r.sourceEntityPath.GetString(); })
      .add_property(
          "object_index_in_copy", +[](const PlannedResource& r) { return r.objectIndexInCopy; })
      .add_property(
          "source_entity_paths", +[](const PlannedResource& r) { return PathStrings(r.sourceEntityPaths); })
      .add_property(
          "dependency_resource_indices",
          +[](const PlannedResource& r) { return ToTuple(r.dependencyResourceIndices); });
  bp::class_<Partition>("Partition", bp::no_init)
      .add_property("resource_indices", +[](const Partition& p) { return ToTuple(p.resourceIndices); });
  bp::class_<CorrespondenceEntry>("CorrespondenceEntry", bp::no_init)
      .add_property(
          "object_resource_index", +[](const CorrespondenceEntry& e) { return e.objectResourceIndex; })
      .add_property(
          "source_path", +[](const CorrespondenceEntry& e) { return e.sourcePath.GetString(); })
      .add_property("instance_context", +[](const CorrespondenceEntry& e) { return PathStrings(e.instanceContext); });
  // Arrays cross as copy-on-write copies, sharing the plan's storage.
  bp::class_<GeometryDescription>("GeometryDescription", bp::no_init)
      .add_property(
          "representative_source_path",
          +[](const GeometryDescription& g) { return g.representativeSourcePath.GetString(); })
      .add_property(
          "extent", +[](const GeometryDescription& g) { return g.extent; })
      .add_property("content_key", +[](const GeometryDescription& g) { return g.contentKey; });
  bp::class_<BatchGroup>("BatchGroup", bp::no_init)
      .add_property(
          "geometry_index", +[](const BatchGroup& g) { return g.geometryIndex; })
      .add_property(
          "visible_in_viewport", +[](const BatchGroup& g) { return g.visibleInViewport; })
      .add_property(
          "visible_in_render", +[](const BatchGroup& g) { return g.visibleInRender; })
      .add_property(
          "coincident_copy_index", +[](const BatchGroup& g) { return g.coincidentCopyIndex; })
      .add_property("copy_indices", +[](const BatchGroup& g) { return g.copyIndices; });
  bp::class_<PlanView>("Plan", bp::no_init)
      .def("batch_groups", &PlanBatchGroups, bp::arg("minimum"))
      .add_property(
          "time_code", +[](const PlanView& p) { return p.data->timeCode; })
      .add_property(
          "context", +[](const PlanView& p) { return p.data->context; })
      .add_property(
          "partitions", +[](const PlanView& p) { return ToTuple(p.data->partitions); })
      .add_property(
          "resources", +[](const PlanView& p) { return ToTuple(p.data->resources); })
      .add_property(
          "correspondence", +[](const PlanView& p) { return ToTuple(p.data->correspondence); })
      .add_property(
          "copy_count", +[](const PlanView& p) { return p.data->copyObjectResourceIndices.size(); })
      .add_property(
          "copy_world_matrices", +[](const PlanView& p) { return p.data->copyWorldMatrices; })
      .add_property(
          "copy_object_resource_indices", +[](const PlanView& p) { return p.data->copyObjectResourceIndices; })
      .add_property(
          "copy_geometry_indices", +[](const PlanView& p) { return p.data->copyGeometryIndices; })
      .add_property(
          "copy_placeholder_bounds_indices", +[](const PlanView& p) { return p.data->copyPlaceholderBoundsIndices; })
      .add_property(
          "placeholder_bounds", +[](const PlanView& p) { return p.data->placeholderBounds; })
      .add_property(
          "copy_visible_in_viewport", +[](const PlanView& p) { return p.data->copyVisibleInViewport; })
      .add_property(
          "copy_visible_in_render", +[](const PlanView& p) { return p.data->copyVisibleInRender; })
      .add_property(
          "copy_shear_split_indices", +[](const PlanView& p) { return p.data->copyShearSplitIndices; })
      .add_property(
          "shear_parent_world_matrices", +[](const PlanView& p) { return p.data->shearParentWorldMatrices; })
      .add_property(
          "shear_object_basis_matrices", +[](const PlanView& p) { return p.data->shearObjectBasisMatrices; })
      .add_property(
          "geometries", +[](const PlanView& p) { return ToTuple(p.data->geometries); })
      .add_property("diagnostics", +[](const PlanView& p) { return ToTuple(p.data->diagnostics); });
  bp::def("plan", &MakePlan, (bp::arg("snapshot"), bp::arg("settings"), bp::arg("context")));
  bp::def("_hydra_composed_worlds", &HydraComposedWorldsDict, bp::arg("snapshot"));
}

}  // namespace
}  // namespace proscenium

PXR_BOOST_PYTHON_MODULE(_core) {
  using namespace proscenium;
  bp::def("usd_version", &UsdVersion);
  bp::def("_post_tf_error", &PostTfError, (bp::arg("message"), bp::arg("then_throw") = false));
  bp::class_<StageHandle, bp::noncopyable>("StageHandle", bp::init<UsdStagePtr>())
      .def(
          "stage", +[](const StageHandle& h) { return StageOrNone(h.Stage()); })
      .def("release", &StageHandle::Release)
      .add_property("released", &StageHandle::Released);
  bp::class_<SceneIndexChain, std::shared_ptr<SceneIndexChain>, bp::noncopyable>("SceneIndexChain", bp::no_init)
      .def("__init__", bp::make_constructor(&NewSceneIndexChain))
      .def(
          "stage", +[](const SceneIndexChain& c) { return StageOrNone(c.Stage()); })
      .def("capture", &Capture, bp::arg("time_code"))
      .def("release", &SceneIndexChain::Release)
      .add_property("released", &SceneIndexChain::Released);
  // Opaque: only planning reads a snapshot.
  const bp::class_<SnapshotView> snapshot("Snapshot", bp::no_init);
  WrapPlan();
}
