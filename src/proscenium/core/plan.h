// The display plan (pipeline.md "Display Plan"): what Python's application layer applies, built in the core from a
// snapshot and a planning context. Immutable once built, and deterministic over its inputs, so equal inputs give
// equal plans. Sources are composed-stage paths, and the plan's parts name its resources by their positions in
// Plan::resources, which mean something within that plan only.
//
// M5's minimal planner gives each drawn copy of a gprim a placeholder: a drawn copy's partition holding an object and
// its bounds mesh. M6 replaces the planner; the envelope (partitions, ownership entries, correspondence, and content)
// stays.
#pragma once

#include <pxr/base/gf/matrix4d.h>
#include <pxr/base/vt/array.h>
#include <pxr/pxr.h>
#include <pxr/usd/sdf/path.h>
#include <pxr/usd/usd/timeCode.h>

#include <cstddef>
#include <cstdint>
#include <memory>
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

struct Placeholder {
  std::size_t object;
  std::size_t boundsMesh;
  PXR_NS::GfMatrix4d world{1.0};  // USD's row-vector convention
  // Local bounds as (min x, min y, min z, max x, max y, max z); empty when the gprim has none.
  PXR_NS::VtFloatArray bounds;
};

struct Plan {
  PXR_NS::UsdTimeCode time;
  PlanningContext context;
  std::vector<Partition> partitions;
  std::vector<Resource> resources;
  std::vector<CorrespondenceEntry> correspondence;
  std::vector<Placeholder> placeholders;
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
