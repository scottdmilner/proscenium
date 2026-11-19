// Each node type's function, in its role's signature (node_roles.h), defined in the node type's own .cpp file beside
// this one and listed once in node_registry.cpp.
#pragma once

#include "node_contexts.h"

namespace proscenium {

// layer_from_file.cpp: the layer it reads, and its file.
void RunLayerFromFile(TaskContext& context);
NodeFile LayerFromFileFile(const NodeContext& context);

// new_layer_zone.cpp: the begin's file and Template, and the end's outputs.
NodeFile NewLayerZoneFile(const NodeContext& context);
std::optional<PXR_NS::SdfLayerHandle> NewLayerZoneTemplate(const NodeContext& context);
ValueOutputs NewLayerZoneOutputs(const PXR_NS::SdfLayerHandle& layer);

void RunStageOutput(TaskContext& context);  // stage_output.cpp
void RunViewer(TaskContext& context);       // viewer.cpp

}  // namespace proscenium
