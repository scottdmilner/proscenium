// Create Prim authors one new prim spec, Parent joined with Name, and an over for each ancestor its layer lacks
// (docs/phase3/node-tree.md "Create Prim"). Its Prim output is the new prim's path, computed from its inputs alone, so
// it's ready before any task runs, for nodes in this zone and in others.
#include <pxr/base/tf/token.h>
#include <pxr/base/tf/type.h>
#include <pxr/usd/sdf/path.h>
#include <pxr/usd/sdf/types.h>
#include <pxr/usd/usd/schemaRegistry.h>

#include <optional>
#include <string>
#include <utility>

#include "nodes/create_prim_attributes.h"
#include "nodes/node_types.h"

PXR_NAMESPACE_USING_DIRECTIVE

namespace proscenium {
namespace {

// Why a Type that isn't a concrete prim type isn't one, by its schema kind, or nothing for a concrete type.
std::optional<std::pair<DiagnosticCode, std::string>> TypeProblem(const TfToken& type) {
  const TfType schema = UsdSchemaRegistry::GetTypeFromSchemaTypeName(type);
  const std::string quoted = "Type \"" + type.GetString() + "\"";
  if (schema.IsUnknown()) return std::pair{DiagnosticCode::kUnknownPrimType, quoted + " names no registered schema"};
  switch (UsdSchemaRegistry::GetSchemaKind(schema)) {
    case UsdSchemaKind::ConcreteTyped:
      return std::nullopt;
    case UsdSchemaKind::AbstractBase:
    case UsdSchemaKind::AbstractTyped:
      return std::pair{
          DiagnosticCode::kNonConcretePrimType,
          quoted + " is an abstract schema, which no prim has as its type; a concrete one derives from it"};
    default:
      return std::pair{DiagnosticCode::kNonConcretePrimType,
                       quoted + " is an API schema, which Edit Prim applies; a prim's type is a concrete schema"};
  }
}

// The new prim's path; empty when Parent brings nothing, its link's warning says why, or Name isn't a valid
// identifier, which CreatePrimPath reports.
SdfPath NewPrimPath(const CreatePrimInputs& inputs) {
  if (inputs.parent.IsEmpty() || !SdfPath::IsValidIdentifier(inputs.name)) return {};
  return inputs.parent.AppendChild(TfToken(inputs.name));
}

SdfSpecifier SpecifierOf(const TfToken& specifier) {
  // The shared checks have refused any other token, since the menu is closed.
  if (specifier == "over") return SdfSpecifierOver;
  if (specifier == "class") return SdfSpecifierClass;
  return SdfSpecifierDef;
}

}  // namespace

ValueOutputs CreatePrimPath(const ValueInputs& context) {
  const CreatePrimInputs inputs = ReadCreatePrimInputs(context.Inputs());
  const TfToken parentName(CreatePrimInputs::kParent);
  // An authored empty Parent names nothing; a linked one that brings nothing has its link's warning.
  if (inputs.parent.IsEmpty() && !context.IsLinked(parentName)) {
    context.ReportError(DiagnosticCode::kInvalidPrimPath, "Parent is empty; / is the parent of a root prim",
                        context.AttributePath(parentName));
  }
  // Valid identifiers include UTF-8 names that USD accepts, such as café.
  if (!SdfPath::IsValidIdentifier(inputs.name)) {
    context.ReportError(DiagnosticCode::kInvalidPrimName,
                        inputs.name.empty() ? "Name is empty" : "Name \"" + inputs.name + "\" isn't a valid identifier",
                        context.AttributePath(TfToken(CreatePrimInputs::kName)));
  }
  // The type is a suggestion from the registered concrete types, so another one warns and is still authored, as USD
  // allows. It's checked here, before any task runs, since the schema registry is USD API, which the node's authoring,
  // inside its zone's SdfChangeBlock, doesn't call.
  if (!inputs.type.IsEmpty()) {
    if (const auto problem = TypeProblem(inputs.type)) {
      context.ReportWarning(problem->first, problem->second, context.AttributePath(TfToken(CreatePrimInputs::kType)));
    }
  }
  CreatePrimOutputs outputs;
  outputs.prim = NewPrimPath(inputs);
  return WriteCreatePrimOutputs(outputs);
}

void AuthorCreatePrim(AuthoringContext& context) {
  const CreatePrimInputs inputs = ReadCreatePrimInputs(context.Inputs());
  const SdfPath path = NewPrimPath(inputs);
  if (path.IsEmpty()) return;  // CreatePrimPath has reported why, and the chain stops before this node

  // A spec the layer already has, from the zone's Template or an earlier node, is an error, naming where it came from,
  // except an over an earlier node authored only because a prim it created needed an ancestor: this node takes it, so
  // a chain may create a child before its parent. An over on a prim a sublayer defines is ordinary: that prim has no
  // spec in this layer.
  if (context.HasPrimSpec(path)) {
    // Every spec the layer holds has its entry, from the begin's copy of the Template or from the node that wrote it.
    const EditAuthor* author = context.PrimSpecAuthor(path);
    if (author == nullptr || author->kind != EditKind::kMissingAncestor) {
      std::string from;
      if (author != nullptr) {
        from = (author->kind == EditKind::kTemplate ? ", copied from the Template by \"" : ", authored by \"") +
               author->nodeId + "\"";
      }
      context.ReportError(DiagnosticCode::kExistingPrimSpec,
                          "the zone's layer already has a spec for " + path.GetString() + from,
                          context.AttributePath(TfToken(CreatePrimInputs::kName)));
      return;
    }
  }
  context.CreatePrimSpec(path, SpecifierOf(inputs.specifier), inputs.type);
}

}  // namespace proscenium
