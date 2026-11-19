#include "cook_diagnostics.h"

#include <algorithm>
#include <utility>

PXR_NAMESPACE_USING_DIRECTIVE

namespace proscenium {

const char* DiagnosticCodeName(DiagnosticCode code) {
  switch (code) {
    case DiagnosticCode::kMissingTree:
      return "missing-tree";
    case DiagnosticCode::kNotANodeTree:
      return "not-a-node-tree";
    case DiagnosticCode::kUnknownTreeFormat:
      return "unknown-tree-format";
    case DiagnosticCode::kCompositionInTree:
      return "composition-in-tree";
    case DiagnosticCode::kInvalidNodeName:
      return "invalid-node-name";
    case DiagnosticCode::kUnknownNodeType:
      return "unknown-node-type";
    case DiagnosticCode::kMissingNodeVersion:
      return "missing-node-version";
    case DiagnosticCode::kNewerNodeVersion:
      return "newer-node-version";
    case DiagnosticCode::kUnknownAttribute:
      return "unknown-attribute";
    case DiagnosticCode::kWrongAttributeType:
      return "wrong-attribute-type";
    case DiagnosticCode::kInvalidToken:
      return "invalid-token";
    case DiagnosticCode::kInvalidPrimPath:
      return "invalid-prim-path";
    case DiagnosticCode::kInvalidPrimsExpression:
      return "invalid-prims-expression";
    case DiagnosticCode::kUnresolvedConnection:
      return "unresolved-connection";
    case DiagnosticCode::kIncompatibleLink:
      return "incompatible-link";
    case DiagnosticCode::kTooManyLinks:
      return "too-many-links";
    case DiagnosticCode::kCycle:
      return "cycle";
    case DiagnosticCode::kNoUpstreamValue:
      return "no-upstream-value";
    case DiagnosticCode::kUsdError:
      return "usd-error";
    case DiagnosticCode::kUnpairedZone:
      return "unpaired-zone";
    case DiagnosticCode::kChainBranch:
      return "chain-branch";
    case DiagnosticCode::kBrokenChain:
      return "broken-chain";
    case DiagnosticCode::kMismatchedZone:
      return "mismatched-zone";
    case DiagnosticCode::kUnreachedZoneEnd:
      return "unreached-zone-end";
    case DiagnosticCode::kNoChain:
      return "no-chain";
    case DiagnosticCode::kSharedFile:
      return "shared-file";
    case DiagnosticCode::kMissingBaseDirectory:
      return "missing-base-directory";
    case DiagnosticCode::kWorkingDirectoryPath:
      return "working-directory-path";
    case DiagnosticCode::kMissingPath:
      return "missing-path";
    case DiagnosticCode::kFileNotFound:
      return "file-not-found";
    case DiagnosticCode::kUnreadableFile:
      return "unreadable-file";
    case DiagnosticCode::kUnlinkedInput:
      return "unlinked-input";
    case DiagnosticCode::kMissingStageMetrics:
      return "missing-stage-metrics";
  }
  return "";
}

const char* SeverityName(Severity severity) { return severity == Severity::kError ? "error" : "warning"; }

void CookDiagnostics::AddTree(Severity severity, DiagnosticCode code, std::string message, SdfPath sourcePath) {
  tree.push_back({severity, code, std::move(message), std::move(sourcePath)});
}

void CookDiagnostics::AddNode(const std::string& nodeId, Severity severity, DiagnosticCode code, std::string message,
                              SdfPath sourcePath) {
  byNode[nodeId].push_back({severity, code, std::move(message), std::move(sourcePath)});
}

bool CookDiagnostics::HasError(const std::string& nodeId) const {
  const auto found = byNode.find(nodeId);
  return found != byNode.end() && std::any_of(found->second.begin(), found->second.end(),
                                              [](const NodeDiagnostic& d) { return d.severity == Severity::kError; });
}

}  // namespace proscenium
