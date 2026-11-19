// Stage Output names one of the tree's stages: the stage composed on the layer linked into it, with every payload
// loaded (docs/phase3/node-tree.md "Stage Output"). Its cache keeps the stage, and each cook returns the same one while
// its root layer stays the same: a binding reuses its evaluation stage only while the source stage's root and session
// layers stay the same (docs/spec/source-access.md "Source Stages"), and tools may author in the session layer. Its
// coordinate conversion setting is the front end's: the cook doesn't convert.
#include <pxr/base/tf/stringUtils.h>
#include <pxr/base/tf/token.h>
#include <pxr/usd/sdf/layer.h>
#include <pxr/usd/sdf/path.h>
#include <pxr/usd/usd/stage.h>
#include <pxr/usd/usdGeom/tokens.h>

#include <string>
#include <vector>

#include "nodes/node_types.h"
#include "nodes/stage_output_attributes.h"

PXR_NAMESPACE_USING_DIRECTIVE

namespace proscenium {
namespace {

// Warns when the root layer authors no upAxis or metersPerUnit. Stage metadata comes from the root layer only, so the
// stage then falls back to Y-up and centimeters, whatever its sublayers author (docs/phase3/node-tree.md "Stage
// Outputs and the Viewer").
void ReportMissingMetrics(const TaskContext& context, const SdfLayerHandle& rootLayer) {
  std::vector<std::string> missing;
  if (!rootLayer->HasField(SdfPath::AbsoluteRootPath(), UsdGeomTokens->upAxis)) {
    missing.emplace_back("upAxis, so it's Y-up");
  }
  if (!rootLayer->HasField(SdfPath::AbsoluteRootPath(), UsdGeomTokens->metersPerUnit)) {
    missing.emplace_back("metersPerUnit, so its unit is the centimeter");
  }
  if (missing.empty()) return;
  context.ReportWarning(
      DiagnosticCode::kMissingStageMetrics,
      "the stage's root layer \"" + rootLayer->GetIdentifier() + "\" authors no " + TfStringJoin(missing, ", and no "));
}

}  // namespace

void RunStageOutput(TaskContext& context) {
  const StageOutputInputs inputs = ReadStageOutputInputs(context.Inputs());
  auto& stage = context.Cache<UsdStageRefPtr>("stage");
  if (!inputs.layer.layer) {
    stage = nullptr;
    // A link that brings nothing has its warning already, naming the node it comes from.
    const TfToken layerName(StageOutputInputs::kLayer);
    if (!context.IsLinked(layerName)) {
      context.ReportWarning(DiagnosticCode::kUnlinkedInput, "no layer is linked, so there's no stage",
                            context.AttributePath(layerName));
    }
    return;
  }
  ReportMissingMetrics(context, inputs.layer.layer);
  if (!stage || stage->GetRootLayer() != inputs.layer.layer)
    stage = UsdStage::Open(inputs.layer.layer, UsdStage::LoadAll);
  context.SetStageOutput(stage);
}

}  // namespace proscenium
