#include "node_registry.h"

#include <cstring>

#include "nodes/node_types.h"

namespace proscenium {

const std::vector<NodeRegistration>& NodeRegistry() {
  // One line per node type, each defined in its own .cpp file beside this one and declared in node_types.h.
  static const std::vector<NodeRegistration> registry{
      {"CreatePrim", AuthoringRole{AuthorCreatePrim, CreatePrimPath}},
      {"LayerFromFile", TaskRole{RunLayerFromFile, LayerFromFileFile}},
      {"NewLayerZoneBegin", ZoneRole{NewLayerZoneFile, NewLayerZoneTemplate, nullptr, nullptr}},
      {"NewLayerZoneEnd", ZoneRole{nullptr, nullptr, NewLayerZoneFinish, NewLayerZoneOutputs}},
      {"Prim", ValueRole{ComputePrim}},
      {"StageOutput", TaskRole{RunStageOutput, nullptr}},
      {kViewerType, TaskRole{RunViewer, nullptr}},
  };
  return registry;
}

const NodeRegistration* FindNodeRegistration(const char* typeName) {
  for (const NodeRegistration& registration : NodeRegistry()) {
    if (std::strcmp(registration.typeName, typeName) == 0) return &registration;
  }
  return nullptr;
}

}  // namespace proscenium
