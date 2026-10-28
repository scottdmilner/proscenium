// The display plan: what Python applies to Blender. Built entirely in C++ from a Snapshot, immutable,
// with large arrays in Blender's exact element types so they cross through the buffer protocol.
// Sources are USD paths (instance proxies inside native instances); Hydra paths never are.
#pragma once

#include "correspondence.h"
#include "diagnostics.h"
#include "properties.h"
#include "snapshot.h"

#include <pxr/pxr.h>
#include <pxr/base/gf/matrix4d.h>
#include <pxr/base/gf/range3d.h>
#include <pxr/base/tf/token.h>
#include <pxr/base/vt/array.h>
#include <pxr/base/vt/types.h>
#include <pxr/base/vt/value.h>
#include <pxr/usd/sdf/path.h>
#include <pxr/usd/usd/timeCode.h>

#include <cstddef>
#include <cstdint>
#include <memory>
#include <optional>
#include <string>
#include <utility>
#include <vector>

namespace hydra_bridge {

// Blender attribute domains and data types, named as bpy spells them.
enum class Domain : std::uint8_t { Point, Face, Corner };
enum class DataType : std::uint8_t { Float, Float2, FloatVector, FloatColor, Int };

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
    pxr::VtIntArray cornerVerts;  // per corner
    pxr::VtIntArray faceOffsets;  // per face: its first corner (Blender's loop_start)
    // Per face, its material slot: 0 for the mesh's own binding, then one per materialBind subset. Objects
    // say which material each slot holds, so one mesh serves both destinations.
    pxr::VtIntArray materialIndices;
    int slotCount = 1;
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
    pxr::SdfPathVector instanceContext;    // native instance roots, outermost first
    int mesh = -1;                         // into Plan::meshes; -1 for a placeholder
    pxr::TfToken placeholderType;          // the untranslated Hydra type, for a placeholder
    std::optional<pxr::GfRange3d> bounds;  // a placeholder's local bounds, when Hydra has an extent
    pxr::GfMatrix4d matrix{1.0};           // world, USD row-vector convention
    bool visible = true;                   // effective visibility for the object's own purpose
    // Whether the object displays there: visible, and its purpose is one the destination includes.
    bool inViewport = false;
    bool inRender = false;
    std::vector<int> materialSlots;  // per mesh slot, into Plan::materials; -1 for no material
    pxr::TfToken purpose;
    // The prim's own constant primvars, then inherited per-instance values it doesn't shadow,
    // innermost instance first, as USD authored them.
    ConstantPrimvars constantPrimvars;
    // The same primvars as the ID properties Blender holds, by primvar name; those it can't hold are diagnosed.
    std::vector<std::pair<std::string, PropertyValue>> properties;
};

struct Plan {
    pxr::UsdTimeCode time;
    std::vector<MeshData> meshes;
    std::vector<std::size_t> meshHashes;  // per mesh, its ContentHash, which a later plan's diff looks up (M4)
    std::vector<MaterialData> materials;
    std::vector<ObjectEntry> objects;
    Correspondence correspondence;  // derived from the objects once they are all planned
    Diagnostics diagnostics;        // sources are USD paths
};

using PlanPtr = std::shared_ptr<const Plan>;

// What one destination displays: prim purposes (Hydra's names, so USD's default is "geometry"), and the
// material purpose its bindings are resolved for (empty: allPurpose; any other falls back to allPurpose, as
// in UsdShade).
struct Destination {
    pxr::TfTokenVector purposes;
    pxr::TfToken materialPurpose;
};

// Binding settings that change the plan. A guide is invisible unless USD makes it explicitly visible
// (guideVisibility), so including guides in the viewport shows exactly those (spec VIS-04).
struct PlanSettings {
    Destination viewport{{pxr::TfToken("geometry"), pxr::TfToken("proxy"), pxr::TfToken("guide")},
                         pxr::TfToken("preview")};
    Destination render{{pxr::TfToken("geometry"), pxr::TfToken("render")}, pxr::TfToken("full")};
};

// Call without the GIL. Invalid geometry becomes a placeholder and a diagnostic, never an exception.
PlanPtr BuildPlan(const Snapshot &snapshot, const PlanSettings &settings = {});

}  // namespace hydra_bridge
