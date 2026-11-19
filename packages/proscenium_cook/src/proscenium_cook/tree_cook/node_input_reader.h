// What the generated input readers in nodes/*_attributes.h read a node's inputs and properties through: each one's
// value from its link, its authored value, or its definition's default, so defaults are applied once, here. The shared
// checks have already compared every authored value with its definition, so a read returns the definition's type.
#pragma once

#include <pxr/base/tf/token.h>
#include <pxr/base/vt/value.h>
#include <pxr/pxr.h>
#include <pxr/usd/sdf/layer.h>
#include <pxr/usd/sdf/path.h>
#include <pxr/usd/sdf/pathExpression.h>

#include <optional>
#include <string>
#include <utility>
#include <vector>

namespace proscenium {

// A field that is unauthored unless set (docs/phase3/node-tree.md "Nodes"): unauthored differs from its fallback,
// since leaving it unauthored lets a weaker layer's opinion through.
template <class T>
class AuthoredField {
 public:
  AuthoredField() = default;
  explicit AuthoredField(T value) : value_(std::move(value)) {}

  [[nodiscard]] bool IsAuthored() const { return value_.has_value(); }
  [[nodiscard]] const T& Get() const { return *value_; }  // only when authored

 private:
  std::optional<T> value_;
};

// A Layer input: the finished layer its link brings, or null when it's unlinked or its upstream produced none.
struct LayerInput {
  PXR_NS::SdfLayerHandle layer;
};

// A File input: the identifier composition resolved for the file a Substitution Zone's item stands for, or the path
// typed into an unlinked input.
struct FileInput {
  std::string identifier;
};

class NodeInputReader {
 public:
  NodeInputReader() = default;
  NodeInputReader(const NodeInputReader&) = delete;
  NodeInputReader& operator=(const NodeInputReader&) = delete;
  NodeInputReader(NodeInputReader&&) = delete;
  NodeInputReader& operator=(NodeInputReader&&) = delete;
  virtual ~NodeInputReader() = default;

  // A value socket or property, converted as a link converts it; T's default when nothing provides one.
  template <class T>
  [[nodiscard]] T Value(const char* attributeName) const {
    const PXR_NS::VtValue value = Read(PXR_NS::TfToken(attributeName)).template Cast<T>();
    return value.IsHolding<T>() ? value.UncheckedGet<T>() : T{};
  }

  // An optional property: unauthored unless the node authors it.
  template <class T>
  [[nodiscard]] AuthoredField<T> Optional(const char* attributeName) const {
    const PXR_NS::TfToken name(attributeName);
    if (!IsAuthored(name)) return {};
    return AuthoredField<T>(Value<T>(attributeName));
  }

  // A value whose type follows another property, which the node checks itself.
  [[nodiscard]] PXR_NS::VtValue Dynamic(const char* attributeName) const {
    return Read(PXR_NS::TfToken(attributeName));
  }

  // A Prim input's path; empty when it's empty or not a path.
  [[nodiscard]] PXR_NS::SdfPath Prim(const char* attributeName) const;

  // A Prims input's expression, a Prim converting to a single-path expression; empty when it doesn't parse.
  [[nodiscard]] PXR_NS::SdfPathExpression Prims(const char* attributeName) const;

  [[nodiscard]] LayerInput Layer(const char* attributeName) const;
  [[nodiscard]] std::vector<LayerInput> Layers(const char* attributeName) const;  // a multi-input, in connection order
  [[nodiscard]] FileInput File(const char* attributeName) const;

 protected:
  // The attribute's value: its link's, its authored one, or its definition's default; empty when none of them exists. A
  // Layer input's value holds an SdfLayerHandle, and a File, Prim, or Prims input's a string.
  [[nodiscard]] virtual PXR_NS::VtValue Read(const PXR_NS::TfToken& attributeName) const = 0;

  // A multi-input's values, one per link, in connection order.
  [[nodiscard]] virtual std::vector<PXR_NS::VtValue> ReadAll(const PXR_NS::TfToken& attributeName) const = 0;

  // Whether the node authors the attribute's value.
  [[nodiscard]] virtual bool IsAuthored(const PXR_NS::TfToken& attributeName) const = 0;
};

}  // namespace proscenium
