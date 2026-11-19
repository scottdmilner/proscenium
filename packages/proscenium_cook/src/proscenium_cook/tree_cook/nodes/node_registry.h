// The one list of node types the cook implements. Node types don't register themselves through static objects: a
// static library's linker drops translation units nothing references, and their registration with them, so a node
// would disappear with no error. Loading the node definitions checks this list against them (node_definitions.h).
#pragma once

#include <vector>

#include "node_roles.h"

namespace proscenium {

struct NodeRegistration {
  const char* typeName;   // the node type's name, as its definition's class prim names it
  NodeBehavior behavior;  // its role's function
};

// Every node type, in the order node_registry.cpp lists them.
const std::vector<NodeRegistration>& NodeRegistry();

// The type's registration, or null for a type the registry doesn't hold.
const NodeRegistration* FindNodeRegistration(const char* typeName);

}  // namespace proscenium
