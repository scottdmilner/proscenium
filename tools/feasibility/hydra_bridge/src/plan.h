// The display plan: what Python applies to Blender. Built entirely in C++ from a Snapshot, immutable,
// with large arrays in Blender's exact element types so they cross through the buffer protocol.
// Sources are USD paths (instance proxies inside native instances); Hydra paths never are.
#pragma once

#include "correspondence.h"
#include "diagnostics.h"
#include "prim_record.h"
#include "properties.h"
#include "snapshot.h"

#include <pxr/pxr.h>
#include <pxr/base/gf/matrix4d.h>
#include <pxr/base/gf/range3d.h>
#include <pxr/base/gf/vec4f.h>
#include <pxr/base/tf/token.h>
#include <pxr/base/vt/array.h>
#include <pxr/base/vt/types.h>
#include <pxr/base/vt/value.h>
#include <pxr/imaging/hd/dataSource.h>
#include <pxr/imaging/pxOsd/meshTopology.h>
#include <pxr/usd/sdf/path.h>
#include <pxr/usd/usd/timeCode.h>

#include <cstddef>
#include <cstdint>
#include <memory>
#include <optional>
#include <string>
#include <unordered_map>
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
    // The constant display color, alpha its opacity, that every copy of this mesh has, if they share one, which
    // Blender's mesh holds on points as displayColor, so Solid shading's Attribute color shows it (M4 Phase D).
    // Part of the mesh's content, so a change in what its copies share gives the plan a new mesh.
    std::optional<pxr::GfVec4f> heldColor;
};

struct MaterialData {
    std::string name;
    pxr::SdfPathVector sources;  // one per drawn copy: a material inside a native instance has several
    pxr::TfToken surfaceIdentifier;
    std::vector<std::pair<pxr::TfToken, pxr::VtValue>> surfaceParameters;
};

// M4 Phase E: an aspect of an object that can vary over time, as frames.py's Aspect names it.
enum class Aspect : std::uint8_t { Transform, Visibility, Mesh, Materials, Properties, Bounds };

const char *AspectName(Aspect aspect);  // "transform", "visibility", "mesh", "materials", "properties", "bounds"

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
    // The same primvars as the ID properties Blender holds, by primvar name; strings, and those it
    // can't hold, are diagnosed.
    std::vector<std::pair<std::string, PropertyValue>> properties;
    // M4 Phase E (E3): the aspects the snapshot's dirtied locators reach in the object, in the enum's order. After a
    // time change, or a capture with its time dependencies, those that depend on time. The plan diff ignores it.
    std::vector<Aspect> dirtiedAspects;
};

// M4 Phase E (E4): what BuildMesh finds from a mesh's topology and point count alone.
struct TopologyWork {
    std::vector<bool> rejectedFaceMask;  // per captured face, whether Blender would delete it; empty for none
    Diagnostics problems;                // the topology's own, which come first among the build's
};

// M4 Phase D (D9, a probe): a mesh prim's build, kept with the captured containers of the prim and its subsets
// it was built from. BuildMesh reads only those, and an incremental capture shares the container of every prim
// no notice named, so a later plan whose prim and subsets have the same containers can reuse the build. A later
// build of the prim with a new container reuses what its topology and primvars still give (E4, BuildMesh).
struct MeshBuild {
    pxr::HdContainerDataSourceHandle prim;
    std::vector<pxr::HdContainerDataSourceHandle> subsets;
    pxr::PxOsdMeshTopology topology;      // what it was built from (E4)
    std::vector<PrimvarRecord> primvars;  // likewise
    TopologyWork topologyWork;
    std::optional<MeshData> mesh;
    std::size_t contentHash = 0;
    Diagnostics problems;
    pxr::SdfPathVector materialBindingPrimPaths;  // the prims whose bindings the mesh's slots take
};

using MeshBuilds = std::unordered_map<pxr::SdfPath, MeshBuild, pxr::SdfPath::Hash>;

struct Plan {
    pxr::UsdTimeCode timeCode;
    std::vector<MeshData> meshes;
    std::vector<std::size_t> meshHashes;  // per mesh, its ContentHash, which a later plan's diff looks up (M4)
    std::vector<MaterialData> materials;
    std::vector<ObjectEntry> objects;
    Correspondence correspondence;  // derived from the objects once they are all planned
    Diagnostics diagnostics;        // sources are USD paths
    MeshBuilds builds;              // by mesh prim path: what the next plan may reuse (D9)
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
    // Whether a point instancer's instances become objects, one per point and prototype mesh (M4 Phase D, with a
    // provisional identity: the spec defers point instancers); otherwise the instancer gets a placeholder.
    bool pointInstancers = true;
};

// Call without the GIL. Invalid geometry becomes a placeholder and a diagnostic, never an exception. With
// `previous`, a mesh whose prim and subsets are the containers `previous` built it from reuses that build (D9), and
// any other mesh `previous` built reuses what its topology and primvars still give (E4); the plan is the same
// either way. Null: every mesh is built anew.
PlanPtr BuildPlan(const Snapshot &snapshot, const PlanSettings &settings = {}, const Plan *previous = nullptr);

}  // namespace hydra_bridge
