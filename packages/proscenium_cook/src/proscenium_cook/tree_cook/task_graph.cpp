#include "task_graph.h"

#include <algorithm>
#include <optional>
#include <utility>
#include <variant>

PXR_NAMESPACE_USING_DIRECTIVE

namespace proscenium {

std::vector<Task> OrderTasks(const TreeNodes& tree, const NodeGraph& graph, const std::vector<Zone>& zones,
                             CookDiagnostics& diagnostics) {
  std::vector<Task> tasks;
  for (std::size_t index = 0; index < zones.size(); ++index) {
    const Zone& zone = zones[index];
    Task task{{zone.begin}, index};
    task.nodes.insert(task.nodes.end(), zone.chain.begin(), zone.chain.end());
    if (zone.reachesEnd && zone.end) task.nodes.push_back(*zone.end);
    tasks.push_back(std::move(task));
  }
  for (const std::size_t node : graph.Order()) {
    const NodeRegistration* registration = tree.nodes[node].registration;
    if (registration != nullptr && std::holds_alternative<TaskRole>(registration->behavior)) {
      tasks.push_back({{node}, std::nullopt});
    }
  }
  // By first node, so a task's index is in node-ID order, which breaks ties in the order below.
  std::sort(tasks.begin(), tasks.end(), [](const Task& a, const Task& b) { return a.nodes.front() < b.nodes.front(); });
  std::vector<std::optional<std::size_t>> taskOf(tree.nodes.size());
  for (std::size_t task = 0; task < tasks.size(); ++task) {
    for (const std::size_t node : tasks[task].nodes) taskOf[node] = task;
  }

  // The ordering edges: each Layer or File link from a node of one task into a node of another.
  std::vector<std::vector<std::size_t>> downstream(tasks.size());
  for (std::size_t task = 0; task < tasks.size(); ++task) {
    for (const std::size_t node : tasks[task].nodes) {
      for (const auto& [input, links] : tree.nodes[node].links) {
        // An input the definition lacks has its error, and brings nothing.
        const AttributeDefinition* attribute = tree.nodes[node].definition->FindAttribute(input);
        if (attribute == nullptr || (attribute->kind != SocketKind::kLayer && attribute->kind != SocketKind::kFile)) {
          continue;
        }
        for (const NodeLink& link : links) {
          for (const OutputRef& origin : graph.LinkOrigins(link)) {
            const std::optional<std::size_t> upstream = taskOf[origin.node];
            if (upstream && *upstream != task) downstream[*upstream].push_back(task);
          }
        }
      }
    }
  }

  const std::vector<std::size_t> order = TopologicalOrder(downstream);
  std::vector<bool> isOrdered(tasks.size(), false);
  for (const std::size_t task : order) isOrdered[task] = true;
  for (std::size_t task = 0; task < tasks.size(); ++task) {
    if (isOrdered[task]) continue;
    for (const std::size_t node : tasks[task].nodes) {
      diagnostics.AddNode(tree.nodes[node].id, Severity::kError, DiagnosticCode::kCycle,
                          "The node's task waits on itself through other tasks' links, so it can't be ordered",
                          tree.nodes[node].spec->GetPath());
    }
  }
  std::vector<Task> ordered;
  ordered.reserve(order.size());
  for (const std::size_t task : order) ordered.push_back(std::move(tasks[task]));
  return ordered;
}

}  // namespace proscenium
