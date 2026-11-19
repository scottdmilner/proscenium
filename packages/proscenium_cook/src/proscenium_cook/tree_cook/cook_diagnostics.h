// What the cook reports: each problem's severity, its code from a fixed vocabulary, which Python's DiagnosticCode
// lists (proscenium_cook.cook_results), and, where it has one, the path it concerns. Problems in the tree are
// diagnostics, never exceptions, and the rest of the tree still cooks (docs/phase3/node-tree.md "Diagnostics").
#pragma once

#include <pxr/pxr.h>
#include <pxr/usd/sdf/path.h>

#include <array>
#include <cstdint>
#include <map>
#include <string>
#include <vector>

namespace proscenium {

enum class Severity : std::uint8_t { kError, kWarning };

enum class DiagnosticCode : std::uint8_t {
  // The tree's own, which belong to no node:
  kMissingTree,        // the tree's layer has no /Tree prim
  kNotANodeTree,       // /Tree isn't a NodeTree
  kUnknownTreeFormat,  // tree:format is missing, isn't an int, or is a format this cook doesn't read
  kCompositionInTree,  // a sublayer or composition arc in the tree's layer
  kInvalidNodeName,    // a node prim's name doesn't decode to a node ID
  // A node's:
  kUnknownNodeType,         // a type the definitions don't hold
  kMissingNodeVersion,      // no node:version authored
  kNewerNodeVersion,        // a node:version newer than the cook's definition
  kUnknownAttribute,        // an input, output, property, or relationship the definition doesn't have
  kWrongAttributeType,      // an attribute authored with another type than its definition's
  kInvalidToken,            // a token outside its menu's allowedTokens
  kInvalidPrimPath,         // a Prim that isn't an absolute prim path
  kInvalidPrimsExpression,  // a Prims that doesn't parse as a path expression
  kUnresolvedConnection,    // a connection to no other node's output
  kIncompatibleLink,        // a link between incompatible socket kinds or value types
  kTooManyLinks,            // several links into an input that takes one
  kCycle,                   // a node on a cycle of links
};

// Every code the cook reports, which Python's list must hold.
inline constexpr std::array kDiagnosticCodes{
    DiagnosticCode::kMissingTree,
    DiagnosticCode::kNotANodeTree,
    DiagnosticCode::kUnknownTreeFormat,
    DiagnosticCode::kCompositionInTree,
    DiagnosticCode::kInvalidNodeName,
    DiagnosticCode::kUnknownNodeType,
    DiagnosticCode::kMissingNodeVersion,
    DiagnosticCode::kNewerNodeVersion,
    DiagnosticCode::kUnknownAttribute,
    DiagnosticCode::kWrongAttributeType,
    DiagnosticCode::kInvalidToken,
    DiagnosticCode::kInvalidPrimPath,
    DiagnosticCode::kInvalidPrimsExpression,
    DiagnosticCode::kUnresolvedConnection,
    DiagnosticCode::kIncompatibleLink,
    DiagnosticCode::kTooManyLinks,
    DiagnosticCode::kCycle,
};

// The code's name in Python's list, such as "unknown-node-type".
const char* DiagnosticCodeName(DiagnosticCode code);

const char* SeverityName(Severity severity);  // "error" or "warning"

struct NodeDiagnostic {
  Severity severity = Severity::kError;
  DiagnosticCode code = DiagnosticCode::kUnknownNodeType;
  std::string message;
  PXR_NS::SdfPath sourcePath;  // the path in the layer it concerns; empty for none
};

// A cook's diagnostics: the tree's, and each node's, by node ID.
struct CookDiagnostics {
  std::vector<NodeDiagnostic> tree;
  std::map<std::string, std::vector<NodeDiagnostic>> byNode;

  void AddTree(Severity severity, DiagnosticCode code, std::string message, PXR_NS::SdfPath sourcePath = {});
  void AddNode(const std::string& nodeId, Severity severity, DiagnosticCode code, std::string message,
               PXR_NS::SdfPath sourcePath = {});
  [[nodiscard]] bool HasError(const std::string& nodeId) const;  // whether the node has an error so far
};

}  // namespace proscenium
