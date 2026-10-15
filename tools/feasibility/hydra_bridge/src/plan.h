// The display plan: what Python applies to Blender. Built entirely in C++ from a Snapshot, immutable,
// with large arrays in Blender's exact element types so they cross through the buffer protocol.
// Sources are USD paths (instance proxies inside native instances); Hydra paths never are.
#pragma once

#include "diagnostics.h"
#include "snapshot.h"

#include <pxr/pxr.h>
#include <pxr/base/gf/matrix4d.h>
#include <pxr/base/tf/token.h>
#include <pxr/base/vt/array.h>
#include <pxr/base/vt/types.h>
#include <pxr/base/vt/value.h>
#include <pxr/usd/sdf/path.h>
#include <pxr/usd/usd/timeCode.h>

#include <memory>
#include <string>
#include <utility>
#include <vector>

namespace hydra_bridge {

// Blender attribute domains and data types, named as bpy spells them.
enum class Domain { Point, Face, Corner };
enum class DataType { Float, Float2, FloatVector, FloatColor, Int };

const char *DomainName(Domain domain);
const char *DataTypeName(DataType type);

struct Attribute {
    std::string name;
    Domain domain;
    DataType type;
    // VtFloatArray, VtVec2fArray, VtVec3fArray, VtVec4fArray, or VtIntArray, one value per element.
    pxr::VtValue data;
};

using ConstantPrimvars = std::vector<std::pair<pxr::TfToken, pxr::VtValue>>;

struct MeshData {
    std::string name;
    pxr::VtVec3fArray positions;
    pxr::VtIntArray cornerVerts;      // per corner
    pxr::VtIntArray faceOffsets;      // per face: its first corner (Blender's loop_start)
    pxr::VtIntArray materialIndices;  // per face, into materialSlots
    std::vector<int> materialSlots;   // into Plan::materials; -1 for no material
    std::vector<Attribute> attributes;
    pxr::TfToken subdivisionScheme;
    bool doubleSided = false;
};

struct MaterialData {
    std::string name;
    pxr::SdfPathVector sources;  // one per drawn copy: a material inside a native instance has several
    pxr::TfToken surfaceIdentifier;
    std::vector<std::pair<pxr::TfToken, pxr::VtValue>> surfaceParameters;
};

struct ObjectEntry {
    pxr::SdfPath source;
    pxr::SdfPathVector instanceContext;  // native instance roots, outermost first
    int mesh = -1;                       // into Plan::meshes; -1 for a placeholder
    pxr::TfToken placeholderType;        // the untranslated Hydra type, for a placeholder
    pxr::GfMatrix4d matrix{1.0};         // world, USD row-vector convention
    bool visible = true;
    pxr::TfToken purpose;
    // The prim's own constant primvars, then inherited per-instance values it doesn't shadow,
    // innermost instance first. Each value is a one-element array.
    ConstantPrimvars constantPrimvars;
};

struct Plan {
    pxr::UsdTimeCode time;
    std::vector<MeshData> meshes;
    std::vector<MaterialData> materials;
    std::vector<ObjectEntry> objects;
    Diagnostics diagnostics;  // sources are USD paths
};

using PlanPtr = std::shared_ptr<const Plan>;

// Call without the GIL. Invalid geometry becomes a placeholder and a diagnostic, never an exception.
PlanPtr BuildPlan(const Snapshot &snapshot);

}  // namespace hydra_bridge
