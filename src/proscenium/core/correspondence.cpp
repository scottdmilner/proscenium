// Correspondence: floors, the browsing universe, and the viewport's elements by floor, from Python's display elements.
#include "correspondence.h"

#include <pxr/base/tf/stringUtils.h>
#include <pxr/usd/usd/prim.h>
#include <pxr/usd/usd/relationship.h>
#include <pxr/usd/usdGeom/pointInstancer.h>

#include <algorithm>

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

}  // namespace proscenium
