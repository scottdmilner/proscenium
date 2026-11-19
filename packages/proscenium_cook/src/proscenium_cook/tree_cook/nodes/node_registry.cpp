#include "node_registry.h"

#include <cstring>

namespace proscenium {

const std::vector<NodeRegistration>& NodeRegistry() {
  // One line per node type, each declared in its own .cpp file beside this one. The first arrive with step 4 of
  // docs/plans/cook-module.md.
  static const std::vector<NodeRegistration> registry{};
  return registry;
}

const NodeRegistration* FindNodeRegistration(const char* typeName) {
  for (const NodeRegistration& registration : NodeRegistry()) {
    if (std::strcmp(registration.typeName, typeName) == 0) return &registration;
  }
  return nullptr;
}

}  // namespace proscenium
