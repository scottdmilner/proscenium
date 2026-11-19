// The node definitions, loaded through Sdf from the package's node_definitions.usda (docs/phase3/node-tree.md "Node
// definitions"): each node type's version and its inputs, outputs, and properties, with their types, defaults, menus,
// and the socket facts USD's types can't hold. Behavior is never in the definitions, only in the node registry.
#pragma once

#include <pxr/base/tf/token.h>
#include <pxr/base/vt/array.h>
#include <pxr/base/vt/types.h>
#include <pxr/base/vt/value.h>
#include <pxr/pxr.h>
#include <pxr/usd/sdf/valueTypeName.h>

#include <cstdint>
#include <string>
#include <unordered_map>
#include <vector>

namespace proscenium {

// What a socket carries. A value socket or property carries its USD value type; the others are the note's sockets.
enum class SocketKind : std::uint8_t { kValue, kLayer, kEditableLayer, kFile, kPrim, kPrims };

// The name a definition's customData gives the kind, such as "EditableLayer"; "Value" for kValue.
const char* SocketKindName(SocketKind kind);

// Which of a node's attributes it is, by its namespace: an input or output socket (inputs:, outputs:), or a property
// (props:).
enum class AttributeRole : std::uint8_t { kInput, kOutput, kProperty };

// One attribute of a node type's definition: an input, output, or property.
struct AttributeDefinition {
  PXR_NS::TfToken attributeName;  // the attribute's full name, such as inputs:layer
  AttributeRole role = AttributeRole::kInput;
  SocketKind kind = SocketKind::kValue;
  PXR_NS::SdfValueTypeName valueType;  // the attribute's type: opaque for a layer, string for a file or a path
  PXR_NS::VtValue defaultValue;        // empty when the definition authors none
  PXR_NS::VtTokenArray allowedTokens;  // a menu's items; empty for none
  bool multiInput = false;             // takes several links, in connection order
  bool optional = false;               // unauthored unless set: read as an AuthoredField
  bool dynamicType = false;            // its type follows another property: read as a VtValue
  PXR_NS::TfToken mutePassThrough;     // for an output: the input a muted node passes through it; empty for none
};

// Which end of a zone a node type is, from its definition's customData zone; kNone for a node that isn't one.
enum class ZoneEdge : std::uint8_t { kNone, kBegin, kEnd };

// One node type's definition.
struct NodeDefinition {
  PXR_NS::TfToken typeName;  // the class prim's name, and the type name of the type's prims in a tree
  int version = 0;           // its node:version, the newest a tree may author
  std::string doc;
  ZoneEdge zone = ZoneEdge::kNone;
  PXR_NS::TfToken zonePartner;                  // a zone node's: the other end's type; empty for kNone
  std::vector<AttributeDefinition> attributes;  // in the order the definition authors them

  // The attribute with this name, or null when the type has none.
  [[nodiscard]] const AttributeDefinition* FindAttribute(const PXR_NS::TfToken& attributeName) const;

  // The node's Editable Layer input or output, the link its chain follows; null when it has none.
  [[nodiscard]] const AttributeDefinition* EditableLayer(AttributeRole role) const;
};

// Every node type's definition, keyed by type name.
class NodeDefinitions {
 public:
  // Loads the definitions file at path. Throws std::invalid_argument, naming every problem, when the file can't be
  // read, a definition is malformed, or the definitions and the node registry don't name the same node types.
  explicit NodeDefinitions(const std::string& path);

  // The type's definition, or null for a type the definitions don't hold.
  [[nodiscard]] const NodeDefinition* Find(const PXR_NS::TfToken& typeName) const;

  [[nodiscard]] std::vector<PXR_NS::TfToken> TypeNames() const;  // sorted

 private:
  std::unordered_map<PXR_NS::TfToken, NodeDefinition, PXR_NS::TfToken::HashFunctor> definitions_;
};

}  // namespace proscenium
