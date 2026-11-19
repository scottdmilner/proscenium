#include "node_input_reader.h"

#include <pxr/base/tf/errorMark.h>

PXR_NAMESPACE_USING_DIRECTIVE

namespace proscenium {
namespace {

std::string StringOf(const VtValue& value) {
  return value.IsHolding<std::string>() ? value.UncheckedGet<std::string>() : "";
}

LayerInput LayerOf(const VtValue& value) {
  return {value.IsHolding<SdfLayerHandle>() ? value.UncheckedGet<SdfLayerHandle>() : SdfLayerHandle()};
}

}  // namespace

SdfPath NodeInputReader::Prim(const char* attributeName) const {
  const std::string text = StringOf(Read(TfToken(attributeName)));
  if (text.empty() || !SdfPath::IsValidPathString(text)) return {};
  return SdfPath(text);
}

SdfPathExpression NodeInputReader::Prims(const char* attributeName) const {
  const std::string text = StringOf(Read(TfToken(attributeName)));
  if (text.empty()) return {};
  // The shared checks report an authored expression that doesn't parse (invalid-prims-expression), so the reader
  // doesn't post its errors again.
  const TfErrorMark mark;
  SdfPathExpression expression(text);
  mark.Clear();
  return expression;
}

LayerInput NodeInputReader::Layer(const char* attributeName) const { return LayerOf(Read(TfToken(attributeName))); }

std::vector<LayerInput> NodeInputReader::Layers(const char* attributeName) const {
  std::vector<LayerInput> layers;
  for (const VtValue& value : ReadAll(TfToken(attributeName))) layers.push_back(LayerOf(value));
  return layers;
}

FileInput NodeInputReader::File(const char* attributeName) const { return {StringOf(Read(TfToken(attributeName)))}; }

}  // namespace proscenium
