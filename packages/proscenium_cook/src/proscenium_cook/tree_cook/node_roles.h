// The four roles a node type plays, each with its own function signature, so a node can do only what its role allows
// (docs/plans/cook-module.md "Node types in C++"). A node type is a registered function, and keeps no state of its
// own: what it keeps between cooks, it keeps through its context's Cache.
#pragma once

#include <pxr/base/tf/hash.h>
#include <pxr/base/tf/token.h>
#include <pxr/base/vt/value.h>
#include <pxr/pxr.h>

#include <unordered_map>
#include <variant>

namespace proscenium {

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

// New Layer Zone, Variant Zone, and Substitution Zone: hooks the task machinery calls. Their hooks arrive with the
// first zone, step 6 of the plan.
struct ZoneRole {};

// Layer from File, Stage Output, and Viewer: a task of its own, outside any chain.
struct TaskRole {
  void (*run)(TaskContext& context) = nullptr;
};

using NodeBehavior = std::variant<ValueRole, AuthoringRole, ZoneRole, TaskRole>;

}  // namespace proscenium
