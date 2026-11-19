// The node graph: one vertex per node and one edge per link (docs/plans/cook-module.md "Two graphs"). It must be
// acyclic; each node on a cycle gets an error and takes no part in the cook. Its topological order runs upstream
// first, with ties broken by node ID, so the order, and so the result, is the same on every cook.
#pragma once

#include <pxr/base/tf/token.h>
#include <pxr/pxr.h>

#include <cstddef>
#include <vector>

#include "cook_diagnostics.h"
#include "tree_reading.h"

namespace proscenium {

// A graph's vertices in topological order, upstream first, by Kahn's algorithm: of the vertices ready, the lowest index
// goes first, so vertices indexed in node-ID order break ties by node ID. downstream holds each vertex's downstream
// vertices. A vertex skip marks, and its edges, take no part; skip is empty when none do. A vertex on a cycle that
// isn't skipped, and any vertex downstream of one, is left out.
std::vector<std::size_t> TopologicalOrder(const std::vector<std::vector<std::size_t>>& downstream,
                                          const std::vector<bool>& skip = {});

// One node's output, by node index.
struct OutputRef {
  std::size_t node;
  PXR_NS::TfToken attributeName;
};

class NodeGraph {
 public:
  // Builds the graph over tree's nodes, adding an error to each node on a cycle, and marks which nodes can run: those
  // of a known type, off every cycle, with no error from the checks.
  NodeGraph(TreeNodes& tree, CookDiagnostics& diagnostics);

  // The nodes off every cycle, upstream first, ties broken by node ID.
  [[nodiscard]] const std::vector<std::size_t>& Order() const { return order_; }

  // The outputs an input's links bring, in connection order, each traced back through muted nodes: a muted node's
  // output brings what its definition's pass-through input brings, even when an error keeps the node from running,
  // and nothing when it has none. A link from an unmuted node that can't run, or from a node on a cycle, brings
  // nothing, so it isn't listed.
  [[nodiscard]] std::vector<OutputRef> Sources(std::size_t node, const PXR_NS::TfToken& input) const;

  // The outputs one link brings, traced as Sources traces each of an input's links.
  [[nodiscard]] std::vector<OutputRef> LinkSources(const NodeLink& link) const;

  // Where one link's tracing ends: each output of an unmuted node, whether or not it can run, and each output of a
  // muted node that passes nothing through, or of a node of unknown type or on a cycle. A link's sources are those of
  // its origins that can run.
  [[nodiscard]] std::vector<OutputRef> LinkOrigins(const NodeLink& link) const;

 private:
  const TreeNodes& tree_;
  std::vector<std::size_t> order_;
};

}  // namespace proscenium
