#include "tree_cook.h"

#include <stdexcept>
#include <type_traits>
#include <utility>
#include <variant>

#include "node_graph.h"
#include "tree_reading.h"

PXR_NAMESPACE_USING_DIRECTIVE

namespace proscenium {

TreeCook::TreeCook(UsdStageRefPtr treeStage, std::string baseDirectory,
                   std::shared_ptr<const NodeDefinitions> definitions)
    : treeStage_(std::move(treeStage)), baseDirectory_(std::move(baseDirectory)), definitions_(std::move(definitions)) {
  if (!treeStage_) throw std::invalid_argument("TreeCook needs the tree's stage");
  if (!definitions_) throw std::invalid_argument("TreeCook needs the node definitions");
}

CookResult TreeCook::Cook() {
  CookDiagnostics diagnostics;
  TreeNodes tree = ReadTree(treeStage_->GetRootLayer(), *definitions_, diagnostics);
  const NodeGraph graph(tree, diagnostics);

  // Each node's committed outputs this cook, by node index.
  std::vector<ValueOutputs> outputs(tree.nodes.size());
  const TreeInputReader::OutputValues valueOf = [&](const OutputRef& ref) {
    const auto found = outputs[ref.node].find(ref.attributeName);
    return found == outputs[ref.node].end() ? VtValue() : found->second;
  };

  // The scheduler: every node that can run, serially, upstream first, so each reads its upstream nodes' committed
  // outputs. A muted node doesn't run: its consumers read through it (NodeGraph::Sources).
  // Every node of the tree keeps its cache, whether or not it runs this cook; a node gone from the tree drops its.
  std::map<std::pair<std::string, TfToken>, NodeCache> caches;
  for (const TreeNode& node : tree.nodes) {
    const std::pair<std::string, TfToken> key{node.id, node.typeName};
    caches[key] = std::move(caches_[key]);
  }
  for (const std::size_t index : graph.Order()) {
    const TreeNode& node = tree.nodes[index];
    NodeCache& cache = caches[{node.id, node.typeName}];
    if (!node.runnable || node.muted) continue;
    const TreeInputReader inputs(tree, graph, index, valueOf);
    std::visit(
        [&](const auto& role) {
          using Role = std::decay_t<decltype(role)>;
          if constexpr (std::is_same_v<Role, ValueRole>) {
            outputs[index] = role.compute(ValueInputs(node, inputs, cache, diagnostics));
          } else if constexpr (std::is_same_v<Role, TaskRole>) {
            TaskContext context(node, inputs, cache, diagnostics, outputs[index]);
            role.run(context);
          }
          // Authoring and zone nodes run inside their zone's task, from step 6 of the plan.
        },
        node.registration->behavior);
  }
  caches_ = std::move(caches);

  CookResult result;
  result.treeDiagnostics = std::move(diagnostics.tree);
  for (auto& [nodeId, nodeDiagnostics] : diagnostics.byNode) {
    result.nodeReports[nodeId].diagnostics = std::move(nodeDiagnostics);
  }
  return result;
}

}  // namespace proscenium
