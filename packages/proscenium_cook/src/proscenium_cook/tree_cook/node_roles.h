// The four roles a node type plays, each with its own function signature, so a node can do only what its role allows
// (docs/plans/cook-module.md "Node types in C++"). A node type is a registered function, and keeps no state of its
// own: what it keeps between cooks, it keeps through its context's Cache.
#pragma once

#include <pxr/base/tf/hash.h>
#include <pxr/base/tf/token.h>
#include <pxr/base/vt/value.h>
#include <pxr/pxr.h>
#include <pxr/usd/sdf/layer.h>

#include <optional>
#include <string>
#include <unordered_map>
#include <variant>

namespace proscenium {

class NodeContext;
class ValueInputs;
class AuthoringContext;
class TaskContext;

// A value node's outputs, by output attribute name.
using ValueOutputs = std::unordered_map<PXR_NS::TfToken, PXR_NS::VtValue, PXR_NS::TfToken::HashFunctor>;

// Prim, Match Prims, Value, and Convert: inputs in, outputs returned. It gets no stage and no layer, so it's pure
// because of its signature.
struct ValueRole {
  ValueOutputs (*compute)(const ValueInputs& inputs) = nullptr;
};

// One step of a zone's chain: it reads the zone's stage and authors into its scratch layer.
struct AuthoringRole {
  void (*author)(AuthoringContext& context) = nullptr;
  // Its outputs other than its Editable Layer, such as Create Prim's Prim, computed from its inputs and properties
  // alone, with the value nodes, before any task runs; null for a type with none. It gets no stage, so a value it
  // gives another zone never waits on its own zone's task (docs/plans/cook-module.md "Edges between tasks").
  ValueOutputs (*outputs)(const ValueInputs& inputs) = nullptr;
};

// The file a node saves a layer to or reads one from, and the attribute that names it. No other zone saves to a zone's
// file, and nothing in the tree reads it (docs/phase3/node-tree.md "Writing").
struct NodeFile {
  std::string identifier;  // as USD's resolver identifies it; empty for none
  PXR_NS::TfToken attributeName;
};

// A zone's begin or end, paired by its definition's zone and zonePartner: hooks the task machinery calls, each null for
// a type that needs none. Most of a zone's behavior is the machinery's own: its chain (zone_chains.h), its task, and
// its layer (tree_cook.cpp).
struct ZoneRole {
  // A begin's: the file Write saves its zone's layer to. A problem with it is the begin's error, which stops its zone.
  NodeFile (*file)(const NodeContext& context) = nullptr;
  // A begin's: the layer its zone starts as a copy of, or none for an empty start. A null layer is a start whose link
  // brings nothing, which stops the zone. The machinery makes the copy (layer_copies.h).
  std::optional<PXR_NS::SdfLayerHandle> (*startsFrom)(const NodeContext& context) = nullptr;
  // An end's: what it authors once its zone's chain has run, such as a New Layer Zone's defaultPrim, before the
  // scratch layer moves into the zone's layer. An error it reports stops the zone.
  void (*finish)(AuthoringContext& context) = nullptr;
  // An end's: its outputs, given its zone's finished layer.
  ValueOutputs (*outputs)(const PXR_NS::SdfLayerHandle& layer) = nullptr;
};

// Layer from File, Stage Output, and Viewer: a task of its own, outside any chain.
struct TaskRole {
  void (*run)(TaskContext& context) = nullptr;
  // A task's that reads a file: the file it reads, before any task runs, so a zone saving to it is an error first. Its
  // run reports any problem with the file, so the cook discards what this reports.
  NodeFile (*file)(const NodeContext& context) = nullptr;
};

using NodeBehavior = std::variant<ValueRole, AuthoringRole, ZoneRole, TaskRole>;

}  // namespace proscenium
