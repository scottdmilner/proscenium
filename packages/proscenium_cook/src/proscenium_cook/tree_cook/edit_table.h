// A zone layer's edit table: the node that last wrote each item the layer holds (docs/phase3/node-tree.md
// "Provenance"). Inspection shows which node authored a value from it, verification looks up its entries, and a
// composition error maps to the node that authored the arc through it. It's built while the zone's chain authors, kept
// beside the zone's layer as its write table is, and never stored in the layer. It holds prim specs and layer metadata
// fields so far; property values, prim fields, and list-op items join it with the nodes that author them.
#pragma once

#include <pxr/base/tf/token.h>
#include <pxr/pxr.h>
#include <pxr/usd/sdf/path.h>

#include <cstdint>
#include <map>
#include <string>

namespace proscenium {

// How a node came to write an entry.
enum class EditKind : std::uint8_t {
  kAuthored,         // the node authored it
  kTemplate,         // the begin copied it from its zone's Template
  kMissingAncestor,  // an over the node authored for an ancestor its layer lacked, which a later Create Prim may take
};

// Who last wrote an entry, and how.
struct EditAuthor {
  std::string nodeId;
  EditKind kind = EditKind::kAuthored;
};

struct EditTable {
  // By prim path as authored, so a spec inside a variant is at /A{look=red}Child. Template content is the zone's begin
  // node's, and an implicit over for a missing ancestor is the node's that needed it until a node creates that prim.
  std::map<PXR_NS::SdfPath, EditAuthor> primSpecs;
  // By layer metadata field, such as defaultPrim; a list field's items get entries of their own with the first node
  // that edits one, Sublayer (step 12 of the plan).
  std::map<PXR_NS::TfToken, EditAuthor> layerFields;
};

}  // namespace proscenium
