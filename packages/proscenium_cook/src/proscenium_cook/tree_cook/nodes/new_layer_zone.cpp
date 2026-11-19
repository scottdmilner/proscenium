// New Layer Zone's begin and end, in one file since each is half of one zone (docs/phase3/node-tree.md "New Layer
// Zone"). The begin names the file Write saves the zone's layer to and the Template the zone starts from, and the end
// authors its Default Prim and gives the finished layer out. The zone's chain, its task, its layer, and the Template's
// copy are the machinery's (zone_chains.h, tree_cook.cpp, layer_copies.h).
#include <pxr/base/tf/token.h>
#include <pxr/usd/ar/resolver.h>
#include <pxr/usd/sdf/layer.h>
#include <pxr/usd/sdf/path.h>
#include <pxr/usd/sdf/schema.h>
#include <pxr/usd/sdf/types.h>

#include <optional>
#include <string>

#include "nodes/new_layer_zone_begin_attributes.h"
#include "nodes/new_layer_zone_end_attributes.h"
#include "nodes/node_types.h"

PXR_NAMESPACE_USING_DIRECTIVE

namespace proscenium {

NodeFile NewLayerZoneFile(const NodeContext& context) {
  const NewLayerZoneBeginInputs inputs = ReadNewLayerZoneBeginInputs(context.Inputs());
  const TfToken fileName(NewLayerZoneBeginInputs::kFile);
  NodeFile file{{}, fileName};
  // An empty File names no file, so no other zone can share it.
  if (inputs.file.identifier.empty()) return file;
  // The file needn't exist yet, so it's identified as a new file is: by default an absolute, normalized path.
  if (const std::optional<std::string> path = context.ExpandPath(inputs.file.identifier, fileName)) {
    file.identifier = ArGetResolver().CreateIdentifierForNewAsset(*path);
  }
  return file;
}

std::optional<SdfLayerHandle> NewLayerZoneTemplate(const NodeContext& context) {
  // Unlinked, the zone starts empty; linked, from the Template's layer, null when the link brings nothing.
  if (!context.IsLinked(TfToken(NewLayerZoneBeginInputs::kTemplate))) return std::nullopt;
  return ReadNewLayerZoneBeginInputs(context.Inputs()).template_.layer;
}

void NewLayerZoneFinish(AuthoringContext& context) {
  const NewLayerZoneEndInputs inputs = ReadNewLayerZoneEndInputs(context.Inputs());
  // Empty, the layer keeps the Template's defaultPrim, and with no Template it has none; a link that brings nothing
  // has stopped the zone before this.
  if (inputs.defaultPrim.IsEmpty()) return;
  const SdfPath attribute = context.AttributePath(TfToken(NewLayerZoneEndInputs::kDefaultPrim));
  // A Prim may be /, as a parent, but / is no prim a reference could compose.
  if (inputs.defaultPrim.IsAbsoluteRootPath()) {
    context.ReportError(DiagnosticCode::kInvalidDefaultPrim,
                        "Default Prim is /, the layer's root, not a prim: name one, such as /World", attribute);
    return;
  }
  const std::optional<SdfSpecifier> specifier = context.PrimSpecifier(inputs.defaultPrim);
  if (!specifier) {
    context.ReportError(DiagnosticCode::kInvalidDefaultPrim,
                        "Default Prim " + inputs.defaultPrim.GetString() + " isn't a prim of the zone's layer",
                        attribute);
    return;
  }
  // USD composes an over or a class as the target, so either is authored, with a warning: an over defines no prim
  // unless a sublayer does, and a class is abstract on a stage opened on the layer.
  if (*specifier == SdfSpecifierOver) {
    context.ReportWarning(DiagnosticCode::kDefaultPrimNotDef,
                          "Default Prim " + inputs.defaultPrim.GetString() +
                              " is an over in the zone's layer, which defines no prim there: a reference composes only "
                              "its opinions",
                          attribute);
  } else if (*specifier == SdfSpecifierClass) {
    context.ReportWarning(DiagnosticCode::kDefaultPrimNotDef,
                          "Default Prim " + inputs.defaultPrim.GetString() +
                              " is a class: a stage opened on the layer treats it as abstract",
                          attribute);
  }
  // A root prim by its name, as every USD reads it, and a deeper prim by its path, which USD reads from 0.25.
  const TfToken name =
      inputs.defaultPrim.IsRootPrimPath() ? inputs.defaultPrim.GetNameToken() : inputs.defaultPrim.GetAsToken();
  context.SetLayerField(SdfFieldKeys->DefaultPrim, VtValue(name));
}

ValueOutputs NewLayerZoneOutputs(const SdfLayerHandle& layer) {
  NewLayerZoneEndOutputs outputs;
  outputs.layer = layer;
  return WriteNewLayerZoneEndOutputs(outputs);
}

}  // namespace proscenium
