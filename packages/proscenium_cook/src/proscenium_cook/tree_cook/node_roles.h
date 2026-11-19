// The four roles a node type plays, each with its own function signature, so a node can do only what its role allows
// (docs/plans/cook-module.md "Node types in C++"). A node type is a registered function, and keeps no state of its
// own: what it keeps between cooks, it keeps through its context's Cache.
#pragma once

#include <pxr/base/tf/hash.h>
#include <pxr/base/tf/token.h>
#include <pxr/base/vt/value.h>
#include <pxr/pxr.h>
#include <pxr/usd/sdf/layer.h>

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

// One step of a zone's chain: it reads the zone's stage and authors into its scratch layer. Its value outputs are
// computed from its inputs and properties alone.
struct AuthoringRole {
  void (*author)(AuthoringContext& context) = nullptr;
};

// The file a zone's layer is saved to, and the attribute that names it.
struct ZoneFile {
  std::string identifier;  // as USD's resolver identifies a new file; empty for none
  PXR_NS::TfToken attributeName;
};

// A zone's begin or end, paired by its definition's zone and zonePartner: hooks the task machinery calls, each null for
// a type that needs none. Most of a zone's behavior is the machinery's own: its chain (zone_chains.h), its task, and
// its layer (tree_cook.cpp).
struct ZoneRole {
  // A begin's: the file Write saves its zone's layer to. A problem with it is the begin's error, which stops its zone.
  ZoneFile (*file)(const NodeContext& context) = nullptr;
  // An end's: its outputs, given its zone's finished layer.
  ValueOutputs (*outputs)(const PXR_NS::SdfLayerHandle& layer) = nullptr;
};

// Layer from File, Stage Output, and Viewer: a task of its own, outside any chain.
struct TaskRole {
  void (*run)(TaskContext& context) = nullptr;
};

using NodeBehavior = std::variant<ValueRole, AuthoringRole, ZoneRole, TaskRole>;

}  // namespace proscenium
