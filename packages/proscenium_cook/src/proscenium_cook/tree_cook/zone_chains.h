// The tree's zones: each begin paired with the end its zone:end names, and its chain, found by following Editable Layer
// links forward from the begin (docs/phase3/node-tree.md "What a zone holds"). Finding them reports the errors that
// follow from the chains, each on the node it concerns, and a node given one can't run.
#pragma once

#include <cstddef>
#include <optional>
#include <vector>

#include "cook_diagnostics.h"
#include "tree_reading.h"

namespace proscenium {

// One begin's zone, by node index.
struct Zone {
  std::size_t begin = 0;
  std::optional<std::size_t> end;  // the end its begin pairs with, when they pair
  // The nodes after the begin, in chain order, up to its end or the chain's break; the end isn't one of them.
  std::vector<std::size_t> chain;
  bool reachesEnd = false;  // whether the chain reaches the zone's own end
};

// Every begin's zone, in node-ID order, reporting:
// - a begin whose zone:end names no end of its zone, or an end another begin's zone:end names too, and an end that no
//   one begin names (unpaired-zone);
// - an Editable Layer output linked to more than one input (chain-branch);
// - an end its begin's chain doesn't reach (broken-chain), with a warning on each node of that chain, whose edits never
//   reach it (unreached-zone-end);
// - an end another begin's chain reaches (mismatched-zone);
// - an authoring node whose Editable Layer doesn't trace back to a begin (no-chain). The nodes after it, and the nodes
//   after a branch, pass nothing on, and report nothing.
// An end whose begin is on a cycle warns that its zone gets nothing from it (no-upstream-value).
// Nodes on a cycle take no part, since each has its error already. Needs NodeGraph to have marked them.
std::vector<Zone> FindZones(TreeNodes& tree, CookDiagnostics& diagnostics);

}  // namespace proscenium
