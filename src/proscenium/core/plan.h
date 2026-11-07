// The display plan (pipeline.md "Display Plan"): what Python's application layer applies, built in the core from a
// snapshot and a planning context. Immutable once built, and deterministic over its inputs, so equal inputs give
// equal plans. Sources are composed-stage paths, and the plan's parts name its resources by their positions in
// Plan::resources, which mean something within that plan only.
//
// Each drawn copy of a gprim is a drawn copy's partition holding an object and its bounds mesh, which the stub
// application layer draws as its bounds. A mesh's copies share its provisional geometry description; any other gprim's
// copy is a placeholder. Per-copy content crosses as structure-of-arrays buffers in Blender's element types, so a
// consumer reads each once per plan; paths stay tuples.
#pragma once

#include <pxr/base/gf/matrix4d.h>
#include <pxr/base/vt/array.h>
#include <pxr/pxr.h>
#include <pxr/usd/sdf/path.h>
#include <pxr/usd/usd/timeCode.h>

#include <cstddef>
#include <cstdint>
#include <memory>
#include <string>
#include <utility>
#include <vector>

#include "snapshot.h"

namespace proscenium {

// The representation roles M5's planner gives (DECISIONS.md "Representation roles and resource identities").
enum class Role : std::uint8_t { kObject, kBoundsMesh };

// The role's name in the vocabulary, as ownership entries store it.
const char* RoleName(Role role);

// The planning context (pipeline.md "Display Plan"): plain values Python captures before planning.
struct PlanningContext {
  // The target scene's unit scale, which coordinate conversion reads (transforms.md); conversion is M6's.
  double unitScale = 1.0;
  int representationVersion = 1;  // the representation the application layer applies; the planner plans only 1

  // Throws std::invalid_argument for a unit scale that isn't positive and finite.
  PlanningContext(double scale, int version);
};

// One managed resource, as its ownership entry records it (lifecycle.md "Ownership and Lifecycle"). Its identity is
// a value, compared by equality (DECISIONS.md "Representation roles and resource identities"): a drawn copy's
// resource is identified by its role, its copy's source entity, and its place among the copy's objects.
struct Resource {
  Role role;
  PXR_NS::SdfPath entity;         // its copy's source entity
  std::uint32_t place = 0;        // among its copy's objects
  PXR_NS::SdfPathVector covers;   // the source entities it represents
  std::vector<std::size_t> uses;  // the resources it depends on
};

// A unit of display replacement, owning its resources.
struct Partition {
  std::vector<std::size_t> resources;
};

// A display element and the source entity it represents (interaction-contract.md "Two Layers and the Live Stage").
struct CorrespondenceEntry {
  std::size_t element;     // the object that shows it
  PXR_NS::SdfPath source;  // an instance-proxy path inside native instances
  // Provisional (M10 completes instance descriptions): the native-instance roots the source lies in, outermost first.
  PXR_NS::SdfPathVector instanceContext;
};

// Provisional (M8 replaces it): a mesh's geometry, shared by every drawn copy of the mesh.
struct GeometryDescription {
  PXR_NS::SdfPath source;  // its first drawn copy's, in source order
  // Local bounds as (min x, min y, min z, max x, max y, max z); empty when Hydra gives the mesh none.
  PXR_NS::VtFloatArray extent;
  // Provisional: the source's path, one per mesh Hydra draws, so a prototype's mesh is shared by its copies. M8 keys
  // a mesh by its content.
  std::string contentKey;
};

struct Plan {
  PXR_NS::UsdTimeCode time;
  PlanningContext context;
  std::vector<Partition> partitions;
  std::vector<Resource> resources;
  std::vector<CorrespondenceEntry> correspondence;  // one per drawn copy, in the copies' order
  // The drawn copies, in source order, one element (or 16) per copy.
  PXR_NS::VtFloatArray copyWorlds;    // 16 each: the world matrix in Blender's layout, which is USD's row-major one
  PXR_NS::VtIntArray copyObjects;     // its object, in resources
  PXR_NS::VtIntArray copyGeometries;  // its geometry description, in geometries; -1 for none
  // Its placeholder, in placeholderBounds; -1 for none, and for a copy with neither a geometry nor bounds (C5 makes
  // it a marker).
  PXR_NS::VtIntArray copyPlaceholders;
  PXR_NS::VtFloatArray placeholderBounds;  // 6 each, as GeometryDescription::extent
  std::vector<GeometryDescription> geometries;
};

using PlanPtr = std::shared_ptr<const Plan>;

// Runs without the GIL. Throws std::invalid_argument for a representation version the planner doesn't plan.
PlanPtr BuildPlan(const Snapshot& snapshot, const PlanningContext& context);

// EXCEPTION to the rule against test-only API (with the user, 2026-11-06): each drawn copy's world transform as
// Hydra's own values compose it, ignoring a reset transform stack inside an instance, by source. Only the known-gap
// check for OpenUSD #862 calls it: the bug shows only in Hydra's composition, which nothing else exposes, and the
// check must fail once Hydra honors the reset so the workaround can go.
std::vector<std::pair<PXR_NS::SdfPath, PXR_NS::GfMatrix4d>> HydraComposedWorlds(const Snapshot& snapshot);

}  // namespace proscenium
