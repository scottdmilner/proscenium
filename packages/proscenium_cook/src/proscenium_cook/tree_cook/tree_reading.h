// Reading the tree from its layer, through Sdf only, never the composed stage (docs/phase3/node-tree.md "The tree as
// plain data"), and checking it against the node definitions. Every problem becomes a diagnostic: the tree's own
// when it isn't a tree this cook reads, and otherwise a node's, on the node it concerns.
#pragma once

#include <pxr/base/tf/token.h>
#include <pxr/pxr.h>
#include <pxr/usd/sdf/layer.h>
#include <pxr/usd/sdf/path.h>
#include <pxr/usd/sdf/primSpec.h>

#include <cstddef>
#include <map>
#include <string>
#include <vector>

#include "cook_diagnostics.h"
#include "node_definitions.h"
#include "nodes/node_registry.h"

namespace proscenium {

// The tree format this cook reads, tree:format on /Tree.
inline constexpr int kTreeFormat = 1;

// One link into an input: the node and output it comes from.
struct NodeLink {
  std::size_t sourceNode = 0;       // its index in TreeNodes::nodes
  PXR_NS::TfToken sourceAttribute;  // such as outputs:layer
};

// One node of the tree.
struct TreeNode {
  std::string id;  // its node ID, decoded from its prim name
  PXR_NS::SdfPrimSpecHandle spec;
  PXR_NS::TfToken typeName;
  const NodeDefinition* definition = nullptr;      // null for a type the definitions don't hold
  const NodeRegistration* registration = nullptr;  // null when definition is
  bool muted = false;
  // Its inputs' links, by input attribute name, each in connection order. Only links that resolve are here.
  std::map<PXR_NS::TfToken, std::vector<NodeLink>> links;
  bool onCycle = false;  // set by NodeGraph
  // Whether it can run: its type is known, it's off every cycle, and the checks found no error on it.
  bool runnable = false;
};

// The tree's nodes, in node-ID order, and the diagnostics reading them gave.
struct TreeNodes {
  std::vector<TreeNode> nodes;
  bool readable = false;  // false when the layer isn't a tree this cook reads, so there are no nodes
};

// Reads and checks the tree in layer, adding each problem to diagnostics. A layer that isn't a tree this cook reads
// (no /Tree, not a NodeTree, another tree:format) leaves no nodes; the tree's other errors, a sublayer, an arc, or a
// prim name that isn't a node ID, leave the rest of the nodes.
TreeNodes ReadTree(const PXR_NS::SdfLayerHandle& layer, const NodeDefinitions& definitions,
                   CookDiagnostics& diagnostics);

}  // namespace proscenium
