// Layer from File reads a layer: the process's shared copy of the file at its Path, which it never authors into
// (docs/phase3/node-tree.md "Layer from File"). Its cache holds the layer, so the cook keeps it open between cooks and
// a later cook finds the same copy rather than reading the file again.
#include <pxr/base/tf/errorMark.h>
#include <pxr/base/tf/token.h>
#include <pxr/usd/ar/resolver.h>
#include <pxr/usd/sdf/layer.h>

#include <optional>
#include <string>

#include "nodes/layer_from_file_attributes.h"
#include "nodes/node_types.h"

PXR_NAMESPACE_USING_DIRECTIVE

namespace proscenium {
namespace {

// The Tf errors mark has seen, one per line.
std::string ErrorText(const TfErrorMark& mark) {
  std::string text;
  for (const TfError& error : mark) {
    if (!text.empty()) text += "\n";
    text += error.GetCommentary();
  }
  return text;
}

}  // namespace

void RunLayerFromFile(TaskContext& context) {
  const LayerFromFileInputs inputs = ReadLayerFromFileInputs(context.Inputs());
  const TfToken pathName(LayerFromFileInputs::kPath);
  auto& layer = context.Cache<SdfLayerRefPtr>("layer");
  if (inputs.path.empty()) {
    layer = nullptr;
    context.ReportError(DiagnosticCode::kMissingPath, "Path names no file", context.AttributePath(pathName));
    return;
  }
  const std::optional<std::string> path = context.ExpandPath(inputs.path, pathName);
  if (!path) {
    layer = nullptr;
    return;
  }
  // An error the open raises when it fails is this node's own; one raised while it still succeeds is the scheduler's
  // to report.
  const TfErrorMark mark;
  layer = SdfLayer::FindOrOpen(*path);
  if (!layer) {
    const bool found = !ArGetResolver().Resolve(*path).empty();
    const std::string errors = ErrorText(mark);
    mark.Clear();
    if (!found) {
      context.ReportError(DiagnosticCode::kFileNotFound, "no file at \"" + *path + "\"",
                          context.AttributePath(pathName));
    } else {
      context.ReportError(DiagnosticCode::kUnreadableFile,
                          "\"" + *path + "\" isn't a layer USD reads" + (errors.empty() ? "" : ": " + errors),
                          context.AttributePath(pathName));
    }
    return;
  }
  LayerFromFileOutputs outputs;
  outputs.layer = layer;
  context.SetOutputs(WriteLayerFromFileOutputs(outputs));
}

}  // namespace proscenium
