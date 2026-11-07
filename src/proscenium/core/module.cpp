// The compiled core's Python module, proscenium.core._core. It links only Blender's usd_ms.
//
// Each entry point translates errors as errors.h describes. Paths reach Python as strings, as the records store them.
#include <pxr/base/tf/diagnostic.h>
#include <pxr/base/tf/pyLock.h>
#include <pxr/pxr.h>

#include <memory>
#include <pxr/external/boost/python.hpp>
#include <stdexcept>
#include <string>
#include <vector>

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

PlanView MakePlan(const SnapshotView& snapshot, const PlanningContext& context) {
  return Guarded([&] {
    TF_PY_ALLOW_THREADS_IN_SCOPE();
    return PlanView{BuildPlan(*snapshot.data, context)};
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
  bp::class_<PlanningContext>("PlanningContext",
                              bp::init<double, int>((bp::arg("unit_scale"), bp::arg("representation_version"))))
      .add_property(
          "unit_scale", +[](const PlanningContext& c) { return c.unitScale; })
      .add_property("representation_version", +[](const PlanningContext& c) { return c.representationVersion; });
  bp::class_<Resource>("Resource", bp::no_init)
      .add_property(
          "role", +[](const Resource& r) { return RoleName(r.role); })
      .add_property(
          "entity", +[](const Resource& r) { return r.entity.GetString(); })
      .add_property(
          "place", +[](const Resource& r) { return r.place; })
      .add_property(
          "covers", +[](const Resource& r) { return PathStrings(r.covers); })
      .add_property("uses", +[](const Resource& r) { return ToTuple(r.uses); });
  bp::class_<Partition>("Partition", bp::no_init)
      .add_property("resources", +[](const Partition& p) { return ToTuple(p.resources); });
  bp::class_<CorrespondenceEntry>("CorrespondenceEntry", bp::no_init)
      .add_property(
          "element", +[](const CorrespondenceEntry& e) { return e.element; })
      .add_property(
          "source", +[](const CorrespondenceEntry& e) { return e.source.GetString(); })
      .add_property("instance_context", +[](const CorrespondenceEntry& e) { return PathStrings(e.instanceContext); });
  // Arrays cross as copy-on-write copies, sharing the plan's storage.
  bp::class_<GeometryDescription>("GeometryDescription", bp::no_init)
      .add_property(
          "source", +[](const GeometryDescription& g) { return g.source.GetString(); })
      .add_property(
          "extent", +[](const GeometryDescription& g) { return g.extent; })
      .add_property("content_key", +[](const GeometryDescription& g) { return g.contentKey; });
  bp::class_<PlanView>("Plan", bp::no_init)
      .add_property(
          "time_code", +[](const PlanView& p) { return p.data->time; })
      .add_property(
          "context", +[](const PlanView& p) { return p.data->context; })
      .add_property(
          "partitions", +[](const PlanView& p) { return ToTuple(p.data->partitions); })
      .add_property(
          "resources", +[](const PlanView& p) { return ToTuple(p.data->resources); })
      .add_property(
          "correspondence", +[](const PlanView& p) { return ToTuple(p.data->correspondence); })
      .add_property(
          "copy_count", +[](const PlanView& p) { return p.data->copyObjects.size(); })
      .add_property(
          "copy_worlds", +[](const PlanView& p) { return p.data->copyWorlds; })
      .add_property(
          "copy_objects", +[](const PlanView& p) { return p.data->copyObjects; })
      .add_property(
          "copy_geometries", +[](const PlanView& p) { return p.data->copyGeometries; })
      .add_property(
          "copy_placeholders", +[](const PlanView& p) { return p.data->copyPlaceholders; })
      .add_property(
          "placeholder_bounds", +[](const PlanView& p) { return p.data->placeholderBounds; })
      .add_property("geometries", +[](const PlanView& p) { return ToTuple(p.data->geometries); });
  bp::def("plan", &MakePlan, (bp::arg("snapshot"), bp::arg("context")));
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
