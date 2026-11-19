#include "zone_chains.h"

#include <pxr/base/tf/stringUtils.h>
#include <pxr/base/tf/token.h>
#include <pxr/usd/sdf/path.h>
#include <pxr/usd/sdf/relationshipSpec.h>

#include <string>
#include <unordered_map>

PXR_NAMESPACE_USING_DIRECTIVE

namespace proscenium {
namespace {

using NodeLists = std::vector<std::vector<std::size_t>>;

// Which end of a zone the node is; kNone for a node of unknown type, or one on a cycle, which takes no part.
ZoneEdge EdgeOf(const TreeNode& node) {
  return node.definition != nullptr && !node.onCycle ? node.definition->zone : ZoneEdge::kNone;
}

const AttributeDefinition* EditableLayerOf(const TreeNode& node, AttributeRole role) {
  return node.definition != nullptr ? node.definition->EditableLayer(role) : nullptr;
}

std::string Quoted(const TreeNode& node) { return "\"" + node.id + "\""; }

// The path of the node's Editable Layer input or output, which a chain's diagnostic concerns; its prim's for none.
SdfPath EditableLayerPath(const TreeNode& node, AttributeRole role) {
  const AttributeDefinition* attribute = EditableLayerOf(node, role);
  return attribute != nullptr ? node.spec->GetPath().AppendProperty(attribute->attributeName) : node.spec->GetPath();
}

// Each node's next nodes on a chain: those whose Editable Layer input links to its Editable Layer output, in node-ID
// order. A node has at most one of each (node_definitions.h), and an input at most one link (too-many-links).
NodeLists ChainConsumers(const TreeNodes& tree) {
  NodeLists consumers(tree.nodes.size());
  for (std::size_t consumer = 0; consumer < tree.nodes.size(); ++consumer) {
    const AttributeDefinition* input = EditableLayerOf(tree.nodes[consumer], AttributeRole::kInput);
    if (input == nullptr) continue;
    const auto links = tree.nodes[consumer].links.find(input->attributeName);
    if (links == tree.nodes[consumer].links.end()) continue;
    for (const NodeLink& link : links->second) consumers[link.sourceNode].push_back(consumer);
  }
  return consumers;
}

class ZoneFinder {
 public:
  ZoneFinder(TreeNodes& tree, CookDiagnostics& diagnostics)
      : tree_(tree), diagnostics_(diagnostics), consumers_(ChainConsumers(tree)), mismatched_(tree.nodes.size()) {}

  std::vector<Zone> Find() {
    const std::vector<std::optional<std::size_t>> endOf = Pair();
    std::vector<bool> inChain(tree_.nodes.size(), false);
    std::vector<Zone> zones;
    for (std::size_t begin = 0; begin < tree_.nodes.size(); ++begin) {
      if (EdgeOf(tree_.nodes[begin]) != ZoneEdge::kBegin) continue;
      zones.push_back(Walk(begin, endOf[begin]));
      for (const std::size_t node : zones.back().chain) inChain[node] = true;
    }
    for (const Zone& zone : zones) {
      if (zone.end && !zone.reachesEnd) ReportBroken(zone, *zone.end);
    }
    ReportNoChain(inChain);
    // A node given an error here can't run, as one the checks gave an error can't.
    for (TreeNode& node : tree_.nodes) {
      if (node.runnable && diagnostics_.HasError(node.id)) node.runnable = false;
    }
    return zones;
  }

 private:
  void Error(const TreeNode& node, DiagnosticCode code, std::string message, SdfPath sourcePath) {
    diagnostics_.AddNode(node.id, Severity::kError, code, std::move(message), std::move(sourcePath));
  }

  // Each begin's end: the one node its zone:end names, of its partner's type, when no other begin names it too. Reports
  // each begin and end that doesn't pair.
  std::vector<std::optional<std::size_t>> Pair() {
    const std::size_t count = tree_.nodes.size();
    std::unordered_map<SdfPath, std::size_t, SdfPath::Hash> indexByPrim;
    for (std::size_t i = 0; i < count; ++i) indexByPrim.emplace(tree_.nodes[i].spec->GetPath(), i);
    std::vector<std::optional<std::size_t>> named(count);
    NodeLists namedBy(count);
    // The begin, on a cycle, that names each end; its end isn't unpaired, but gets nothing from it.
    std::vector<std::optional<std::size_t>> cyclicBeginOf(count);
    for (std::size_t begin = 0; begin < count; ++begin) {
      const TreeNode& node = tree_.nodes[begin];
      const bool isBegin = node.definition != nullptr && node.definition->zone == ZoneEdge::kBegin;
      if (!isBegin) continue;
      const SdfRelationshipSpecHandle zoneEnd = node.spec->GetRelationships().get(TfToken("zone:end"));
      SdfPathVector targets;
      if (zoneEnd) zoneEnd->GetTargetPathList().ApplyEditsToList(&targets);
      const auto found = targets.size() == 1 ? indexByPrim.find(targets.front()) : indexByPrim.end();
      const bool namesEnd = found != indexByPrim.end() && EdgeOf(tree_.nodes[found->second]) == ZoneEdge::kEnd &&
                            tree_.nodes[found->second].typeName == node.definition->zonePartner;
      if (node.onCycle) {
        if (namesEnd) cyclicBeginOf[found->second] = begin;
      } else if (namesEnd) {
        named[begin] = found->second;
        namedBy[found->second].push_back(begin);
      } else {
        Error(node, DiagnosticCode::kUnpairedZone,
              "zone:end must name one " + node.definition->zonePartner.GetString() + " node",
              zoneEnd ? zoneEnd->GetPath() : node.spec->GetPath());
      }
    }
    std::vector<std::optional<std::size_t>> endOf(count);
    for (std::size_t begin = 0; begin < count; ++begin) {
      const std::optional<std::size_t> end = named[begin];
      if (!end) continue;
      if (namedBy[*end].size() == 1) {
        endOf[begin] = end;
      } else {
        const TreeNode& node = tree_.nodes[begin];
        Error(node, DiagnosticCode::kUnpairedZone,
              "zone:end names " + Quoted(tree_.nodes[*end]) + ", which another begin's zone:end names too",
              node.spec->GetPath().AppendProperty(TfToken("zone:end")));
      }
    }
    for (std::size_t end = 0; end < count; ++end) {
      const TreeNode& node = tree_.nodes[end];
      if (EdgeOf(node) != ZoneEdge::kEnd || namedBy[end].size() == 1) continue;
      if (const std::optional<std::size_t> cyclicBegin = cyclicBeginOf[end]; cyclicBegin && namedBy[end].empty()) {
        diagnostics_.AddNode(
            node.id, Severity::kWarning, DiagnosticCode::kNoUpstreamValue,
            "its zone gets nothing from its begin, " + Quoted(tree_.nodes[*cyclicBegin]) + ", which is on a cycle",
            EditableLayerPath(node, AttributeRole::kInput));
        continue;
      }
      Error(
          node, DiagnosticCode::kUnpairedZone,
          namedBy[end].empty() ? "no begin's zone:end names this end" : "more than one begin's zone:end names this end",
          node.spec->GetPath());
    }
    pairedEnds_.assign(count, false);
    for (const auto& end : endOf) {
      if (end) pairedEnds_[*end] = true;
    }
    return endOf;
  }

  // The begin's chain, followed forward until it reaches an end, branches, or stops.
  Zone Walk(std::size_t begin, std::optional<std::size_t> end) {
    Zone zone{begin, end, {}, false};
    std::size_t current = begin;
    while (true) {
      const std::vector<std::size_t>& next = consumers_[current];
      if (next.size() > 1) {
        Error(tree_.nodes[current], DiagnosticCode::kChainBranch,
              "its Editable Layer links to " + TfStringify(next.size()) +
                  " inputs; it links to one, so that every edit reaches its zone's end",
              EditableLayerPath(tree_.nodes[current], AttributeRole::kOutput));
        break;
      }
      if (next.empty() || tree_.nodes[next.front()].onCycle) break;
      const std::size_t node = next.front();
      if (EdgeOf(tree_.nodes[node]) == ZoneEdge::kEnd) {
        if (node == end) {
          zone.reachesEnd = true;
        } else if (pairedEnds_[node]) {
          mismatched_[node] = true;
          Error(tree_.nodes[node], DiagnosticCode::kMismatchedZone,
                "the chain from " + Quoted(tree_.nodes[begin]) + " reaches this end, which isn't its zone's",
                EditableLayerPath(tree_.nodes[node], AttributeRole::kInput));
        }
        break;
      }
      zone.chain.push_back(node);
      current = node;
    }
    return zone;
  }

  // An end its begin's chain doesn't reach, and the chain's nodes, whose edits never reach it. An end that another
  // begin's chain reaches has its mismatched-zone error instead.
  void ReportBroken(const Zone& zone, std::size_t endIndex) {
    const TreeNode& begin = tree_.nodes[zone.begin];
    const TreeNode& end = tree_.nodes[endIndex];
    if (!mismatched_[endIndex]) {
      const std::string stop = zone.chain.empty() ? "" : ", stopping after " + Quoted(tree_.nodes[zone.chain.back()]);
      Error(end, DiagnosticCode::kBrokenChain, "the chain from " + Quoted(begin) + " doesn't reach this end" + stop,
            EditableLayerPath(end, AttributeRole::kInput));
    }
    for (const std::size_t node : zone.chain) {
      diagnostics_.AddNode(tree_.nodes[node].id, Severity::kWarning, DiagnosticCode::kUnreachedZoneEnd,
                           "its edits never reach its zone's end, " + Quoted(end), tree_.nodes[node].spec->GetPath());
    }
  }

  // Each authoring node on no chain. Only the first of a run of them reports it: the nodes after it pass nothing on. A
  // node after a branch reports nothing either, since the node that branches has the error.
  void ReportNoChain(const std::vector<bool>& inChain) {
    std::vector<bool> chainless(tree_.nodes.size(), false);
    for (std::size_t i = 0; i < tree_.nodes.size(); ++i) {
      const TreeNode& node = tree_.nodes[i];
      chainless[i] = EdgeOf(node) == ZoneEdge::kNone && node.definition != nullptr && !node.onCycle &&
                     EditableLayerOf(node, AttributeRole::kInput) != nullptr && !inChain[i];
    }
    for (std::size_t i = 0; i < tree_.nodes.size(); ++i) {
      if (!chainless[i]) continue;
      const TreeNode& node = tree_.nodes[i];
      const auto links = node.links.find(EditableLayerOf(node, AttributeRole::kInput)->attributeName);
      if (links != node.links.end()) {
        const std::size_t source = links->second.front().sourceNode;
        if (chainless[source] || consumers_[source].size() > 1) continue;
      }
      Error(node, DiagnosticCode::kNoChain, "its Editable Layer doesn't trace back to a zone's begin",
            EditableLayerPath(node, AttributeRole::kInput));
    }
  }

  TreeNodes& tree_;
  CookDiagnostics& diagnostics_;
  NodeLists consumers_;
  std::vector<bool> pairedEnds_;  // by node index: an end that pairs with one begin
  std::vector<bool> mismatched_;  // by node index: an end another begin's chain reaches
};

}  // namespace

std::vector<Zone> FindZones(TreeNodes& tree, CookDiagnostics& diagnostics) {
  return ZoneFinder(tree, diagnostics).Find();
}

}  // namespace proscenium
