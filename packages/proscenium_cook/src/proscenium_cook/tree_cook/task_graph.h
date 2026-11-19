// The task graph: the cook's units of work, built from the node graph (docs/plans/cook-module.md "Two graphs"). A zone
// is one task, its begin, its chain, and its end, run in chain order; Layer from File, Stage Output, and Viewer are
// each a task of their own. A task waits for another only when a Layer or File link brings that task's result into it.
// A chain node's value output isn't an ordering edge, since it's computed from the node's own inputs, so an acyclic
// tree gives an acyclic task graph ("Edges between tasks").
#pragma once

#include <cstddef>
#include <optional>
#include <vector>

#include "cook_diagnostics.h"
#include "node_graph.h"
#include "tree_reading.h"
#include "zone_chains.h"

namespace proscenium {

struct Task {
  // By node index: a zone's begin, its chain, and its end when the chain reaches it; or one task node.
  std::vector<std::size_t> nodes;
  std::optional<std::size_t> zone;  // its index in the zones it's built from; none for a task node's task
};

// Every zone's task, and every task node's off a cycle, upstream first, ties broken by the node ID of each task's first
// node. A zone whose chain doesn't reach its end leaves the end out, since the end gives nothing out: its task then
// feeds no other. A task on a cycle of tasks is left out, and each of its nodes gets an error (cycle). No node type yet
// can make one: that needs a chain node with a Layer or File output.
std::vector<Task> OrderTasks(const TreeNodes& tree, const NodeGraph& graph, const std::vector<Zone>& zones,
                             CookDiagnostics& diagnostics);

}  // namespace proscenium
