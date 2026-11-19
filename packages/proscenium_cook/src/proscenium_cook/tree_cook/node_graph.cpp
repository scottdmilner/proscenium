#include "node_graph.h"

#include <algorithm>
#include <set>

PXR_NAMESPACE_USING_DIRECTIVE

namespace proscenium {
namespace {

using Adjacency = std::vector<std::vector<std::size_t>>;

// Each node's downstream nodes, one edge per linked pair.
Adjacency Downstream(const TreeNodes& tree) {
  Adjacency downstream(tree.nodes.size());
  for (std::size_t consumer = 0; consumer < tree.nodes.size(); ++consumer) {
    for (const auto& [input, links] : tree.nodes[consumer].links) {
      for (const NodeLink& link : links) downstream[link.sourceNode].push_back(consumer);
    }
  }
  for (auto& nodes : downstream) {
    std::sort(nodes.begin(), nodes.end());
    nodes.erase(std::unique(nodes.begin(), nodes.end()), nodes.end());
  }
  return downstream;
}

// Whether a path of links leads from node back to itself.
bool OnCycle(std::size_t node, const Adjacency& downstream) {
  std::vector<bool> seen(downstream.size(), false);
  std::vector<std::size_t> pending(downstream[node].begin(), downstream[node].end());
  while (!pending.empty()) {
    const std::size_t next = pending.back();
    pending.pop_back();
    if (next == node) return true;
    if (seen[next]) continue;
    seen[next] = true;
    pending.insert(pending.end(), downstream[next].begin(), downstream[next].end());
  }
  return false;
}

}  // namespace

NodeGraph::NodeGraph(TreeNodes& tree, CookDiagnostics& diagnostics) : tree_(tree) {
  const Adjacency downstream = Downstream(tree);
  const std::size_t count = tree.nodes.size();
  std::vector<bool> cyclic(count, false);
  for (std::size_t node = 0; node < count; ++node) {
    if (!OnCycle(node, downstream)) continue;
    cyclic[node] = true;
    diagnostics.AddNode(tree.nodes[node].id, Severity::kError, DiagnosticCode::kCycle,
                        "The node is on a cycle of links, so it can't be ordered", tree.nodes[node].spec->GetPath());
  }
  // Kahn's algorithm over the nodes off every cycle; nodes are in node-ID order, so the lowest index is ready first.
  std::vector<std::size_t> upstreamCount(count, 0);
  for (std::size_t node = 0; node < count; ++node) {
    if (cyclic[node]) continue;
    for (const std::size_t consumer : downstream[node]) ++upstreamCount[consumer];
  }
  std::set<std::size_t> ready;
  for (std::size_t node = 0; node < count; ++node) {
    if (!cyclic[node] && upstreamCount[node] == 0) ready.insert(node);
  }
  while (!ready.empty()) {
    const std::size_t node = *ready.begin();
    ready.erase(ready.begin());
    order_.push_back(node);
    for (const std::size_t consumer : downstream[node]) {
      if (!cyclic[consumer] && --upstreamCount[consumer] == 0) ready.insert(consumer);
    }
  }
  for (std::size_t node = 0; node < count; ++node) {
    TreeNode& treeNode = tree.nodes[node];
    treeNode.onCycle = cyclic[node];
    treeNode.runnable = treeNode.registration != nullptr && !cyclic[node] && !diagnostics.HasError(treeNode.id);
  }
}

std::vector<OutputRef> NodeGraph::Sources(std::size_t node, const TfToken& input) const {
  std::vector<OutputRef> sources;
  const auto links = tree_.nodes[node].links.find(input);
  if (links == tree_.nodes[node].links.end()) return sources;
  // Traced in connection order: pending holds what's left, last first.
  std::vector<OutputRef> pending;
  for (auto link = links->second.rbegin(); link != links->second.rend(); ++link) {
    pending.push_back({link->sourceNode, link->sourceAttribute});
  }
  while (!pending.empty()) {
    const OutputRef ref = pending.back();
    pending.pop_back();
    const TreeNode& source = tree_.nodes[ref.node];
    if (source.onCycle || source.definition == nullptr) continue;
    // A muted node passes its pass-through input on even when an error keeps it from running.
    if (!source.muted) {
      if (source.runnable) sources.push_back(ref);
      continue;
    }
    const AttributeDefinition* output = source.definition->FindAttribute(ref.attributeName);
    if (output == nullptr || output->mutePassThrough.IsEmpty()) continue;
    const auto through = source.links.find(output->mutePassThrough);
    if (through == source.links.end()) continue;
    for (auto link = through->second.rbegin(); link != through->second.rend(); ++link) {
      pending.push_back({link->sourceNode, link->sourceAttribute});
    }
  }
  return sources;
}

}  // namespace proscenium
