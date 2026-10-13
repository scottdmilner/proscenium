// Constant primvars as Blender ID properties on each object, named as the primvar, so shaders read them with
// an Attribute node of type Object.
#pragma once

#include <pxr/pxr.h>
#include <pxr/base/vt/value.h>

#include <cstddef>
#include <optional>
#include <string>

namespace hydra_bridge {

// What Blender's ID properties hold: a bool, int, double, or std::string, or a VtBoolArray, VtIntArray,
// VtDoubleArray, or VtStringArray. `tupleSize` > 0 when the array holds tuples of that size (an array of
// vectors, or a matrix's rows), which Blender keeps as nested arrays.
struct PropertyValue {
    pxr::VtValue value;
    size_t tupleSize = 0;
};

// nullopt, with the reason in `why`, for a value Blender can't hold: a type with no ID-property form, or an
// array of matrices. Integers outside 32 bits keep their low 32 bits, best effort, with the loss in `warning`.
// A one-element array becomes its element, as USD's constant primvars are conventionally authored
// (displayColor = [(r, g, b)]).
std::optional<PropertyValue> ToProperty(const pxr::VtValue &value, std::string &why, std::string &warning);

// Blender limits ID-property names to 63 bytes, and the bridge's own properties use the proscenium_ prefix.
bool PropertyNameUsable(const std::string &name, std::string &why);

}  // namespace hydra_bridge
