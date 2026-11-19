#include "node_definitions.h"

#include <pxr/base/tf/stringUtils.h>
#include <pxr/base/vt/dictionary.h>
#include <pxr/usd/sdf/attributeSpec.h>
#include <pxr/usd/sdf/layer.h>
#include <pxr/usd/sdf/primSpec.h>
#include <pxr/usd/sdf/schema.h>
#include <pxr/usd/sdf/types.h>

#include <algorithm>
#include <array>
#include <optional>
#include <set>
#include <stdexcept>
#include <utility>

#include "nodes/node_registry.h"

PXR_NAMESPACE_USING_DIRECTIVE

namespace proscenium {
namespace {

const TfToken& NodeVersionName() {
  static const TfToken name("node:version");
  return name;
}

struct SocketKindSpelling {
  SocketKind kind;
  const char* name;
};

constexpr std::array kSocketKindNames{
    SocketKindSpelling{SocketKind::kValue, "Value"},
    SocketKindSpelling{SocketKind::kLayer, "Layer"},
    SocketKindSpelling{SocketKind::kEditableLayer, "EditableLayer"},
    SocketKindSpelling{SocketKind::kFile, "File"},
    SocketKindSpelling{SocketKind::kPrim, "Prim"},
    SocketKindSpelling{SocketKind::kPrims, "Prims"},
};

// The kind a definition's customData names; the value kind is never named, so it isn't found.
std::optional<SocketKind> FindSocketKind(const std::string& name) {
  for (const auto& spelling : kSocketKindNames) {
    if (spelling.kind != SocketKind::kValue && name == spelling.name) return spelling.kind;
  }
  return std::nullopt;
}

std::optional<AttributeRole> FindAttributeRole(const std::string& attributeName) {
  if (TfStringStartsWith(attributeName, "inputs:")) return AttributeRole::kInput;
  if (TfStringStartsWith(attributeName, "outputs:")) return AttributeRole::kOutput;
  if (TfStringStartsWith(attributeName, "props:")) return AttributeRole::kProperty;
  return std::nullopt;
}

// A customData flag, false when unauthored; a value of another type is a problem.
bool ReadFlag(const VtDictionary& customData, const char* key, const std::string& where,
              std::vector<std::string>& problems) {
  const auto found = customData.find(key);
  if (found == customData.end()) return false;
  if (!found->second.IsHolding<bool>()) {
    problems.push_back(where + ": customData " + key + " must be a bool");
    return false;
  }
  return found->second.UncheckedGet<bool>();
}

std::string ReadString(const VtDictionary& customData, const char* key, const std::string& where,
                       std::vector<std::string>& problems) {
  const auto found = customData.find(key);
  if (found == customData.end()) return {};
  if (!found->second.IsHolding<std::string>()) {
    problems.push_back(where + ": customData " + key + " must be a string");
    return {};
  }
  return found->second.UncheckedGet<std::string>();
}

// The type a socket kind's attribute must have: opaque for a layer, string for a file or a path.
SdfValueTypeName RequiredType(SocketKind kind) {
  switch (kind) {
    case SocketKind::kLayer:
    case SocketKind::kEditableLayer:
      return SdfValueTypeNames->Opaque;
    case SocketKind::kFile:
    case SocketKind::kPrim:
    case SocketKind::kPrims:
      return SdfValueTypeNames->String;
    case SocketKind::kValue:
      break;
  }
  return {};
}

AttributeDefinition ReadAttributeDefinition(const SdfAttributeSpecHandle& attribute, AttributeRole role,
                                            const std::string& where, std::vector<std::string>& problems) {
  AttributeDefinition attributeDefinition;
  attributeDefinition.attributeName = attribute->GetNameToken();
  attributeDefinition.role = role;
  attributeDefinition.valueType = attribute->GetTypeName();
  attributeDefinition.defaultValue = attribute->GetDefaultValue();
  attributeDefinition.allowedTokens = attribute->GetAllowedTokens();
  const VtDictionary customData = attribute->GetCustomData();
  const std::string socket = ReadString(customData, "socket", where, problems);
  if (!socket.empty()) {
    const auto kind = FindSocketKind(socket);
    if (kind) {
      attributeDefinition.kind = *kind;
    } else {
      problems.push_back(where + ": unknown socket kind \"" + socket + "\"");
    }
  }
  if (const SdfValueTypeName required = RequiredType(attributeDefinition.kind);
      required && attributeDefinition.valueType != required) {
    problems.push_back(where + ": a " + SocketKindName(attributeDefinition.kind) + " socket must be " +
                       required.GetAsToken().GetString());
  }
  if (attributeDefinition.kind == SocketKind::kValue && attributeDefinition.valueType == SdfValueTypeNames->Opaque) {
    problems.push_back(where + ": an opaque attribute must name its socket kind");
  }
  attributeDefinition.multiInput = ReadFlag(customData, "multiInput", where, problems);
  attributeDefinition.optional = ReadFlag(customData, "optional", where, problems);
  attributeDefinition.dynamicType = ReadFlag(customData, "dynamicType", where, problems);
  attributeDefinition.mutePassThrough = TfToken(ReadString(customData, "mutePassThrough", where, problems));
  if (attributeDefinition.multiInput &&
      (role != AttributeRole::kInput || attributeDefinition.kind != SocketKind::kLayer)) {
    problems.push_back(where + ": only a Layer input takes several links");
  }
  if (attributeDefinition.optional && role != AttributeRole::kProperty) {
    problems.push_back(where + ": only a property is optional, since an input's link would set it");
  }
  if (!attributeDefinition.mutePassThrough.IsEmpty() && role != AttributeRole::kOutput) {
    problems.push_back(where + ": only an output passes an input through");
  }
  return attributeDefinition;
}

// Every mutePassThrough names an input of its output's kind and type.
void CheckPassThroughs(const NodeDefinition& definition, std::vector<std::string>& problems) {
  for (const AttributeDefinition& output : definition.attributes) {
    if (output.mutePassThrough.IsEmpty()) continue;
    const AttributeDefinition* input = definition.FindAttribute(output.mutePassThrough);
    const std::string where = definition.typeName.GetString() + "." + output.attributeName.GetString();
    if (input == nullptr || input->role != AttributeRole::kInput) {
      problems.push_back(where + ": mutePassThrough names no input, " + output.mutePassThrough.GetString());
    } else if (input->kind != output.kind || input->valueType != output.valueType) {
      problems.push_back(where + ": mutePassThrough names an input of another kind or type");
    }
  }
}

NodeDefinition ReadDefinition(const SdfPrimSpecHandle& prim, std::vector<std::string>& problems) {
  NodeDefinition definition;
  definition.typeName = prim->GetNameToken();
  definition.doc = prim->GetDocumentation();
  const std::string& type = definition.typeName.GetString();
  if (prim->GetSpecifier() != SdfSpecifierClass) problems.push_back(type + ": a definition must be a class prim");
  if (!prim->GetNameChildren().empty()) problems.push_back(type + ": a definition holds no prims");
  for (const SdfPropertySpecHandle& property : prim->GetProperties()) {
    const std::string where = type + "." + property->GetName();
    const SdfAttributeSpecHandle attribute = TfDynamic_cast<SdfAttributeSpecHandle>(property);
    if (!attribute) {
      problems.push_back(where + ": a definition holds only attributes");
      continue;
    }
    if (attribute->GetNameToken() == NodeVersionName()) {
      const VtValue version = attribute->GetDefaultValue();
      if (version.IsHolding<int>() && version.UncheckedGet<int>() >= 1) {
        definition.version = version.UncheckedGet<int>();
      }
      continue;
    }
    const auto role = FindAttributeRole(attribute->GetName());
    if (!role) {
      problems.push_back(where + ": not an inputs:, outputs:, or props: attribute");
      continue;
    }
    definition.attributes.push_back(ReadAttributeDefinition(attribute, *role, where, problems));
  }
  if (definition.version == 0) problems.push_back(type + ": node:version must be an int of at least 1");
  CheckPassThroughs(definition, problems);
  return definition;
}

}  // namespace

const char* SocketKindName(SocketKind kind) {
  for (const auto& spelling : kSocketKindNames) {
    if (spelling.kind == kind) return spelling.name;
  }
  return "";
}

const AttributeDefinition* NodeDefinition::FindAttribute(const TfToken& attributeName) const {
  const auto found =
      std::find_if(attributes.begin(), attributes.end(), [&](const AttributeDefinition& attributeDefinition) {
        return attributeDefinition.attributeName == attributeName;
      });
  return found == attributes.end() ? nullptr : &*found;
}

NodeDefinitions::NodeDefinitions(const std::string& path) {
  const SdfLayerRefPtr layer = SdfLayer::FindOrOpen(path);
  if (!layer) throw std::invalid_argument("Can't read the node definitions file " + path);
  std::vector<std::string> problems;
  for (const SdfPrimSpecHandle& prim : layer->GetRootPrims()) {
    NodeDefinition definition = ReadDefinition(prim, problems);
    definitions_.emplace(definition.typeName, std::move(definition));
  }
  std::set<std::string> registered;
  for (const NodeRegistration& registration : NodeRegistry()) registered.insert(registration.typeName);
  for (const auto& [typeName, definition] : definitions_) {
    if (registered.count(typeName.GetString()) == 0) problems.push_back(typeName.GetString() + ": no implementation");
  }
  for (const std::string& typeName : registered) {
    if (definitions_.count(TfToken(typeName)) == 0) problems.push_back(typeName + ": no definition");
  }
  if (!problems.empty()) {
    std::sort(problems.begin(), problems.end());
    throw std::invalid_argument("The node definitions in " + path + " are malformed:\n" +
                                TfStringJoin(problems.begin(), problems.end(), "\n"));
  }
}

const NodeDefinition* NodeDefinitions::Find(const TfToken& typeName) const {
  const auto found = definitions_.find(typeName);
  return found == definitions_.end() ? nullptr : &found->second;
}

std::vector<TfToken> NodeDefinitions::TypeNames() const {
  std::vector<TfToken> names;
  names.reserve(definitions_.size());
  for (const auto& [typeName, definition] : definitions_) names.push_back(typeName);
  std::sort(names.begin(), names.end(),
            [](const TfToken& a, const TfToken& b) { return a.GetString() < b.GetString(); });
  return names;
}

}  // namespace proscenium
