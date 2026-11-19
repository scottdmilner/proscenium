// Each node type's function, in its role's signature (node_roles.h), defined in the node type's own .cpp file beside
// this one and listed once in node_registry.cpp.
#pragma once

#include "node_contexts.h"

namespace proscenium {

void RunLayerFromFile(TaskContext& context);  // layer_from_file.cpp
void RunStageOutput(TaskContext& context);    // stage_output.cpp

}  // namespace proscenium
