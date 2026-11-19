#include "node_registry.h"

#include <cstring>

#include "nodes/node_types.h"

namespace proscenium {

const std::vector<NodeRegistration>& NodeRegistry() {
  // One line per node type, each defined in its own .cpp file beside this one and declared in node_types.h.
  static const std::vector<NodeRegistration> registry{
      {"LayerFromFile", TaskRole{RunLayerFromFile}},
      {"NewLayerZoneBegin", ZoneRole{NewLayerZoneFile, nullptr}},
      {"NewLayerZoneEnd", ZoneRole{nullptr, NewLayerZoneOutputs}},
      {"StageOutput", TaskRole{RunStageOutput}},
      {"Viewer", TaskRole{RunViewer}},
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
