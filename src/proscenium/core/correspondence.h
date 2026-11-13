// The correspondence layer (interaction-contract.md "Two Layers and the Live Stage"), ported from the bridge's
// correspondence and interaction: what a published generation's display shows, at the time code it shows, and the
// source entity each display element came from. Python builds one per shown generation from its manifest and Blender
// data (DECISIONS.md "Persisted correspondence"); its elements are named by their indices among its own elements,
// which Python maps to manifest entry keys (DECISIONS.md "Headless interaction functions"). Paths are USD paths.
#pragma once

#include <pxr/pxr.h>
#include <pxr/usd/sdf/path.h>
#include <pxr/usd/usd/stage.h>

#include <cstddef>
#include <optional>
#include <stdexcept>
#include <utility>
#include <vector>

namespace proscenium {

// The live stage has expired (interaction-contract.md "Without a Live Stage"). Python raises it as
// proscenium.core._core.SourceUnavailableError.
class SourceUnavailableError : public std::runtime_error {
 public:
  SourceUnavailableError() : std::runtime_error("The source is unavailable: the binding has no live stage") {}
};

// One display element as Python gives it: an object a manifest entry names.
struct DisplayElement {
  PXR_NS::SdfPath sourcePath;  // its copy's source entity: an instance-proxy or point-instance path
  // Its copy's native-instance roots, point instancers, and points, outermost first, from a held plan; absent when
  // no held plan has the copy, and then derived from the source path on the live stage.
  std::optional<PXR_NS::SdfPathVector> instanceContext;
  bool inViewport = false;  // its object's viewport hide flag shows it at the frame the display shows
};

// A source entity: its path and instance context.
struct SourceEntity {
  PXR_NS::SdfPath sourcePath;
  PXR_NS::SdfPathVector instanceContext;
};

// The floor of an entity (interaction-contract.md "Selection"): the first of its instance context, or the entity
// itself outside instance contents.
const PXR_NS::SdfPath& Floor(const SourceEntity& entity);

// The instance context of the entity at `sourcePath` on `stage`, as the planner gives it (instancing.h): each prefix
// that is a native-instance root, and for a point-instance path element its instancer and its point, outermost first.
// Below a point, the path continues from the prototype root's name, so prefixes there are read at the prototype the
// instancer targets with that name. A prefix the stage lacks contributes nothing.
PXR_NS::SdfPathVector InstanceContextOnStage(const PXR_NS::UsdStage& stage, const PXR_NS::SdfPath& sourcePath);

// Every function but the constructor runs without Python, and raises SourceUnavailableError once the live stage has
// expired.
class Correspondence {
 public:
  // Holds `stage` weakly. Throws SourceUnavailableError for an expired or null stage.
  Correspondence(PXR_NS::UsdStagePtr stage, std::vector<DisplayElement> elements);

  [[nodiscard]] std::size_t ElementCount() const { return entities_.size(); }

  // The element's entity, or std::nullopt for an index that names no element.
  [[nodiscard]] std::optional<SourceEntity> ResolvePick(std::size_t elementIndex) const;
  // Whether each path is in the browsing universe.
  [[nodiscard]] std::vector<bool> Displayed(const PXR_NS::SdfPathVector& paths) const;
  // The viewport elements at or beneath each target in the universe, by index, ascending and each once.
  [[nodiscard]] std::vector<std::size_t> HighlightTargets(const PXR_NS::SdfPathVector& targetPaths) const;

 private:
  // The live stage, or SourceUnavailableError.
  [[nodiscard]] const PXR_NS::UsdStage& Live() const;
  [[nodiscard]] bool InUniverse(const PXR_NS::SdfPath& path) const;

  PXR_NS::UsdStagePtr stage_;           // weak: the binding's live stage, which its caller owns
  std::vector<SourceEntity> entities_;  // by element index
  // The browsing universe: the floors of the viewport's elements and every prefix of them but the absolute root.
  // Sorted and unique; SdfPath's order keeps each prim's subtree one contiguous range.
  PXR_NS::SdfPathVector universe_;
  // The viewport's elements as (floor, element index), sorted, so the elements beneath a prim are one range.
  std::vector<std::pair<PXR_NS::SdfPath, std::size_t>> viewportElementsByFloor_;
};

}  // namespace proscenium
