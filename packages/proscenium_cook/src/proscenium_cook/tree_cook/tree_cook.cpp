#include "tree_cook.h"

#include <pxr/base/tf/errorMark.h>

#include <map>
#include <stdexcept>
#include <type_traits>
#include <utility>
#include <variant>

#include "node_graph.h"
#include "tree_reading.h"

PXR_NAMESPACE_USING_DIRECTIVE

namespace proscenium {
namespace {

// Warns once for each node whose output one of this node's links traces back to but that brings nothing: it failed,
// can't run, or is muted with nothing to pass through (docs/plans/cook-module.md "Order and results"). The warning
// names that node, whose own diagnostic says why, and the first input it fails to reach. The node still runs,
// without those values.
void ReportLinksBringingNothing(const TreeNodes& tree, const NodeGraph& graph, std::size_t index,
                                const TreeInputReader::OutputValues& valueOf, CookDiagnostics& diagnostics) {
  const TreeNode& node = tree.nodes[index];
  std::map<std::size_t, TfToken> broughtNothing;  // by node index, so in node-ID order
  for (const auto& [input, links] : node.links) {
    for (const NodeLink& link : links) {
      for (const OutputRef& origin : graph.LinkOrigins(link)) {
        const TreeNode& source = tree.nodes[origin.node];
        const bool brings = !source.muted && source.runnable && !valueOf(origin).IsEmpty();
        if (!brings) broughtNothing.emplace(origin.node, input);
      }
    }
  }
  for (const auto& [sourceIndex, input] : broughtNothing) {
    const TreeNode& source = tree.nodes[sourceIndex];
    diagnostics.AddNode(
        node.id, Severity::kWarning, DiagnosticCode::kNoUpstreamValue,
        input.GetString() + " gets nothing from \"" + source.id + "\"" + (source.muted ? ", which is muted" : ""),
        node.spec->GetPath().AppendProperty(input));
  }
}

// Reports each Tf error posted since mark as a USD error on the node, and clears them, so an error a node raises
// becomes its diagnostic rather than an exception that would discard the whole cook.
void ReportTfErrors(const TfErrorMark& mark, const TreeNode& node, CookDiagnostics& diagnostics) {
  for (const TfError& error : mark) {
    diagnostics.AddNode(node.id, Severity::kError, DiagnosticCode::kUsdError, error.GetCommentary());
  }
  mark.Clear();
}

}  // namespace

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

  CookResult result;
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
    ReportLinksBringingNothing(tree, graph, index, valueOf, diagnostics);
    const TreeInputReader inputs(tree, graph, index, valueOf);
    const TfErrorMark mark;
    std::visit(
        [&](const auto& role) {
          using Role = std::decay_t<decltype(role)>;
          if constexpr (std::is_same_v<Role, ValueRole>) {
            outputs[index] = role.compute(ValueInputs(node, inputs, cache, diagnostics, baseDirectory_));
          } else if constexpr (std::is_same_v<Role, TaskRole>) {
            TaskContext context(node, inputs, cache, diagnostics, baseDirectory_, outputs[index], result.stageOutputs,
                                result.viewerStages);
            role.run(context);
          }
          // Authoring and zone nodes run inside their zone's task, from step 6 of the plan.
        },
        node.registration->behavior);
    ReportTfErrors(mark, node, diagnostics);
  }
  caches_ = std::move(caches);

  result.treeDiagnostics = std::move(diagnostics.tree);
  for (auto& [nodeId, nodeDiagnostics] : diagnostics.byNode) {
    result.nodeReports[nodeId].diagnostics = std::move(nodeDiagnostics);
  }
  return result;
}

}  // namespace proscenium
