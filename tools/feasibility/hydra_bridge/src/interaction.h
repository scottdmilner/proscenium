// M4: the core's interaction functions for the baseline (interaction contract, "Headless Functions"), over one
// published generation's plan and the live stage. Correspondence answers from the plan; kind levels go to the
// inspection model (inspection.h) in C++, so paths never pass through Python between the two. A display
// element is named by its plan object index, which apply.py records on its Blender object.
#pragma once

#include "plan.h"

#include <pxr/pxr.h>
#include <pxr/base/tf/token.h>
#include <pxr/usd/sdf/path.h>
#include <pxr/usd/usd/stage.h>

#include <cstddef>
#include <optional>
#include <stdexcept>
#include <vector>

namespace hydra_bridge {

// A binding's source entity: a USD path, and the native instance roots above it, outermost first.
struct Entity {
    pxr::SdfPath source;
    pxr::SdfPathVector instanceContext;
};

// The floor of an entity: the first of its instance context, or the entity itself outside instance contents.
pxr::SdfPath Floor(const Entity &entity);

// The live stage has expired (interaction contract, "Without a Live Stage").
class SourceUnavailableError : public std::runtime_error {
public:
    SourceUnavailableError()
        : std::runtime_error("the source is unavailable: the live stage has expired") {}
};

struct SourceSelection {
    pxr::SdfPathVector targets;  // in the order of the selected elements, without repeats
    pxr::SdfPath active;         // the active element's target; empty when no element is active
};

// Every function raises SourceUnavailableError once the live stage has expired. A kind level is a registered
// model kind; std::nullopt is the prim level.
class Interaction {
public:
    Interaction(pxr::UsdStagePtr stage, PlanPtr plan);

    // The element's entity, or std::nullopt for an index that names no element of this generation.
    [[nodiscard]] std::optional<Entity> ResolvePick(std::size_t element) const;
    [[nodiscard]] pxr::SdfPathVector SelectTargets(const std::vector<Entity> &entities,
                                                   const std::optional<pxr::TfToken> &level) const;
    [[nodiscard]] std::vector<bool> Displayed(const pxr::SdfPathVector &paths) const;
    // The viewport elements at or beneath each target in the universe, in plan order, without repeats.
    [[nodiscard]] std::vector<std::size_t> HighlightTargets(const pxr::SdfPathVector &targets) const;
    // `active` is one of `selected`, or std::nullopt; indices naming no element are ignored.
    [[nodiscard]] SourceSelection SelectionFromBlender(const std::vector<std::size_t> &selected,
                                                       std::optional<std::size_t> active,
                                                       const std::optional<pxr::TfToken> &level) const;

    // Throws std::invalid_argument unless `level` is a registered kind.
    static void CheckLevel(const pxr::TfToken &level);

private:
    // The live stage, or SourceUnavailableError.
    [[nodiscard]] const pxr::UsdStage &Live() const;
    [[nodiscard]] bool InUniverse(const pxr::SdfPath &path) const;

    pxr::UsdStagePtr stage_;  // weak: the binding's live stage, which the caller owns
    PlanPtr plan_;            // the published generation
};

}  // namespace hydra_bridge
