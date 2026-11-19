// New Layer Zone's begin and end, in one file since each is half of one zone (docs/phase3/node-tree.md "New Layer
// Zone"). The begin names the file Write saves the zone's layer to and the Template the zone starts from, and the end
// gives the finished layer out. The zone's chain, its task, its layer, and the Template's copy are the machinery's
// (zone_chains.h, tree_cook.cpp, layer_copies.h).
#include <pxr/base/tf/token.h>
#include <pxr/usd/ar/resolver.h>
#include <pxr/usd/sdf/layer.h>

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

ValueOutputs NewLayerZoneOutputs(const SdfLayerHandle& layer) {
  NewLayerZoneEndOutputs outputs;
  outputs.layer = layer;
  return WriteNewLayerZoneEndOutputs(outputs);
}

}  // namespace proscenium
