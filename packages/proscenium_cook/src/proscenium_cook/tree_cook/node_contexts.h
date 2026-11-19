// The contexts a node's function gets, one per role (node_roles.h). A node reaches the tree, its stage, and its layer
// only through its context: its inputs with the definitions' defaults for unauthored ones, its diagnostics, and its
// cache (docs/plans/cook-module.md "The package"). Each role's context gains what that role reaches as the plan's
// steps add it: a chain's stage and scratch layer arrive with step 6.
#pragma once

#include <pxr/base/tf/token.h>
#include <pxr/base/vt/value.h>
#include <pxr/pxr.h>
#include <pxr/usd/sdf/path.h>
#include <pxr/usd/usd/stage.h>

#include <any>
#include <cstddef>
#include <functional>
#include <map>
#include <optional>
#include <string>
#include <unordered_map>
#include <utility>
#include <vector>

#include "cook_diagnostics.h"
#include "node_graph.h"
#include "node_input_reader.h"
#include "node_roles.h"
#include "tree_reading.h"

namespace proscenium {

// What one node keeps between cooks, by key, such as an array converted from Blender's buffer. Nodes keep no state
// of their own; this cache belongs to the cook, keyed by node ID, so reuse and the differential test see it.
class NodeCache {
 public:
  // The entry at key, made empty when it's missing or holds another type.
  template <class T>
  T& Get(const std::string& key) {
    std::any& entry = entries_[key];
    if (entry.type() != typeid(T)) entry = T{};
    return std::any_cast<T&>(entry);
  }

 private:
  std::unordered_map<std::string, std::any> entries_;
};

// A node's inputs as the tree gives them: a linked input's value from the output its link traces back to, an
// unlinked one's authored value, or its definition's default.
class TreeInputReader final : public NodeInputReader {
 public:
  // Looks up the value another node's output committed earlier in the current cook. It returns an empty VtValue when
  // that node committed nothing to the output, for example because it didn't run.
  using OutputValues = std::function<PXR_NS::VtValue(const OutputRef&)>;

  TreeInputReader(const TreeNodes& tree, const NodeGraph& graph, std::size_t node, OutputValues valueOf)
      : tree_(tree), graph_(graph), node_(node), valueOf_(std::move(valueOf)) {}

 protected:
  [[nodiscard]] PXR_NS::VtValue Read(const PXR_NS::TfToken& attributeName) const override;
  [[nodiscard]] std::vector<PXR_NS::VtValue> ReadAll(const PXR_NS::TfToken& attributeName) const override;
  [[nodiscard]] bool IsAuthored(const PXR_NS::TfToken& attributeName) const override;

 private:
  const TreeNodes& tree_;
  const NodeGraph& graph_;
  std::size_t node_;
  OutputValues valueOf_;
};

// What every context gives its node: its ID, its inputs, its diagnostics, and its cache.
class NodeContext {
 public:
  // baseDirectory is the cook's, for // paths; empty for none.
  NodeContext(const TreeNode& node, const NodeInputReader& inputs, NodeCache& cache, CookDiagnostics& diagnostics,
              const std::string& baseDirectory)
      : node_(node), inputs_(inputs), cache_(cache), diagnostics_(diagnostics), baseDirectory_(baseDirectory) {}

  [[nodiscard]] const std::string& NodeId() const { return node_.id; }
  [[nodiscard]] const NodeInputReader& Inputs() const { return inputs_; }

  // Whether the node's input has a link, though the link may bring nothing.
  [[nodiscard]] bool IsLinked(const PXR_NS::TfToken& attributeName) const {
    return node_.links.find(attributeName) != node_.links.end();
  }

  // The path a Path property names, as USD's resolver takes it (docs/phase3/node-tree.md "The tree as plain data"):
  // a // path joined to the base directory, and any other as written. A // path with no base directory is an error,
  // and nothing; a ./ or ../ path (or .\ or ..\) warns, since it resolves against the process's working directory.
  [[nodiscard]] std::optional<std::string> ExpandPath(const std::string& path,
                                                      const PXR_NS::TfToken& attributeName) const;

  // The path of the node's attribute in the tree's layer, which a diagnostic about it concerns.
  [[nodiscard]] PXR_NS::SdfPath AttributePath(const PXR_NS::TfToken& attributeName) const {
    return node_.spec->GetPath().AppendProperty(attributeName);
  }

  // Reports a problem on the node; sourcePath is the path in the authored layer it concerns, if it has one.
  void ReportError(DiagnosticCode code, std::string message, PXR_NS::SdfPath sourcePath = {}) const {
    diagnostics_.AddNode(node_.id, Severity::kError, code, std::move(message), std::move(sourcePath));
  }
  void ReportWarning(DiagnosticCode code, std::string message, PXR_NS::SdfPath sourcePath = {}) const {
    diagnostics_.AddNode(node_.id, Severity::kWarning, code, std::move(message), std::move(sourcePath));
  }

  // The node's cached entry at key, kept between cooks while the node keeps its ID and type.
  template <class T>
  [[nodiscard]] T& Cache(const std::string& key) const {
    return cache_.Get<T>(key);
  }

 private:
  const TreeNode& node_;
  const NodeInputReader& inputs_;
  NodeCache& cache_;
  CookDiagnostics& diagnostics_;
  const std::string& baseDirectory_;
};

// A value node's inputs: it gets no stage and no layer.
class ValueInputs final : public NodeContext {
 public:
  using NodeContext::NodeContext;
};

// One step of a zone's chain. Its zone's stage and scratch layer arrive with step 6.
class AuthoringContext final : public NodeContext {
 public:
  using NodeContext::NodeContext;
};

// The stages a cook returns, each keyed by node ID.
using StagesByNode = std::map<std::string, PXR_NS::UsdStageRefPtr>;

// A task of its own: it commits its outputs for the tasks downstream of it, and a Stage Output its stage.
class TaskContext final : public NodeContext {
 public:
  TaskContext(const TreeNode& node, const NodeInputReader& inputs, NodeCache& cache, CookDiagnostics& diagnostics,
              const std::string& baseDirectory, ValueOutputs& outputs, StagesByNode& stageOutputs)
      : NodeContext(node, inputs, cache, diagnostics, baseDirectory), outputs_(outputs), stageOutputs_(stageOutputs) {}

  // Commits the node's outputs, as its generated Write<Type>Outputs gives them.
  void SetOutputs(ValueOutputs outputs) const { outputs_ = std::move(outputs); }

  // Returns stage as the cook's stage for this Stage Output.
  void SetStageOutput(PXR_NS::UsdStageRefPtr stage) const { stageOutputs_[NodeId()] = std::move(stage); }

 private:
  ValueOutputs& outputs_;
  StagesByNode& stageOutputs_;
};

}  // namespace proscenium
