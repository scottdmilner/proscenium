// Each node type's function, in its role's signature (node_roles.h), defined in the node type's own .cpp file beside
// this one and listed once in node_registry.cpp.
#pragma once

#include "node_contexts.h"

namespace proscenium {

void RunLayerFromFile(TaskContext& context);  // layer_from_file.cpp

// new_layer_zone.cpp: the begin's file, and the end's outputs.
ZoneFile NewLayerZoneFile(const NodeContext& context);
ValueOutputs NewLayerZoneOutputs(const PXR_NS::SdfLayerHandle& layer);

void RunStageOutput(TaskContext& context);  // stage_output.cpp
void RunViewer(TaskContext& context);       // viewer.cpp

}  // namespace proscenium
