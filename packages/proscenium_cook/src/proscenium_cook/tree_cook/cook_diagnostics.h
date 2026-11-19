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
  kNoUpstreamValue,         // a link that brings nothing, from a node that failed, can't run, or is muted
  kUsdError,                // a USD error the node raised while it ran, which it doesn't report as its own
  // A zone's (docs/phase3/node-tree.md "What a zone holds"):
  kUnpairedZone,      // a begin whose zone:end names no end of its zone, or an end no one begin names
  kChainBranch,       // an Editable Layer output linked to more than one input
  kBrokenChain,       // an end its begin's chain doesn't reach
  kMismatchedZone,    // an end another begin's chain reaches
  kUnreachedZoneEnd,  // a chain node on a chain that never reaches its end
  kNoChain,           // an authoring node whose Editable Layer doesn't trace back to a begin
  kSharedFile,        // two zones that save to one file
  // A Path property's (docs/phase3/node-tree.md "The tree as plain data"):
  kMissingBaseDirectory,  // a // path with no base directory: the .blend isn't saved
  kWorkingDirectoryPath,  // a path starting with ./ or ../, which resolves against the working directory
  // A node type's own:
  kMissingPath,          // Layer from File or Prim: an empty Path
  kFileNotFound,         // Layer from File: no file at Path
  kUnreadableFile,       // Layer from File: a file that doesn't parse as a layer
  kUnlinkedInput,        // Stage Output: nothing linked into its Layer
  kMissingStageMetrics,  // Stage Output: a root layer that authors no upAxis or metersPerUnit
  kInvalidDefaultPrim,   // New Layer Zone: a Default Prim that isn't a prim of the zone's layer
  kDefaultPrimNotDef,    // New Layer Zone: a Default Prim whose spec is an over or a class
  kInvalidPrimName,      // Create Prim: a Name that isn't a valid identifier
  kExistingPrimSpec,     // Create Prim: a prim the layer already has a spec for
  kUnknownPrimType,      // Create Prim: a Type that names no registered schema
  kNonConcretePrimType,  // Create Prim: a Type that names an abstract or API schema
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
    DiagnosticCode::kNoUpstreamValue,
    DiagnosticCode::kUsdError,
    DiagnosticCode::kUnpairedZone,
    DiagnosticCode::kChainBranch,
    DiagnosticCode::kBrokenChain,
    DiagnosticCode::kMismatchedZone,
    DiagnosticCode::kUnreachedZoneEnd,
    DiagnosticCode::kNoChain,
    DiagnosticCode::kSharedFile,
    DiagnosticCode::kMissingBaseDirectory,
    DiagnosticCode::kWorkingDirectoryPath,
    DiagnosticCode::kMissingPath,
    DiagnosticCode::kFileNotFound,
    DiagnosticCode::kUnreadableFile,
    DiagnosticCode::kUnlinkedInput,
    DiagnosticCode::kMissingStageMetrics,
    DiagnosticCode::kInvalidDefaultPrim,
    DiagnosticCode::kDefaultPrimNotDef,
    DiagnosticCode::kInvalidPrimName,
    DiagnosticCode::kExistingPrimSpec,
    DiagnosticCode::kUnknownPrimType,
    DiagnosticCode::kNonConcretePrimType,
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
