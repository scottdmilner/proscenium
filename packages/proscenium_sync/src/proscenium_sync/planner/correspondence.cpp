// Correspondence: floors, the browsing universe, and the viewport's elements by floor, from Python's display elements,
// and selection targets through the inspection layer.
#include "correspondence.h"

#include <kind_targets.h>
#include <pxr/base/tf/stringUtils.h>
#include <pxr/usd/usd/prim.h>
#include <pxr/usd/usd/relationship.h>
#include <pxr/usd/usdGeom/pointInstancer.h>

#include <algorithm>
#include <numeric>
#include <string>
#include <unordered_set>

PXR_NAMESPACE_USING_DIRECTIVE

namespace proscenium {

namespace {

// Whether a path element names a point, as instancing.cpp's PointInstancePathElement does.
bool NamesPoint(const std::string& element) {
  return TfStringStartsWith(element, "__id_") || TfStringStartsWith(element, "__index_");
}

}  // namespace

const SdfPath& Floor(const SourceEntity& entity) {
  return entity.instanceContext.empty() ? entity.sourcePath : entity.instanceContext.front();
}

SdfPathVector InstanceContextOnStage(const UsdStage& stage, const SdfPath& sourcePath) {
  SdfPathVector context;
  // Below a point, prefixes from `pointPrototypeRoot` on read at the prototype `stagePrototypeRoot`.
  SdfPath pointPrototypeRoot;
  SdfPath stagePrototypeRoot;
  const auto onStage = [&](const SdfPath& path) {
    return pointPrototypeRoot.IsEmpty() ? path : path.ReplacePrefix(pointPrototypeRoot, stagePrototypeRoot);
  };
  const SdfPathVector prefixes = sourcePath.GetPrefixes();
  for (std::size_t i = 0; i < prefixes.size(); ++i) {
    const SdfPath& prefix = prefixes[i];
    if (NamesPoint(prefix.GetName())) {
      const UsdGeomPointInstancer instancer(stage.GetPrimAtPath(onStage(prefix.GetParentPath())));
      if (instancer) {
        context.push_back(prefix.GetParentPath());
        context.push_back(prefix);
        if (i + 1 == prefixes.size()) break;
        // The next element is the prototype root's name.
        SdfPathVector prototypes;
        instancer.GetPrototypesRel().GetForwardedTargets(&prototypes);
        const TfToken& name = prefixes[i + 1].GetNameToken();
        const auto prototype = std::find_if(prototypes.begin(), prototypes.end(),
                                            [&](const SdfPath& p) { return p.GetNameToken() == name; });
        if (prototype == prototypes.end()) break;
        pointPrototypeRoot = prefixes[i + 1];
        stagePrototypeRoot = *prototype;
        continue;
      }
    }
    const UsdPrim prim = stage.GetPrimAtPath(onStage(prefix));
    if (prim && prim.IsInstance()) context.push_back(prefix);
  }
  return context;
}

Correspondence::Correspondence(UsdStagePtr stage, std::vector<DisplayElement> elements) : stage_(std::move(stage)) {
  const UsdStage& live = Live();
  entities_.reserve(elements.size());
  for (std::size_t i = 0; i < elements.size(); ++i) {
    DisplayElement& element = elements[i];
    SdfPathVector context = element.instanceContext ? std::move(*element.instanceContext)
                                                    : InstanceContextOnStage(live, element.sourcePath);
    const SourceEntity& entity =
        entities_.emplace_back(SourceEntity{std::move(element.sourcePath), std::move(context)});
    // Only the viewport's elements make prims browsable; render-only content doesn't (ICON-12).
    if (!element.inViewport) continue;
    const SdfPath& floor = Floor(entity);
    viewportElementsByFloor_.emplace_back(floor, i);
    for (SdfPath path = floor; !path.IsEmpty() && !path.IsAbsoluteRootPath(); path = path.GetParentPath())
      universe_.push_back(path);
  }
  std::sort(universe_.begin(), universe_.end());
  universe_.erase(std::unique(universe_.begin(), universe_.end()), universe_.end());
  std::sort(viewportElementsByFloor_.begin(), viewportElementsByFloor_.end());
  elementIndicesBySourcePath_.resize(entities_.size());
  std::iota(elementIndicesBySourcePath_.begin(), elementIndicesBySourcePath_.end(), std::size_t{0});
  std::sort(elementIndicesBySourcePath_.begin(), elementIndicesBySourcePath_.end(),
            [&](std::size_t a, std::size_t b) { return entities_[a].sourcePath < entities_[b].sourcePath; });
}

const UsdStage& Correspondence::Live() const {
  if (!stage_) throw SourceUnavailableError();
  return *stage_;
}

bool Correspondence::InUniverse(const SdfPath& path) const {
  return std::binary_search(universe_.begin(), universe_.end(), path);
}

std::optional<SourceEntity> Correspondence::ResolvePick(std::size_t elementIndex) const {
  static_cast<void>(Live());
  if (elementIndex >= entities_.size()) return std::nullopt;
  return entities_[elementIndex];
}

std::vector<bool> Correspondence::Displayed(const SdfPathVector& paths) const {
  static_cast<void>(Live());
  std::vector<bool> displayed;
  displayed.reserve(paths.size());
  for (const SdfPath& path : paths) displayed.push_back(InUniverse(path));
  return displayed;
}

std::vector<std::size_t> Correspondence::HighlightTargets(const SdfPathVector& targetPaths) const {
  static_cast<void>(Live());
  std::vector<std::size_t> covered;
  for (const SdfPath& target : targetPaths) {
    // Outside the universe, a target has nothing displayed beneath it, and may be inside instance contents.
    if (!InUniverse(target)) continue;
    // The elements whose floors are at or beneath the target are one range, starting at the target.
    auto it = std::lower_bound(viewportElementsByFloor_.begin(), viewportElementsByFloor_.end(), target,
                               [](const auto& element, const SdfPath& path) { return element.first < path; });
    for (; it != viewportElementsByFloor_.end() && it->first.HasPrefix(target); ++it) covered.push_back(it->second);
  }
  std::sort(covered.begin(), covered.end());
  covered.erase(std::unique(covered.begin(), covered.end()), covered.end());
  return covered;
}

namespace {

// Throws std::invalid_argument unless `level` is the prim level or a registered kind.
void CheckLevel(const std::optional<TfToken>& level) {
  if (level && !proscenium_inspection::IsRegisteredKind(*level))
    throw std::invalid_argument("'" + level->GetString() + "' is not a registered kind");
}

SdfPath Target(const UsdStage& stage, const SdfPath& floor, const std::optional<TfToken>& level) {
  return level ? proscenium_inspection::KindTarget(stage, floor, *level) : floor;
}

}  // namespace

SdfPath Correspondence::FloorOf(const UsdStage& stage, const SdfPath& entityPath) const {
  const auto found =
      std::lower_bound(elementIndicesBySourcePath_.begin(), elementIndicesBySourcePath_.end(), entityPath,
                       [&](std::size_t element, const SdfPath& path) { return entities_[element].sourcePath < path; });
  if (found != elementIndicesBySourcePath_.end() && entities_[*found].sourcePath == entityPath)
    return Floor(entities_[*found]);
  const SdfPathVector context = InstanceContextOnStage(stage, entityPath);
  return context.empty() ? entityPath : context.front();
}

SdfPathVector Correspondence::SelectTargets(const SdfPathVector& entityPaths,
                                            const std::optional<TfToken>& level) const {
  const UsdStage& stage = Live();
  CheckLevel(level);
  SdfPathVector targets;
  targets.reserve(entityPaths.size());
  for (const SdfPath& path : entityPaths) targets.push_back(Target(stage, FloorOf(stage, path), level));
  return targets;
}

SourceSelection Correspondence::SelectionFromBlender(const std::vector<std::size_t>& selectedElementIndices,
                                                     std::optional<std::size_t> activeElementIndex,
                                                     const std::optional<TfToken>& level) const {
  const UsdStage& stage = Live();
  CheckLevel(level);
  SourceSelection selection;
  std::unordered_set<SdfPath, SdfPath::Hash> seen;
  for (const std::size_t element : selectedElementIndices) {
    if (element >= entities_.size()) continue;
    SdfPath target = Target(stage, Floor(entities_[element]), level);
    if (activeElementIndex == element) selection.activeTargetPath = target;
    if (seen.insert(target).second) selection.targetPaths.push_back(std::move(target));
  }
  return selection;
}

}  // namespace proscenium
