#include "tree_cook.h"

#include <pxr/base/tf/errorMark.h>
#include <pxr/base/tf/fileUtils.h>
#include <pxr/base/tf/pathUtils.h>
#include <pxr/base/tf/stringUtils.h>
#include <pxr/base/vt/dictionary.h>
#include <pxr/usd/sdf/layer.h>

#if defined(__APPLE__)
#include <unistd.h>
#endif

#include <map>
#include <optional>
#include <stdexcept>
#include <utility>
#include <variant>

#include "layer_copies.h"
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

// The key files compare by, the same for each spelling of one file. A relative identifier, such as a Layer from File's
// ./own.usda or own.usda, is made absolute against the working directory, where the resolver finds it and where a
// zone's file of that spelling is saved. A file system path's deepest existing directory is then resolved through its
// symlinks, and on a file system that ignores case the path is folded to lowercase, so //Shared.usda and //shared.usda
// are one file on macOS's and Windows' defaults. The folding is ASCII only, so two spellings of one file that differ in
// a non-ASCII letter's case, or in Unicode normalization, still compare apart.
std::string FileKey(const std::string& written) {
  std::string identifier = TfIsRelativePath(written) ? TfAbsPath(written) : written;
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
    for (std::size_t index = 0; index < zones_.size(); ++index) {
      const std::size_t begin = zones_[index].begin;
      auto& layer = CacheOf(begin).Get<SdfLayerRefPtr>("layer");
      if (!layer) layer = SdfLayer::CreateAnonymous(PrimNameFromNodeId(tree_.nodes[begin].id));
      zoneLayers_.emplace_back(layer);
      zoneOfLayer_.emplace(layer->GetIdentifier(), index);
    }
  }

  // The files zones save to, from their begins, and the files tasks read, such as a Layer from File's, each before any
  // task runs. A file that two zones save to, or that a zone saves to and a task reads, is an error on each of those
  // nodes: a zone's file is its output alone (docs/phase3/node-tree.md "Writing"). So a zone whose Template is its own
  // file is an error, rather than a cycle through the file. The error stops a zone, and a task that reads the file
  // doesn't run.
  void CheckFiles() {
    // One node's use of a file: a begin saving its zone's layer there, or a task reading it.
    struct FileUse {
      std::size_t node;
      NodeFile file;
      bool saves;  // a zone's begin, rather than a task that reads the file
    };
    // Every use, grouped by FileKey, so each spelling of one file lands in one group. A node that names no file, such
    // as a begin with an empty File, has no use.
    std::map<std::string, std::vector<FileUse>> usesByFile;
    const auto add = [&](std::size_t index, const NodeFile& file, bool saves) {
      if (!file.identifier.empty()) usesByFile[FileKey(file.identifier)].push_back({index, file, saves});
    };

    // The files zones save to, from each runnable, unmuted begin's file hook. A problem the hook reports, such as a //
    // path with no base directory, is the begin's error, which stops its zone.
    for (const Zone& zone : zones_) {
      const TreeNode& begin = tree_.nodes[zone.begin];
      const auto* role = std::get_if<ZoneRole>(&begin.registration->behavior);
      if (!begin.runnable || begin.muted || role == nullptr || role->file == nullptr) continue;
      Call(zone.begin, [&](const TreeInputReader& inputs) {
        add(zone.begin, role->file(NodeContext(begin, inputs, CacheOf(zone.begin), diagnostics_, baseDirectory_)),
            true);
      });
    }

    // The files tasks read, from each runnable, unmuted task's file hook (a Layer from File's). The task's run expands
    // the same path and reports the same problems with it, so what the hook reports here is discarded, Tf errors too,
    // rather than reported twice.
    for (std::size_t index = 0; index < tree_.nodes.size(); ++index) {
      const TreeNode& node = tree_.nodes[index];
      const auto* role = node.registration != nullptr ? std::get_if<TaskRole>(&node.registration->behavior) : nullptr;
      if (!node.runnable || node.muted || role == nullptr || role->file == nullptr) continue;
      const TreeInputReader inputs(tree_, graph_, index, valueOf_);
      CookDiagnostics discarded;  // the node's run reports the same problems
      const TfErrorMark mark;
      add(index, role->file(NodeContext(node, inputs, CacheOf(index), discarded, baseDirectory_)), false);
      mark.Clear();
    }

    // Each group's conflicts. Every node in a group with a zone's begin and any other use gets an error naming the
    // others it conflicts with: a begin conflicts with every other use, and a reader only with the begins, since two
    // tasks may read one file.
    for (const auto& [key, uses] : usesByFile) {
      for (const FileUse& use : uses) {
        std::vector<std::string> savers;   // the other begins saving to this file
        std::vector<std::string> readers;  // the tasks reading it, listed only in a begin's error
        for (const FileUse& other : uses) {
          if (other.node == use.node) continue;
          if (other.saves || use.saves) (other.saves ? savers : readers).push_back(Quoted(other.node));
        }
        if (savers.empty() && readers.empty()) continue;  // a reader in a group of readers only
        // Such as: "/x/own.usda" is also the file of "A" and read by "B".
        std::vector<std::string> clauses;
        if (!savers.empty()) clauses.push_back("the file of " + TfStringJoin(savers, ", "));
        if (!readers.empty()) clauses.push_back("read by " + TfStringJoin(readers, ", "));
        const TreeNode& node = tree_.nodes[use.node];
        diagnostics_.AddNode(node.id, Severity::kError, DiagnosticCode::kSharedFile,
                             "\"" + use.file.identifier + "\" is also " + TfStringJoin(clauses, " and ") +
                                 "; a zone's file is its own, which no other node saves to or reads",
                             node.spec->GetPath().AppendProperty(use.file.attributeName));
      }
    }
  }

  void RunTask(const Task& task) {
    if (task.zone) {
      CookZone(*task.zone);
      return;
    }
    const std::size_t index = task.nodes.front();
    const TreeNode& node = tree_.nodes[index];
    if (!node.runnable || node.muted || diagnostics_.HasError(node.id)) return;
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

  [[nodiscard]] std::string Quoted(std::size_t index) const { return "\"" + tree_.nodes[index].id + "\""; }

  // Runs a node: warns of its links that bring nothing, then calls it (Call).
  template <class Body>
  void Run(std::size_t index, const Body& run) {
    ReportLinksBringingNothing(index);
    Call(index, run);
  }

  // Calls run with the node's inputs, reporting the Tf errors it raises as the node's own.
  template <class Body>
  void Call(std::size_t index, const Body& run) {
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
  // TransferContent, so stages composing the layer see one change (docs/phase3/node-tree.md "Cooking the layers"). The
  // scratch layer starts as a copy of the begin's Template, or empty. A muted chain node passes its Editable Layer
  // through. The chain stops at its first node that can't run or reports an error, and then the zone gives no layer
  // out: the nodes after it don't run, and its end warns, naming that node.
  void CookZone(std::size_t zoneIndex) {
    const Zone& zone = zones_[zoneIndex];
    const TreeNode& begin = tree_.nodes[zone.begin];
    std::optional<std::size_t> stoppedAt;
    if (!begin.runnable || begin.muted || diagnostics_.HasError(begin.id)) stoppedAt = zone.begin;
    const SdfLayerRefPtr scratch = SdfLayer::CreateAnonymous();
    WriteTable writeTable;
    if (!stoppedAt) {
      // Its links are reported here, not in CheckFiles, which runs before the tasks upstream of it have committed.
      ReportLinksBringingNothing(zone.begin);
      const std::optional<WriteTable> started = StartZone(zone.begin, scratch);
      if (started && !diagnostics_.HasError(begin.id)) {
        writeTable = *started;
      } else {
        stoppedAt = zone.begin;
      }
    }
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
    const SdfLayerHandle& layer = zoneLayers_[zoneIndex];
    Run(endIndex, [&](const TreeInputReader&) {
      layer->TransferContent(scratch);
      if (role.outputs != nullptr) outputs_[endIndex] = role.outputs(layer);
    });
    // The table describes the layer as it was last committed, so it's kept beside it.
    auto& kept = CacheOf(zone.begin).Get<WriteTable>("writeTable");
    kept = std::move(writeTable);
    ReportAnchoredPaths(begin, kept);
  }

  // Fills a zone's empty scratch layer, before its chain runs, with a copy of the layer its begin starts from (a New
  // Layer Zone's Template), and returns the write table for the paths in that copy. A zone whose begin starts from
  // nothing stays empty, with an empty table. Returns nothing when the begin's start brings nothing, such as a
  // Template from a Layer from File whose file is missing, which stops the zone: an empty layer standing in for the
  // Template's would reach a stage, and Write, as if it were whole. The begin has warned of that link already.
  std::optional<WriteTable> StartZone(std::size_t beginIndex, const SdfLayerHandle& scratch) {
    const TreeNode& begin = tree_.nodes[beginIndex];
    const auto& role = std::get<ZoneRole>(begin.registration->behavior);
    if (role.startsFrom == nullptr) return WriteTable{};

    // 1. Ask the begin which layer it starts from: none for an empty start, or a layer, null when its link brings
    // nothing.
    std::optional<SdfLayerHandle> start;
    Call(beginIndex, [&](const TreeInputReader& inputs) {
      start = role.startsFrom(NodeContext(begin, inputs, CacheOf(beginIndex), diagnostics_, baseDirectory_));
    });
    if (!start) return WriteTable{};
    if (!*start) return std::nullopt;
    const SdfLayerHandle& source = *start;

    // 2. Copy it into the scratch layer, anchoring each relative asset path to the source's file (layer_copies.h). The
    // table maps each anchored path to the path as authored, so Write can make it relative again.
    WriteTable table;
    Call(beginIndex, [&](const TreeInputReader&) { table = CopyLayer(source, scratch); });

    // 3. A source that is another zone's layer is anonymous, so the copy anchors nothing: that zone already anchored
    // its paths when it copied its own Template, and recorded them in its write table, kept in its begin's cache since
    // its task ran first. Those entries carry over, or Write would leave the copied paths absolute.
    const auto zone = zoneOfLayer_.find(source->GetIdentifier());
    if (zone != zoneOfLayer_.end()) {
      const auto& sourceTable = CacheOf(zones_[zone->second].begin).Get<WriteTable>("writeTable");
      table.insert(sourceTable.begin(), sourceTable.end());
    }
    return table;
  }

  // The begin's report data: the asset paths its zone's layer holds anchored, each mapped to the path as authored,
  // which Write makes relative to the zone's file (docs/phase3/node-tree.md "Provenance").
  void ReportAnchoredPaths(const TreeNode& begin, const WriteTable& table) {
    if (table.empty()) return;
    VtDictionary anchored;
    for (const auto& [path, authored] : table) anchored[path] = VtValue(authored);
    result_.nodeReports[begin.id].reportData["anchoredPaths"] = VtValue(anchored);
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
  std::vector<SdfLayerHandle> zoneLayers_;          // by zone index, from MakeZoneLayers
  std::map<std::string, std::size_t> zoneOfLayer_;  // zone index by its layer's identifier
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
  pass.CheckFiles();
  for (const Task& task : tasks) pass.RunTask(task);
  caches_ = std::move(caches);

  result.treeDiagnostics = std::move(diagnostics.tree);
  for (auto& [nodeId, nodeDiagnostics] : diagnostics.byNode) {
    result.nodeReports[nodeId].diagnostics = std::move(nodeDiagnostics);
  }
  return result;
}

}  // namespace proscenium
