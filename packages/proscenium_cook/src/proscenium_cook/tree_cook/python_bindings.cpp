// The cook's Python module, proscenium_cook.tree_cook._cook. It links only Blender's usd_ms.
//
// Each entry point translates errors as python_error_translation.h describes. A cook's result crosses as plain Python
// data, which proscenium_cook.cook_api turns into the package's own types; paths cross as strings.
#include <pxr/base/tf/makePyConstructor.h>
#include <pxr/base/tf/token.h>
#include <pxr/pxr.h>

#include <memory>
#include <pxr/external/boost/python.hpp>
#include <string>
#include <utility>

#include "cook_diagnostics.h"
#include "node_definitions.h"
#include "node_ids.h"
#include "python_error_translation.h"
#include "tree_cook.h"

PXR_NAMESPACE_USING_DIRECTIVE

namespace bp = pxr_boost::python;

namespace proscenium {
namespace {

// The OpenUSD release the module was compiled against, comparable with the host's pxr.Usd.GetVersion().
bp::tuple UsdVersion() { return bp::make_tuple(PXR_MAJOR_VERSION, PXR_MINOR_VERSION, PXR_PATCH_VERSION); }

bp::list DiagnosticCodes() {
  bp::list codes;
  for (const DiagnosticCode code : kDiagnosticCodes) codes.append(std::string(DiagnosticCodeName(code)));
  return codes;
}

// The tree prim name a node ID maps to (node_ids.h), so the front end writes the names the cook decodes.
std::string PrimName(const std::string& nodeId) {
  return Guarded([&] { return PrimNameFromNodeId(nodeId); });
}

std::shared_ptr<NodeDefinitions> LoadNodeDefinitions(const std::string& path) {
  return Guarded([&] { return std::make_shared<NodeDefinitions>(path); });
}

bp::list TypeNames(const NodeDefinitions& definitions) {
  bp::list names;
  for (const TfToken& name : definitions.TypeNames()) names.append(name.GetString());
  return names;
}

std::shared_ptr<TreeCook> NewTreeCook(const UsdStageRefPtr& treeStage, const std::string& baseDirectory,
                                      const std::shared_ptr<NodeDefinitions>& definitions) {
  return Guarded([&] { return std::make_shared<TreeCook>(treeStage, baseDirectory, definitions); });
}

// A diagnostic as (severity, code, message, source_path), source_path empty for none.
bp::tuple DiagnosticTuple(const NodeDiagnostic& diagnostic) {
  return bp::make_tuple(std::string(SeverityName(diagnostic.severity)),
                        std::string(DiagnosticCodeName(diagnostic.code)), diagnostic.message,
                        diagnostic.sourcePath.GetString());
}

bp::list DiagnosticTuples(const std::vector<NodeDiagnostic>& diagnostics) {
  bp::list tuples;
  for (const NodeDiagnostic& diagnostic : diagnostics) tuples.append(DiagnosticTuple(diagnostic));
  return tuples;
}

// The stage as a Usd.Stage that Python owns. pxr's Python holds a stage by weak pointer, so a stage converted as a
// plain RefPtr would expire with the result; the factory hands Python ownership, as Usd.Stage.Open's binding does.
bp::object OwnedStage(const UsdStageRefPtr& stage) {
  using Factory = TfPyRefPtrFactory<>::apply<UsdStageRefPtr>::type;
  return bp::object(bp::handle<>(Factory()(stage)));
}

// The stages by node ID, each one Python owns (OwnedStage).
bp::dict Stages(const std::map<std::string, UsdStageRefPtr>& stages) {
  bp::dict byNode;
  for (const auto& [nodeId, stage] : stages) byNode[nodeId] = OwnedStage(stage);
  return byNode;
}

// The result, with viewer the active Viewer's node ID ("" for none), as a dict of stage_outputs, viewer_stage (None for
// none), node_reports (node ID to (diagnostics, report_data)), and tree_diagnostics.
bp::dict Cook(TreeCook& cook, const std::string& viewer) {
  const CookResult result = Guarded([&] { return cook.Cook(viewer); });
  bp::dict reports;
  for (const auto& [nodeId, report] : result.nodeReports) {
    reports[nodeId] = bp::make_tuple(DiagnosticTuples(report.diagnostics), report.reportData);
  }
  bp::dict out;
  out["stage_outputs"] = Stages(result.stageOutputs);
  out["viewer_stage"] = result.viewerStage ? OwnedStage(result.viewerStage) : bp::object();
  out["node_reports"] = reports;
  out["tree_diagnostics"] = DiagnosticTuples(result.treeDiagnostics);
  return out;
}

}  // namespace
}  // namespace proscenium

PXR_BOOST_PYTHON_MODULE(_cook) {
  using namespace proscenium;
  bp::def("usd_version", &UsdVersion);
  bp::def("diagnostic_codes", &DiagnosticCodes);
  bp::def("prim_name_from_node_id", &PrimName, (bp::arg("node_id")));
  bp::class_<NodeDefinitions, std::shared_ptr<NodeDefinitions>, bp::noncopyable>("NodeDefinitions", bp::no_init)
      .def("__init__", bp::make_constructor(&LoadNodeDefinitions))
      .def("type_names", &TypeNames);
  bp::class_<TreeCook, std::shared_ptr<TreeCook>, bp::noncopyable>("TreeCook", bp::no_init)
      .def("__init__", bp::make_constructor(&NewTreeCook))
      .def("cook", &Cook, (bp::arg("viewer")));
}
