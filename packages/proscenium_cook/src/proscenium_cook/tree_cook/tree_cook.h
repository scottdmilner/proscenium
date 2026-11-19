// TreeCook, the stateful cook of one tree (docs/plans/cook-module.md "The interface"). It holds the tree's stage from
// its construction until it's dropped, never edits it, and reads only its root layer. Each cook reads and checks the
// tree, orders its nodes, and runs them serially in that order, so each sees its upstream nodes' committed results.
#pragma once

#include <pxr/base/vt/dictionary.h>
#include <pxr/pxr.h>
#include <pxr/usd/usd/stage.h>

#include <map>
#include <memory>
#include <string>
#include <utility>
#include <vector>

#include "cook_diagnostics.h"
#include "node_contexts.h"
#include "node_definitions.h"

namespace proscenium {

// One node's diagnostics and report data.
struct NodeReport {
  std::vector<NodeDiagnostic> diagnostics;
  PXR_NS::VtDictionary reportData;
};

// One cook's results, each keyed by node ID.
struct CookResult {
  std::map<std::string, PXR_NS::UsdStageRefPtr> stageOutputs;
  std::map<std::string, PXR_NS::UsdStageRefPtr> viewerStages;
  std::map<std::string, NodeReport> nodeReports;  // only nodes with diagnostics or report data
  std::vector<NodeDiagnostic> treeDiagnostics;
};

class TreeCook {
 public:
  // Throws std::invalid_argument for a null stage.
  TreeCook(PXR_NS::UsdStageRefPtr treeStage, std::string baseDirectory,
           std::shared_ptr<const NodeDefinitions> definitions);

  // Cooks the whole tree. Problems in the tree are diagnostics in the result, never exceptions.
  CookResult Cook();

 private:
  PXR_NS::UsdStageRefPtr treeStage_;
  std::string baseDirectory_;  // for // paths; empty for none
  std::shared_ptr<const NodeDefinitions> definitions_;
  // By node ID and type name, kept while the tree holds a node with both: Blender reuses a deleted node's name.
  std::map<std::pair<std::string, PXR_NS::TfToken>, NodeCache> caches_;
};

}  // namespace proscenium
