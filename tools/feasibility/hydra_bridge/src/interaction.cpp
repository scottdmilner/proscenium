// Interaction: the baseline's core interaction functions, over a plan's correspondence and the live stage.
#include "interaction.h"

#include "inspection.h"

#include <pxr/usd/kind/registry.h>

#include <algorithm>
#include <unordered_set>
#include <utility>

PXR_NAMESPACE_USING_DIRECTIVE

namespace hydra_bridge {

namespace {

SdfPath Target(const UsdStage &stage, const SdfPath &floor, const std::optional<TfToken> &level) {
    return level ? KindTarget(stage, floor, *level) : floor;
}

}  // namespace

SdfPath Floor(const Entity &entity) {
    return entity.instanceContext.empty() ? entity.source : entity.instanceContext.front();
}

Interaction::Interaction(UsdStagePtr stage, PlanPtr plan)
    : stage_(std::move(stage)),
      plan_(std::move(plan)) {}

void Interaction::CheckLevel(const TfToken &level) {
    if (!KindRegistry::HasKind(level))
        throw std::invalid_argument("'" + level.GetString() + "' is not a registered kind");
}

const UsdStage &Interaction::Live() const {
    if (!stage_) throw SourceUnavailableError();
    return *stage_;
}

bool Interaction::InUniverse(const SdfPath &path) const {
    const SdfPathVector &universe = plan_->correspondence.universe;
    return std::binary_search(universe.begin(), universe.end(), path);
}

std::optional<Entity> Interaction::ResolvePick(std::size_t element) const {
    Live();
    if (element >= plan_->objects.size()) return std::nullopt;
    const ObjectEntry &object = plan_->objects[element];
    return Entity{object.source, object.instanceContext};
}

SdfPathVector Interaction::SelectTargets(const std::vector<Entity> &entities,
                                         const std::optional<TfToken> &level) const {
    const UsdStage &stage = Live();
    SdfPathVector targets;
    targets.reserve(entities.size());
    for (const Entity &entity : entities) targets.push_back(Target(stage, Floor(entity), level));
    return targets;
}

std::vector<bool> Interaction::Displayed(const SdfPathVector &paths) const {
    Live();
    std::vector<bool> displayed;
    displayed.reserve(paths.size());
    for (const SdfPath &path : paths) displayed.push_back(InUniverse(path));
    return displayed;
}

std::vector<std::size_t> Interaction::HighlightTargets(const SdfPathVector &targets) const {
    Live();
    const auto &elements = plan_->correspondence.elements;
    std::vector<std::size_t> covered;
    for (const SdfPath &target : targets) {
        // Outside the universe, a target has nothing displayed beneath it, and may be inside instance contents.
        if (!InUniverse(target)) continue;
        // The elements whose floors are at or beneath the target are one range, starting at the target.
        auto it = std::lower_bound(elements.begin(), elements.end(), target,
                                   [](const auto &element, const SdfPath &path) { return element.first < path; });
        for (; it != elements.end() && it->first.HasPrefix(target); ++it) covered.push_back(it->second);
    }
    std::sort(covered.begin(), covered.end());
    covered.erase(std::unique(covered.begin(), covered.end()), covered.end());
    return covered;
}

SourceSelection Interaction::SelectionFromBlender(const std::vector<std::size_t> &selected,
                                                  std::optional<std::size_t> active,
                                                  const std::optional<TfToken> &level) const {
    const UsdStage &stage = Live();
    SourceSelection selection;
    std::unordered_set<SdfPath, SdfPath::Hash> seen;
    for (const std::size_t element : selected) {
        const std::optional<Entity> entity = ResolvePick(element);
        if (!entity) continue;
        SdfPath target = Target(stage, Floor(*entity), level);
        if (active == element) selection.active = target;
        if (seen.insert(target).second) selection.targets.push_back(std::move(target));
    }
    return selection;
}

}  // namespace hydra_bridge
