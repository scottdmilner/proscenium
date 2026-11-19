#include "node_contexts.h"

#include <pxr/base/tf/errorMark.h>
#include <pxr/base/tf/stringUtils.h>
#include <pxr/usd/sdf/attributeSpec.h>
#include <pxr/usd/sdf/primSpec.h>

PXR_NAMESPACE_USING_DIRECTIVE

namespace proscenium {

VtValue TreeInputReader::Read(const TfToken& attributeName) const {
  const std::vector<OutputRef> sources = graph_.Sources(node_, attributeName);
  if (!sources.empty()) return valueOf_(sources.front());
  const TreeNode& node = tree_.nodes[node_];
  // A linked input whose links bring no value, because each leads to a node that failed, can't run, or is muted with
  // no pass-through, stays empty: a link overrides the authored value and the default.
  const bool linked = node.links.find(attributeName) != node.links.end();
  if (linked) return {};
  if (const SdfAttributeSpecHandle attribute = node.spec->GetAttributes().get(attributeName);
      attribute && attribute->HasDefaultValue()) {
    return attribute->GetDefaultValue();
  }
  const AttributeDefinition* attributeDefinition =
      node.definition ? node.definition->FindAttribute(attributeName) : nullptr;
  return attributeDefinition ? attributeDefinition->defaultValue : VtValue();
}

std::vector<VtValue> TreeInputReader::ReadAll(const TfToken& attributeName) const {
  std::vector<VtValue> values;
  for (const OutputRef& source : graph_.Sources(node_, attributeName)) values.push_back(valueOf_(source));
  return values;
}

bool TreeInputReader::IsAuthored(const TfToken& attributeName) const {
  const SdfAttributeSpecHandle attribute = tree_.nodes[node_].spec->GetAttributes().get(attributeName);
  return attribute && attribute->HasDefaultValue();
}

std::optional<std::string> NodeContext::ExpandPath(const std::string& path, const TfToken& attributeName) const {
  if (TfStringStartsWith(path, "//")) {
    if (baseDirectory_.empty()) {
      ReportError(DiagnosticCode::kMissingBaseDirectory,
                  "\"" + path + "\" is relative to the .blend: save the .blend to give it a directory",
                  AttributePath(attributeName));
      return std::nullopt;
    }
    return TfStringCatPaths(baseDirectory_, path.substr(2));
  }
  // A bare relative path, such as base.usda, isn't warned of: it may be an identifier a custom resolver reads.
  if (TfStringStartsWith(path, "./") || TfStringStartsWith(path, "../") || TfStringStartsWith(path, ".\\") ||
      TfStringStartsWith(path, "..\\")) {
    ReportWarning(
        DiagnosticCode::kWorkingDirectoryPath,
        "\"" + path + "\" resolves against the working directory, not the .blend's: start it with // for that",
        AttributePath(attributeName));
  }
  return path;
}

bool AuthoringContext::HasPrimSpec(const SdfPath& path) const { return static_cast<bool>(layer_->GetPrimAtPath(path)); }

std::optional<SdfSpecifier> AuthoringContext::PrimSpecifier(const SdfPath& path) const {
  const SdfPrimSpecHandle prim = layer_->GetPrimAtPath(path);
  if (!prim) return std::nullopt;
  return prim->GetSpecifier();
}

const EditAuthor* AuthoringContext::PrimSpecAuthor(const SdfPath& path) const {
  const auto found = edits_.primSpecs.find(path);
  return found == edits_.primSpecs.end() ? nullptr : &found->second;
}

void AuthoringContext::CreatePrimSpec(const SdfPath& path, SdfSpecifier specifier, const TfToken& typeName) {
  // Each missing ancestor, root first, becomes an over, as SdfCreatePrimInLayer makes it, and is this node's.
  SdfPathVector missing;
  for (SdfPath ancestor = path.GetParentPath(); ancestor.IsPrimPath() && !HasPrimSpec(ancestor);
       ancestor = ancestor.GetParentPath()) {
    missing.push_back(ancestor);
  }
  const SdfPrimSpecHandle prim = SdfCreatePrimInLayer(layer_, path);
  // Each ancestor it made is recorded, even when it fails partway, so every spec the layer holds has its entry.
  for (const SdfPath& ancestor : missing) {
    if (HasPrimSpec(ancestor)) edits_.primSpecs[ancestor] = {NodeId(), EditKind::kMissingAncestor};
  }
  if (!prim) return;  // its Tf error is the node's
  prim->SetSpecifier(specifier);
  if (!typeName.IsEmpty()) prim->SetTypeName(typeName.GetString());
  edits_.primSpecs[path] = {NodeId()};
}

void AuthoringContext::SetLayerField(const TfToken& field, const VtValue& value) {
  // A field Sdf refuses posts a Tf error, which stays posted as the node's own, and isn't recorded.
  const TfErrorMark mark;
  layer_->SetField(SdfPath::AbsoluteRootPath(), field, value);
  if (mark.IsClean()) edits_.layerFields[field] = {NodeId()};
}

}  // namespace proscenium
