#include "node_contexts.h"

#include <pxr/base/tf/stringUtils.h>
#include <pxr/usd/sdf/attributeSpec.h>

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

}  // namespace proscenium
