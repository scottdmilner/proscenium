#include "tree_cook.h"

#include <pxr/base/tf/errorMark.h>
#include <pxr/base/tf/fileUtils.h>
#include <pxr/base/tf/pathUtils.h>
#include <pxr/base/tf/stringUtils.h>
#include <pxr/usd/sdf/layer.h>

#if defined(__APPLE__)
#include <unistd.h>
#endif

#include <map>
#include <optional>
#include <stdexcept>
#include <utility>
#include <variant>

#include "node_graph.h"
#include "node_ids.h"
#include "task_graph.h"
#include "tree_reading.h"
#include "zone_chains.h"

PXR_NAMESPACE_USING_DIRECTIVE

namespace proscenium {
namespace {

using Caches = std::map<std::pair<std::string, TfToken>, NodeCache>;

// Whether the file system holding directory, which exists, ignores case: macOS's and Windows' defaults do.
bool IgnoresCase(const std::string& directory) {
#if defined(_WIN32)
  static_cast<void>(directory);
  return true;
#elif defined(__APPLE__)
  return pathconf(directory.c_str(), _PC_CASE_SENSITIVE) == 0;
#else
  static_cast<void>(directory);
  return false;
#endif
}

// The key zones' files compare by, the same for each spelling of one file. A file system path's deepest existing
// directory is resolved through its symlinks, and on a file system that ignores case the path is folded to lowercase,
// so //Shared.usda and //shared.usda are one file on macOS's and Windows' defaults. The folding is ASCII only, so two
// spellings of one file that differ in a non-ASCII letter's case, or in Unicode normalization, still compare apart. Any
// other resolver's identifier compares as it is.
std::string FileKey(const std::string& identifier) {
  if (TfIsRelativePath(identifier)) return identifier;
  std::string directory = TfNormPath(TfGetPathName(identifier));
  while (!TfIsDir(directory, /*resolveSymlinks=*/true)) {
    const std::string parent = TfNormPath(TfGetPathName(directory));
    if (parent == directory) return identifier;
    directory = parent;
  }
  if (!TfStringStartsWith(identifier, directory)) return identifier;
  const std::string key = TfNormPath(TfRealPath(directory)) + identifier.substr(directory.size());
  return IgnoresCase(directory) ? TfStringToLowerAscii(key) : key;
}

void WarnNothingFrom(const TreeNode& node, const TfToken& input, const TreeNode& source, CookDiagnostics& diagnostics) {
  diagnostics.AddNode(
      node.id, Severity::kWarning, DiagnosticCode::kNoUpstreamValue,
      input.GetString() + " gets nothing from \"" + source.id + "\"" + (source.muted ? ", which is muted" : ""),
      node.spec->GetPath().AppendProperty(input));
}

// Reports each Tf error posted since mark as a USD error on the node, and clears them, so an error a node raises
// becomes its diagnostic rather than an exception that would discard the whole cook.
void ReportTfErrors(const TfErrorMark& mark, const TreeNode& node, CookDiagnostics& diagnostics) {
  for (const TfError& error : mark) {
    diagnostics.AddNode(node.id, Severity::kError, DiagnosticCode::kUsdError, error.GetCommentary());
  }
  mark.Clear();
}

// One cook as it runs: the tree, its graph and zones, each node's committed outputs, and what the cook returns.
class CookPass {
 public:
  CookPass(const TreeNodes& tree, const NodeGraph& graph, const std::vector<Zone>& zones,
           const std::string& baseDirectory, Caches& caches, CookDiagnostics& diagnostics, CookResult& result)
      : tree_(tree),
        graph_(graph),
        zones_(zones),
        baseDirectory_(baseDirectory),
        caches_(caches),
        diagnostics_(diagnostics),
        result_(result),
        outputs_(tree.nodes.size()),
        valueOf_([this](const OutputRef& ref) {
          const auto found = outputs_[ref.node].find(ref.attributeName);
          return found == outputs_[ref.node].end() ? VtValue() : found->second;
        }) {}

  // The value nodes, each computed once, in the node graph's order, so each value is ready before any task uses it.
  void ComputeValues() {
    for (const std::size_t index : graph_.Order()) {
      const TreeNode& node = tree_.nodes[index];
      if (!node.runnable || node.muted) continue;
      if (const auto* role = std::get_if<ValueRole>(&node.registration->behavior)) {
        Run(index, [&](const TreeInputReader& inputs) {
          outputs_[index] = role->compute(ValueInputs(node, inputs, CacheOf(index), diagnostics_, baseDirectory_));
        });
      }
    }
  }

  // Each zone's layer, made before any task runs and kept in its begin's cache, so it lasts while the begin keeps its
  // ID and type, and a stage composing it keeps composing it across cooks.
  void MakeZoneLayers() {
    for (const Zone& zone : zones_) {
      auto& layer = CacheOf(zone.begin).Get<SdfLayerRefPtr>("layer");
      if (!layer) layer = SdfLayer::CreateAnonymous(PrimNameFromNodeId(tree_.nodes[zone.begin].id));
      zoneLayers_.emplace_back(layer);
    }
  }

  // Each zone's file, from its begin, and an error on each begin whose file another zone's begin names too. A problem
  // with a begin's file is its error, which stops its zone.
  void CheckZoneFiles() {
    struct BeginFile {
      std::size_t begin;
      ZoneFile file;
    };
    std::map<std::string, std::vector<BeginFile>> beginsByFile;  // by FileKey
    for (const Zone& zone : zones_) {
      const TreeNode& begin = tree_.nodes[zone.begin];
      const auto* role = std::get_if<ZoneRole>(&begin.registration->behavior);
      if (!begin.runnable || begin.muted || role == nullptr || role->file == nullptr) continue;
      ZoneFile file;
      Run(zone.begin, [&](const TreeInputReader& inputs) {
        file = role->file(NodeContext(begin, inputs, CacheOf(zone.begin), diagnostics_, baseDirectory_));
      });
      if (!file.identifier.empty()) beginsByFile[FileKey(file.identifier)].push_back({zone.begin, file});
    }
    for (const auto& [key, begins] : beginsByFile) {
      if (begins.size() < 2) continue;
      for (const BeginFile& entry : begins) {
        std::vector<std::string> others;
        for (const BeginFile& other : begins) {
          if (other.begin != entry.begin) others.push_back("\"" + tree_.nodes[other.begin].id + "\"");
        }
        const TreeNode& begin = tree_.nodes[entry.begin];
        diagnostics_.AddNode(begin.id, Severity::kError, DiagnosticCode::kSharedFile,
                             "\"" + entry.file.identifier + "\" is also the file of " + TfStringJoin(others, ", ") +
                                 "; each zone saves to a file of its own",
                             begin.spec->GetPath().AppendProperty(entry.file.attributeName));
      }
    }
  }

  void RunTask(const Task& task) {
    if (task.zone) {
      CookZone(zones_[*task.zone], zoneLayers_[*task.zone]);
      return;
    }
    const std::size_t index = task.nodes.front();
    const TreeNode& node = tree_.nodes[index];
    if (!node.runnable || node.muted) return;
    Run(index, [&](const TreeInputReader& inputs) {
      TaskContext context(node, inputs, CacheOf(index), diagnostics_, baseDirectory_, outputs_[index],
                          result_.stageOutputs, result_.viewerStages);
      std::get<TaskRole>(node.registration->behavior).run(context);
    });
  }

 private:
  NodeCache& CacheOf(std::size_t index) {
    const TreeNode& node = tree_.nodes[index];
    return caches_[{node.id, node.typeName}];
  }

  // Runs a node: warns of its links that bring nothing, then calls run with its inputs, reporting the Tf errors it
  // raises as its own.
  template <class Body>
  void Run(std::size_t index, const Body& run) {
    ReportLinksBringingNothing(index);
    const TreeInputReader inputs(tree_, graph_, index, valueOf_);
    const TfErrorMark mark;
    run(inputs);
    ReportTfErrors(mark, tree_.nodes[index], diagnostics_);
  }

  // Warns once for each node whose output one of this node's links traces back to but that brings nothing: it failed,
  // can't run, or is muted with nothing to pass through (docs/plans/cook-module.md "Order and results"). The warning
  // names that node, whose own diagnostic says why, and the first input it fails to reach. The node still runs,
  // without those values. An Editable Layer link is its chain's, which its zone's task follows instead.
  void ReportLinksBringingNothing(std::size_t index) {
    const TreeNode& node = tree_.nodes[index];
    std::map<std::size_t, TfToken> broughtNothing;  // by node index, so in node-ID order
    for (const auto& [input, links] : node.links) {
      const AttributeDefinition* attribute = node.definition->FindAttribute(input);
      if (attribute != nullptr && attribute->kind == SocketKind::kEditableLayer) continue;
      for (const NodeLink& link : links) {
        for (const OutputRef& origin : graph_.LinkOrigins(link)) {
          const TreeNode& source = tree_.nodes[origin.node];
          const bool brings = !source.muted && source.runnable && !valueOf_(origin).IsEmpty();
          if (!brings) broughtNothing.emplace(origin.node, input);
        }
      }
    }
    for (const auto& [sourceIndex, input] : broughtNothing) {
      WarnNothingFrom(node, input, tree_.nodes[sourceIndex], diagnostics_);
    }
  }

  // Cooks a zone's chain into a scratch layer, from its begin, and moves the result into the zone's layer with
  // TransferContent, so stages composing the layer see one change (docs/phase3/node-tree.md "Cooking the layers"). A
  // muted chain node passes its Editable Layer through. The chain stops at its first node that can't run or reports an
  // error, and then the zone gives no layer out: the nodes after it don't run, and its end warns, naming that node.
  void CookZone(const Zone& zone, const SdfLayerHandle& layer) {
    const TreeNode& begin = tree_.nodes[zone.begin];
    std::optional<std::size_t> stoppedAt;
    if (!begin.runnable || begin.muted || diagnostics_.HasError(begin.id)) stoppedAt = zone.begin;
    const SdfLayerRefPtr scratch = SdfLayer::CreateAnonymous();
    for (const std::size_t index : zone.chain) {
      if (stoppedAt) break;
      const TreeNode& node = tree_.nodes[index];
      if (node.muted) continue;
      const auto* role = node.runnable ? std::get_if<AuthoringRole>(&node.registration->behavior) : nullptr;
      if (role != nullptr) {
        Run(index, [&](const TreeInputReader& inputs) {
          AuthoringContext context(node, inputs, CacheOf(index), diagnostics_, baseDirectory_);
          role->author(context);
        });
      }
      if (!node.runnable || diagnostics_.HasError(node.id)) stoppedAt = index;
    }
    if (!zone.reachesEnd || !zone.end) return;  // its end has its broken-chain error
    const std::size_t endIndex = *zone.end;
    const TreeNode& end = tree_.nodes[endIndex];
    if (!end.runnable || end.muted) return;
    if (stoppedAt) {
      WarnNothingFrom(end, end.definition->EditableLayer(AttributeRole::kInput)->attributeName, tree_.nodes[*stoppedAt],
                      diagnostics_);
      return;
    }
    const auto& role = std::get<ZoneRole>(end.registration->behavior);
    Run(endIndex, [&](const TreeInputReader&) {
      layer->TransferContent(scratch);
      if (role.outputs != nullptr) outputs_[endIndex] = role.outputs(layer);
    });
  }

  const TreeNodes& tree_;
  const NodeGraph& graph_;
  const std::vector<Zone>& zones_;
  const std::string& baseDirectory_;
  Caches& caches_;
  CookDiagnostics& diagnostics_;
  CookResult& result_;
  std::vector<ValueOutputs> outputs_;  // each node's committed outputs this cook, by node index
  TreeInputReader::OutputValues valueOf_;
  std::vector<SdfLayerHandle> zoneLayers_;  // by zone index, from MakeZoneLayers
};

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
  const std::vector<Zone> zones = FindZones(tree, diagnostics);
  const std::vector<Task> tasks = OrderTasks(tree, graph, zones, diagnostics);

  // Every node of the tree keeps its cache, whether or not it runs this cook; a node gone from the tree drops its.
  Caches caches;
  for (const TreeNode& node : tree.nodes) {
    const std::pair<std::string, TfToken> key{node.id, node.typeName};
    caches[key] = std::move(caches_[key]);
  }

  // The scheduler: the value nodes first, then every task, serially, upstream first, so each reads its upstream
  // tasks' committed results. A muted node doesn't run: its consumers read through it (NodeGraph::Sources).
  CookResult result;
  CookPass pass(tree, graph, zones, baseDirectory_, caches, diagnostics, result);
  pass.ComputeValues();
  pass.MakeZoneLayers();
  pass.CheckZoneFiles();
  for (const Task& task : tasks) pass.RunTask(task);
  caches_ = std::move(caches);

  result.treeDiagnostics = std::move(diagnostics.tree);
  for (auto& [nodeId, nodeDiagnostics] : diagnostics.byNode) {
    result.nodeReports[nodeId].diagnostics = std::move(nodeDiagnostics);
  }
  return result;
}

}  // namespace proscenium
