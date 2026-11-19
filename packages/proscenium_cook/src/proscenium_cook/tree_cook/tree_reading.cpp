#include "tree_reading.h"

#include <pxr/base/tf/errorMark.h>
#include <pxr/base/tf/stringUtils.h>
#include <pxr/base/vt/value.h>
#include <pxr/usd/sdf/attributeSpec.h>
#include <pxr/usd/sdf/pathExpression.h>
#include <pxr/usd/sdf/relationshipSpec.h>
#include <pxr/usd/sdf/schema.h>
#include <pxr/usd/sdf/types.h>

#include <algorithm>
#include <unordered_map>
#include <utility>

#include "node_ids.h"

PXR_NAMESPACE_USING_DIRECTIVE

namespace proscenium {
namespace {

const SdfPath& TreePath() {
  static const SdfPath path("/Tree");
  return path;
}

// The attributes every node may author beside its definition's: its version and mute flag. The ui: namespace, node
// positions in test files, is ignored.
bool IsNodeOwnAttribute(const std::string& name) {
  return name == "node:version" || name == "node:mute" || TfStringStartsWith(name, "ui:");
}

// A sublayer or composition arc anywhere in the tree's layer: the tree has none, so each is the tree's error.
void CheckNoComposition(const SdfLayerHandle& layer, CookDiagnostics& diagnostics) {
  if (!layer->GetSubLayerPaths().empty()) {
    diagnostics.AddTree(Severity::kError, DiagnosticCode::kCompositionInTree,
                        "The tree's layer has sublayers; a tree composes nothing", SdfPath::AbsoluteRootPath());
  }
  layer->Traverse(SdfPath::AbsoluteRootPath(), [&](const SdfPath& path) {
    if (!path.IsPrimPath()) return;
    const SdfPrimSpecHandle prim = layer->GetPrimAtPath(path);
    if (prim && (prim->HasReferences() || prim->HasPayloads() || prim->HasInheritPaths() || prim->HasSpecializes() ||
                 !prim->GetVariantSetNameList().GetAppliedItems().empty())) {
      diagnostics.AddTree(Severity::kError, DiagnosticCode::kCompositionInTree,
                          "The tree's layer has a composition arc at " + path.GetString() + "; a tree composes nothing",
                          path);
    }
  });
}

// The /Tree prim, when it's a tree this cook reads; otherwise null, with the tree's error added.
SdfPrimSpecHandle FindTree(const SdfLayerHandle& layer, CookDiagnostics& diagnostics) {
  const SdfPrimSpecHandle tree = layer->GetPrimAtPath(TreePath());
  if (!tree) {
    diagnostics.AddTree(Severity::kError, DiagnosticCode::kMissingTree, "The tree's layer has no /Tree prim");
    return {};
  }
  if (tree->GetTypeName() != TfToken("NodeTree")) {
    diagnostics.AddTree(Severity::kError, DiagnosticCode::kNotANodeTree,
                        "/Tree is a " + tree->GetTypeName().GetString() + ", not a NodeTree", TreePath());
    return {};
  }
  const SdfAttributeSpecHandle format = layer->GetAttributeAtPath(TreePath().AppendProperty(TfToken("tree:format")));
  const VtValue value = format ? format->GetDefaultValue() : VtValue();
  if (!value.IsHolding<int>() || value.UncheckedGet<int>() != kTreeFormat) {
    const std::string found =
        value.IsHolding<int>() ? "format " + TfStringify(value.UncheckedGet<int>()) : "no int tree:format";
    diagnostics.AddTree(Severity::kError, DiagnosticCode::kUnknownTreeFormat,
                        "The tree has " + found + "; this cook reads format " + TfStringify(kTreeFormat), TreePath());
    return {};
  }
  return tree;
}

// The tree's nodes, each with its ID, type, definition, and mute flag, in node-ID order.
std::vector<TreeNode> ReadNodes(const SdfPrimSpecHandle& tree, const NodeDefinitions& definitions,
                                CookDiagnostics& diagnostics) {
  std::vector<TreeNode> nodes;
  for (const SdfPrimSpecHandle& prim : tree->GetNameChildren()) {
    const auto id = NodeIdFromPrimName(prim->GetName());
    if (!id) {
      diagnostics.AddTree(Severity::kError, DiagnosticCode::kInvalidNodeName,
                          "The prim name " + prim->GetName() + " doesn't decode to a node ID", prim->GetPath());
      continue;
    }
    TreeNode node;
    node.id = *id;
    node.spec = prim;
    node.typeName = prim->GetTypeName();
    node.definition = definitions.Find(node.typeName);
    node.registration = node.definition ? FindNodeRegistration(node.typeName.GetText()) : nullptr;
    const SdfAttributeSpecHandle mute = prim->GetAttributes().get(TfToken("node:mute"));
    node.muted = mute && mute->GetDefaultValue().IsHolding<bool>() && mute->GetDefaultValue().UncheckedGet<bool>();
    if (!node.definition) {
      diagnostics.AddNode(node.id, Severity::kError, DiagnosticCode::kUnknownNodeType,
                          "No node type is named " + (node.typeName.IsEmpty() ? "\"\"" : node.typeName.GetString()),
                          prim->GetPath());
    }
    nodes.push_back(std::move(node));
  }
  std::sort(nodes.begin(), nodes.end(), [](const TreeNode& a, const TreeNode& b) { return a.id < b.id; });
  return nodes;
}

// node:mute, read for every node, must be a bool; another type reads as unmuted.
void CheckMute(const TreeNode& node, CookDiagnostics& diagnostics) {
  const SdfAttributeSpecHandle mute = node.spec->GetAttributes().get(TfToken("node:mute"));
  if (mute && mute->GetTypeName() != SdfValueTypeNames->Bool) {
    diagnostics.AddNode(node.id, Severity::kError, DiagnosticCode::kWrongAttributeType,
                        "node:mute is a " + mute->GetTypeName().GetAsToken().GetString() + ", not a bool",
                        mute->GetPath());
  }
}

void CheckVersion(const TreeNode& node, CookDiagnostics& diagnostics) {
  const SdfAttributeSpecHandle version = node.spec->GetAttributes().get(TfToken("node:version"));
  const VtValue value = version ? version->GetDefaultValue() : VtValue();
  if (!version || value.IsEmpty()) {
    diagnostics.AddNode(node.id, Severity::kError, DiagnosticCode::kMissingNodeVersion,
                        "The node authors no node:version", node.spec->GetPath());
  } else if (!value.IsHolding<int>()) {
    diagnostics.AddNode(node.id, Severity::kError, DiagnosticCode::kWrongAttributeType,
                        "node:version is a " + version->GetTypeName().GetAsToken().GetString() + ", not an int",
                        version->GetPath());
  } else if (value.UncheckedGet<int>() > node.definition->version) {
    diagnostics.AddNode(node.id, Severity::kError, DiagnosticCode::kNewerNodeVersion,
                        node.typeName.GetString() + " version " + TfStringify(value.UncheckedGet<int>()) +
                            " is newer than this cook's, " + TfStringify(node.definition->version),
                        version->GetPath());
  }
}

// Why text isn't a Prim's path: not absolute, or naming a property or a variant; empty when it's an absolute prim path,
// or the absolute root, which a Create Prim's Parent names for a root prim (docs/phase3/node-tree.md "Prim").
std::string PrimPathProblem(const std::string& text) {
  if (!SdfPath::IsValidPathString(text)) return "which isn't a path";
  const SdfPath path(text);
  if (!path.IsAbsolutePath()) return "which isn't absolute";
  if (path.ContainsPrimVariantSelection()) return "which names a variant";
  if (!path.IsAbsoluteRootOrPrimPath()) return "which isn't a prim's path";
  return {};
}

// The shared checks on an authored value, against its attribute's definition.
void CheckValue(const TreeNode& node, const SdfAttributeSpecHandle& attribute,
                const AttributeDefinition& attributeDefinition, CookDiagnostics& diagnostics) {
  const VtValue value = attribute->GetDefaultValue();
  if (!attributeDefinition.allowedTokens.empty() && value.IsHolding<TfToken>()) {
    const auto& token = value.UncheckedGet<TfToken>();
    // A menu is a suggestion where USD takes other values, and a closed menu, such as a specifier, the only values.
    if (std::find(attributeDefinition.allowedTokens.begin(), attributeDefinition.allowedTokens.end(), token) ==
        attributeDefinition.allowedTokens.end()) {
      diagnostics.AddNode(
          node.id, attributeDefinition.closedMenu ? Severity::kError : Severity::kWarning,
          DiagnosticCode::kInvalidToken,
          attribute->GetName() + " is \"" + token.GetString() + "\", which isn't one of its menu's items",
          attribute->GetPath());
    }
  }
  if (attributeDefinition.kind == SocketKind::kPrims && value.IsHolding<std::string>()) {
    const TfErrorMark mark;
    const SdfPathExpression expression(value.UncheckedGet<std::string>());
    if (!mark.IsClean()) {
      const std::string problem = mark.begin()->GetCommentary();
      mark.Clear();
      diagnostics.AddNode(node.id, Severity::kError, DiagnosticCode::kInvalidPrimsExpression,
                          attribute->GetName() + " doesn't parse as a path expression: " + problem,
                          attribute->GetPath());
    }
  }
  if (attributeDefinition.kind == SocketKind::kPrim && value.IsHolding<std::string>() &&
      !value.UncheckedGet<std::string>().empty()) {
    const auto& text = value.UncheckedGet<std::string>();
    if (const std::string problem = PrimPathProblem(text); !problem.empty()) {
      diagnostics.AddNode(node.id, Severity::kError, DiagnosticCode::kInvalidPrimPath,
                          attribute->GetName() + " is \"" + text + "\", " + problem, attribute->GetPath());
    }
  }
}

// The shared checks on a node of a known type: its version, and each property against its definition.
void CheckAgainstDefinition(const TreeNode& node, CookDiagnostics& diagnostics) {
  CheckVersion(node, diagnostics);
  CheckMute(node, diagnostics);
  for (const SdfPropertySpecHandle& property : node.spec->GetProperties()) {
    const std::string& name = property->GetName();
    if (IsNodeOwnAttribute(name)) continue;
    const SdfAttributeSpecHandle attribute = TfDynamic_cast<SdfAttributeSpecHandle>(property);
    if (!attribute) {
      // A zone's begin names its end; FindZones checks the pairs.
      if (name != "zone:end" || node.definition->zone != ZoneEdge::kBegin) {
        diagnostics.AddNode(node.id, Severity::kError, DiagnosticCode::kUnknownAttribute,
                            node.typeName.GetString() + " has no relationship " + name, property->GetPath());
      }
      continue;
    }
    const AttributeDefinition* attributeDefinition = node.definition->FindAttribute(attribute->GetNameToken());
    if (attributeDefinition == nullptr) {
      diagnostics.AddNode(node.id, Severity::kError, DiagnosticCode::kUnknownAttribute,
                          node.typeName.GetString() + " has no attribute " + name, attribute->GetPath());
    } else if (attribute->GetTypeName() != attributeDefinition->valueType) {
      diagnostics.AddNode(node.id, Severity::kError, DiagnosticCode::kWrongAttributeType,
                          name + " is a " + attribute->GetTypeName().GetAsToken().GetString() + ", not a " +
                              attributeDefinition->valueType.GetAsToken().GetString(),
                          attribute->GetPath());
    } else {
      CheckValue(node, attribute, *attributeDefinition, diagnostics);
    }
  }
}

// Whether a value of type `from` converts to `to` across a link without loss: the same type, or half to float to
// double, in each vector width, and int to int64 (docs/phase3/node-tree.md "Values and USD types").
bool ValueConverts(const SdfValueTypeName& from, const SdfValueTypeName& to) {
  if (from.GetType() == to.GetType()) return true;
  static const std::vector<std::pair<std::string, std::string>> widenings{
      {"GfHalf", "float"},    {"GfHalf", "double"},   {"float", "double"},    {"GfVec2h", "GfVec2f"},
      {"GfVec2h", "GfVec2d"}, {"GfVec2f", "GfVec2d"}, {"GfVec3h", "GfVec3f"}, {"GfVec3h", "GfVec3d"},
      {"GfVec3f", "GfVec3d"}, {"GfVec4h", "GfVec4f"}, {"GfVec4h", "GfVec4d"}, {"GfVec4f", "GfVec4d"},
      {"int", "int64_t"},
  };
  const std::pair<std::string, std::string> pair{from.GetCPPTypeName(), to.GetCPPTypeName()};
  return std::find(widenings.begin(), widenings.end(), pair) != widenings.end();
}

// A socket kind's name with its article, such as "an EditableLayer".
std::string WithArticle(SocketKind kind) {
  const std::string name = SocketKindName(kind);
  return (std::string("AEIOU").find(name.front()) == std::string::npos ? "a " : "an ") + name;
}

// Why a link from output to input is invalid; empty when it's valid.
std::string LinkProblem(const AttributeDefinition& output, const AttributeDefinition& input) {
  if (output.kind != input.kind) {
    if (output.kind == SocketKind::kPrim && input.kind == SocketKind::kPrims) return {};  // a single-path expression
    // The Viewer, partway down a chain: it gets a copy of the zone's layer there (docs/phase3/node-tree.md "Viewer").
    if (output.kind == SocketKind::kEditableLayer && input.takesEditableLayer) return {};
    return WithArticle(output.kind) + " output can't link to " + WithArticle(input.kind) + " input";
  }
  if (input.kind != SocketKind::kValue || input.dynamicType || ValueConverts(output.valueType, input.valueType)) {
    return {};
  }
  return "a " + output.valueType.GetAsToken().GetString() + " output can't link to a " +
         input.valueType.GetAsToken().GetString() + " input without losing precision; use a Convert node";
}

// Each node's links, from its inputs' connections, and the problems with them.
void ReadLinks(std::vector<TreeNode>& nodes, CookDiagnostics& diagnostics) {
  std::unordered_map<SdfPath, std::size_t, SdfPath::Hash> indexByPrim;
  for (std::size_t i = 0; i < nodes.size(); ++i) indexByPrim.emplace(nodes[i].spec->GetPath(), i);
  for (TreeNode& node : nodes) {
    for (const SdfAttributeSpecHandle& attribute : node.spec->GetAttributes()) {
      SdfPathVector targets;
      attribute->GetConnectionPathList().ApplyEditsToList(&targets);
      if (targets.empty()) continue;
      const SdfPath& inputPath = attribute->GetPath();
      if (!TfStringStartsWith(attribute->GetName(), "inputs:")) {
        diagnostics.AddNode(node.id, Severity::kError, DiagnosticCode::kUnresolvedConnection,
                            attribute->GetName() + " has a connection; only an input takes links", inputPath);
        continue;
      }
      const AttributeDefinition* input =
          node.definition ? node.definition->FindAttribute(attribute->GetNameToken()) : nullptr;
      std::vector<NodeLink> links;
      for (const SdfPath& target : targets) {
        const auto found = target.IsPropertyPath() ? indexByPrim.find(target.GetPrimPath()) : indexByPrim.end();
        const TreeNode* source = found == indexByPrim.end() ? nullptr : &nodes[found->second];
        const TfToken outputName = target.GetNameToken();
        const bool isOutput = TfStringStartsWith(outputName.GetString(), "outputs:");
        const AttributeDefinition* output =
            source && source->definition ? source->definition->FindAttribute(outputName) : nullptr;
        const bool exists = source && isOutput &&
                            (source->definition ? output != nullptr && output->role == AttributeRole::kOutput
                                                : static_cast<bool>(source->spec->GetAttributes().get(outputName)));
        if (!exists) {
          diagnostics.AddNode(
              node.id, Severity::kError, DiagnosticCode::kUnresolvedConnection,
              attribute->GetName() + " connects to " + target.GetString() + ", which is no node's output", inputPath);
          continue;
        }
        if (input != nullptr && output != nullptr) {
          const std::string problem = LinkProblem(*output, *input);
          if (!problem.empty()) {
            diagnostics.AddNode(node.id, Severity::kError, DiagnosticCode::kIncompatibleLink,
                                attribute->GetName() + ": " + problem, inputPath);
            continue;
          }
        }
        links.push_back({found->second, outputName});
      }
      if (input != nullptr && !input->multiInput && links.size() > 1) {
        diagnostics.AddNode(node.id, Severity::kError, DiagnosticCode::kTooManyLinks,
                            attribute->GetName() + " takes one link, and has " + TfStringify(links.size()), inputPath);
        links.resize(1);
      }
      if (!links.empty()) node.links.emplace(attribute->GetNameToken(), std::move(links));
    }
  }
}

}  // namespace

TreeNodes ReadTree(const SdfLayerHandle& layer, const NodeDefinitions& definitions, CookDiagnostics& diagnostics) {
  TreeNodes tree;
  const SdfPrimSpecHandle treePrim = FindTree(layer, diagnostics);
  if (!treePrim) return tree;
  CheckNoComposition(layer, diagnostics);
  tree.readable = true;
  tree.nodes = ReadNodes(treePrim, definitions, diagnostics);
  for (const TreeNode& node : tree.nodes) {
    if (node.definition) CheckAgainstDefinition(node, diagnostics);
  }
  ReadLinks(tree.nodes, diagnostics);
  return tree;
}

}  // namespace proscenium
