// Viewer names the stage the editor's UI shows (docs/phase3/node-tree.md "Viewer"). On a Layer, its stage is composed
// on that layer, as a Stage Output's is, and isn't converted, since it feeds no binding. Partway down a chain, its
// Layer is the copy its zone's task makes there, of the layer as the chain has left it (tree_cook.cpp). Its Context
// does nothing yet: only a New Layer Zone's layer has a context to compose over. Unlinked, it has no stage, and reports
// nothing, since the editor shows that there's nothing to view.
#include "nodes/composed_stage.h"
#include "nodes/node_types.h"
#include "nodes/viewer_attributes.h"

PXR_NAMESPACE_USING_DIRECTIVE

namespace proscenium {

void RunViewer(TaskContext& context) {
  const ViewerInputs inputs = ReadViewerInputs(context.Inputs());
  if (const UsdStageRefPtr stage = ComposedStage(context, inputs.layer.layer)) context.SetViewerStage(stage);
}

}  // namespace proscenium
