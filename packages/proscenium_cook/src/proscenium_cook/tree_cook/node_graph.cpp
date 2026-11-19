#include "node_graph.h"

#include <algorithm>
#include <set>
#include <utility>

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

std::vector<std::size_t> TopologicalOrder(const std::vector<std::vector<std::size_t>>& downstream,
                                          const std::vector<bool>& skip) {
  const std::size_t count = downstream.size();
  const auto skipped = [&](std::size_t vertex) { return !skip.empty() && skip[vertex]; };
  std::vector<std::size_t> upstreamCount(count, 0);
  for (std::size_t vertex = 0; vertex < count; ++vertex) {
    if (skipped(vertex)) continue;
    for (const std::size_t consumer : downstream[vertex]) ++upstreamCount[consumer];
  }
  std::set<std::size_t> ready;
  for (std::size_t vertex = 0; vertex < count; ++vertex) {
    if (!skipped(vertex) && upstreamCount[vertex] == 0) ready.insert(vertex);
  }
  std::vector<std::size_t> order;
  while (!ready.empty()) {
    const std::size_t vertex = *ready.begin();
    ready.erase(ready.begin());
    order.push_back(vertex);
    for (const std::size_t consumer : downstream[vertex]) {
      if (!skipped(consumer) && --upstreamCount[consumer] == 0) ready.insert(consumer);
    }
  }
  return order;
}

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
  order_ = TopologicalOrder(downstream, cyclic);
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
  for (const NodeLink& link : links->second) {
    for (OutputRef& source : LinkSources(link)) sources.push_back(std::move(source));
  }
  return sources;
}

std::vector<OutputRef> NodeGraph::LinkSources(const NodeLink& link) const {
  std::vector<OutputRef> sources = LinkOrigins(link);
  sources.erase(std::remove_if(sources.begin(), sources.end(),
                               [&](const OutputRef& origin) {
                                 const TreeNode& source = tree_.nodes[origin.node];
                                 return source.muted || !source.runnable;
                               }),
                sources.end());
  return sources;
}

std::vector<OutputRef> NodeGraph::LinkOrigins(const NodeLink& link) const {
  std::vector<OutputRef> origins;
  // Traced depth first, in connection order: pending holds what's left, last first. A node on a cycle ends the
  // tracing, so it ends.
  std::vector<OutputRef> pending{{link.sourceNode, link.sourceAttribute}};
  while (!pending.empty()) {
    const OutputRef ref = pending.back();
    pending.pop_back();
    const TreeNode& source = tree_.nodes[ref.node];
    // A muted node passes its pass-through input on even when an error keeps it from running.
    const AttributeDefinition* output = source.muted && !source.onCycle && source.definition
                                            ? source.definition->FindAttribute(ref.attributeName)
                                            : nullptr;
    const auto through =
        output && !output->mutePassThrough.IsEmpty() ? source.links.find(output->mutePassThrough) : source.links.end();
    if (through == source.links.end()) {
      origins.push_back(ref);
      continue;
    }
    for (auto next = through->second.rbegin(); next != through->second.rend(); ++next) {
      pending.push_back({next->sourceNode, next->sourceAttribute});
    }
  }
  return origins;
}

}  // namespace proscenium
