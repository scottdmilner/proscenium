// Node IDs, which are Blender's node names, and the prim names they map to reversibly (docs/phase3/node-tree.md "The
// tree as plain data"): each `_` doubles to `__`, and each character USD's identifiers reject there, a leading digit
// among them, becomes `_<hex codepoint>_`. A single `_` always starts an escape, so decoding is unambiguous.
#pragma once

#include <optional>
#include <string>

namespace proscenium {

// The prim name a node ID maps to.
std::string PrimNameFromNodeId(const std::string& nodeId);

// The node ID a prim name maps from, or none when the name isn't one PrimNameFromNodeId gives: a bad escape, or an
// escape where no character needs one, which would let two prim names stand for one node.
std::optional<std::string> NodeIdFromPrimName(const std::string& primName);

}  // namespace proscenium
