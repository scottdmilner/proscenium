#include "properties.h"

#include <pxr/base/gf/half.h>
#include <pxr/base/gf/matrix2d.h>
#include <pxr/base/gf/matrix2f.h>
#include <pxr/base/gf/matrix3d.h>
#include <pxr/base/gf/matrix3f.h>
#include <pxr/base/gf/matrix4d.h>
#include <pxr/base/gf/matrix4f.h>
#include <pxr/base/gf/vec2d.h>
#include <pxr/base/gf/vec2f.h>
#include <pxr/base/gf/vec2h.h>
#include <pxr/base/gf/vec2i.h>
#include <pxr/base/gf/vec3d.h>
#include <pxr/base/gf/vec3f.h>
#include <pxr/base/gf/vec3h.h>
#include <pxr/base/gf/vec3i.h>
#include <pxr/base/gf/vec4d.h>
#include <pxr/base/gf/vec4f.h>
#include <pxr/base/gf/vec4h.h>
#include <pxr/base/gf/vec4i.h>
#include <pxr/base/tf/stringUtils.h>
#include <pxr/base/tf/token.h>
#include <pxr/base/vt/array.h>
#include <pxr/base/vt/types.h>

#include <cstdint>
#include <limits>

PXR_NAMESPACE_USING_DIRECTIVE

namespace hydra_bridge {

namespace {

enum class Kind { None, Bool, Int, Float, String };

// A value's elements, flattened, all of one kind.
struct Flat {
    Kind kind = Kind::None;
    VtBoolArray bools;
    VtIntArray ints;
    VtDoubleArray doubles;
    VtStringArray strings;
    size_t tuple = 0;     // elements per vector or matrix row
    bool matrix = false;  // the elements are matrix rows
    std::string why;      // set when an element can't be held
    bool narrowed = false;  // an integer was wrapped to 32 bits
};

void Add(Flat &flat, bool value) {
    flat.kind = Kind::Bool;
    flat.bools.push_back(value);
}

// Blender's integer ID properties are 32-bit: a wider value keeps its low 32 bits, two's complement, best
// effort (as a C cast does), and the caller warns.
template <class Integer>
void AddInteger(Flat &flat, Integer value) {
    // Through uint32_t, whose wrap is defined; uint32_t to int32_t wraps on every compiler the bridge builds with.
    const auto held = static_cast<int32_t>(static_cast<uint32_t>(value));
    if constexpr (std::numeric_limits<Integer>::is_signed)
        flat.narrowed |= static_cast<int64_t>(value) != held;
    else
        flat.narrowed |= static_cast<uint64_t>(value) > static_cast<uint64_t>(std::numeric_limits<int32_t>::max());
    flat.kind = Kind::Int;
    flat.ints.push_back(held);
}

void Add(Flat &flat, int value) { AddInteger(flat, value); }
void Add(Flat &flat, unsigned char value) { AddInteger(flat, value); }
void Add(Flat &flat, unsigned int value) { AddInteger(flat, value); }
void Add(Flat &flat, int64_t value) { AddInteger(flat, value); }
void Add(Flat &flat, uint64_t value) { AddInteger(flat, value); }

void AddFloat(Flat &flat, double value) {
    flat.kind = Kind::Float;
    flat.doubles.push_back(value);
}

void Add(Flat &flat, GfHalf value) { AddFloat(flat, value); }
void Add(Flat &flat, float value) { AddFloat(flat, value); }
void Add(Flat &flat, double value) { AddFloat(flat, value); }

void Add(Flat &flat, const std::string &value) {
    flat.kind = Kind::String;
    flat.strings.push_back(value);
}

void Add(Flat &flat, const TfToken &value) { Add(flat, value.GetString()); }

template <class Vec>
void AddVector(Flat &flat, const Vec &value) {
    flat.tuple = Vec::dimension;
    for (size_t i = 0; i < Vec::dimension; ++i) Add(flat, value[i]);
}

void Add(Flat &flat, const GfVec2i &value) { AddVector(flat, value); }
void Add(Flat &flat, const GfVec3i &value) { AddVector(flat, value); }
void Add(Flat &flat, const GfVec4i &value) { AddVector(flat, value); }
void Add(Flat &flat, const GfVec2h &value) { AddVector(flat, value); }
void Add(Flat &flat, const GfVec3h &value) { AddVector(flat, value); }
void Add(Flat &flat, const GfVec4h &value) { AddVector(flat, value); }
void Add(Flat &flat, const GfVec2f &value) { AddVector(flat, value); }
void Add(Flat &flat, const GfVec3f &value) { AddVector(flat, value); }
void Add(Flat &flat, const GfVec4f &value) { AddVector(flat, value); }
void Add(Flat &flat, const GfVec2d &value) { AddVector(flat, value); }
void Add(Flat &flat, const GfVec3d &value) { AddVector(flat, value); }
void Add(Flat &flat, const GfVec4d &value) { AddVector(flat, value); }

template <class Matrix>
void AddMatrix(Flat &flat, const Matrix &value) {
    flat.tuple = Matrix::numColumns;
    flat.matrix = true;
    // Gf matrices index rows by int (vectors take size_t).
    for (int row = 0; row < static_cast<int>(Matrix::numRows); ++row)
        for (int column = 0; column < static_cast<int>(Matrix::numColumns); ++column) Add(flat, value[row][column]);
}

void Add(Flat &flat, const GfMatrix2f &value) { AddMatrix(flat, value); }
void Add(Flat &flat, const GfMatrix3f &value) { AddMatrix(flat, value); }
void Add(Flat &flat, const GfMatrix4f &value) { AddMatrix(flat, value); }
void Add(Flat &flat, const GfMatrix2d &value) { AddMatrix(flat, value); }
void Add(Flat &flat, const GfMatrix3d &value) { AddMatrix(flat, value); }
void Add(Flat &flat, const GfMatrix4d &value) { AddMatrix(flat, value); }

template <class... Types>
struct TypeList {};

using Supported = TypeList<bool, int, unsigned char, unsigned int, int64_t, uint64_t, GfHalf, float, double, std::string,
                           TfToken, GfVec2i, GfVec3i, GfVec4i, GfVec2h, GfVec3h, GfVec4h, GfVec2f, GfVec3f, GfVec4f,
                           GfVec2d, GfVec3d, GfVec4d, GfMatrix2f, GfMatrix3f, GfMatrix4f, GfMatrix2d, GfMatrix3d,
                           GfMatrix4d>;

// Fills `flat` from a value of a supported type, or a VtArray of one; `array` is whether the result stays an
// array (a one-element array doesn't). False for any other type.
bool Flatten(const VtValue &, Flat &, bool &, TypeList<>) { return false; }

template <class T, class... Rest>
bool Flatten(const VtValue &value, Flat &flat, bool &array, TypeList<T, Rest...>) {
    if (value.IsHolding<T>()) {
        Add(flat, value.UncheckedGet<T>());
        return true;
    }
    if (value.IsHolding<VtArray<T>>()) {
        const auto &elements = value.UncheckedGet<VtArray<T>>();
        array = elements.size() != 1;
        for (const T &element : elements) Add(flat, element);
        return true;
    }
    return Flatten(value, flat, array, TypeList<Rest...>{});
}

}  // namespace

std::optional<PropertyValue> ToProperty(const VtValue &value, std::string &why, std::string &warning) {
    Flat flat;
    bool array = false;
    if (!Flatten(value, flat, array, Supported{})) {
        why = "type " + value.GetTypeName() + " has no Blender property form";
        return std::nullopt;
    }
    if (!flat.why.empty()) {
        why = flat.why;
        return std::nullopt;
    }
    if (array && flat.matrix) {
        why = "an array of matrices has no Blender property form";
        return std::nullopt;
    }
    if (flat.narrowed) warning = "an integer outside Blender's 32-bit range was wrapped to its low 32 bits";
    PropertyValue property;
    // A lone vector is a flat array; an array of vectors, or a matrix, is nested by rows.
    property.tupleSize = array || flat.matrix ? flat.tuple : 0;
    const bool scalar = !array && flat.tuple == 0;
    switch (flat.kind) {
    case Kind::Bool:
        property.value = scalar ? VtValue(bool(flat.bools[0])) : VtValue(flat.bools);
        break;
    case Kind::Int:
        property.value = scalar ? VtValue(flat.ints[0]) : VtValue(flat.ints);
        break;
    case Kind::Float:
        property.value = scalar ? VtValue(flat.doubles[0]) : VtValue(flat.doubles);
        break;
    case Kind::String:
        property.value = scalar ? VtValue(flat.strings[0]) : VtValue(flat.strings);
        break;
    case Kind::None:
        // An empty array: its element kind decides nothing Blender keeps, so it becomes an empty float array.
        property.value = VtValue(VtDoubleArray());
        break;
    }
    return property;
}

bool PropertyNameUsable(const std::string &name, std::string &why) {
    if (name.size() > 63) {
        why = "the name is longer than Blender's 63-byte property names";
        return false;
    }
    if (TfStringStartsWith(name, "proscenium_")) {
        why = "the proscenium_ prefix is reserved for the bridge's own properties";
        return false;
    }
    return true;
}

}  // namespace hydra_bridge
