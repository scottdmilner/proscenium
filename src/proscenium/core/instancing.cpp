#include "instancing.h"

#include <pxr/base/gf/matrix4f.h>
#include <pxr/base/gf/quatd.h>
#include <pxr/base/gf/quatf.h>
#include <pxr/base/gf/quath.h>
#include <pxr/base/gf/rotation.h>
#include <pxr/base/gf/vec3d.h>
#include <pxr/base/gf/vec3f.h>
#include <pxr/base/gf/vec3h.h>
#include <pxr/base/tf/stringUtils.h>
#include <pxr/base/vt/array.h>
#include <pxr/imaging/hd/tokens.h>
#include <pxr/usd/usdGeom/tokens.h>

#include <algorithm>
#include <array>
#include <cstddef>
#include <cstdint>
#include <optional>
#include <string>
#include <utility>
#include <vector>

PXR_NAMESPACE_USING_DIRECTIVE

namespace proscenium {
namespace {

// Deeper nesting than any real scene; malformed data must not recurse without bound.
constexpr int kMaxDepth = 64;

std::optional<VtMatrix4dArray> InstanceTransforms(const PrimRecord& instancer) {
  const PrimvarRecord* primvar = instancer.FindPrimvar(HdInstancerTokens->instanceTransforms);
  if (!primvar || primvar->indices) return std::nullopt;
  if (primvar->values.IsHolding<VtMatrix4dArray>()) return primvar->values.UncheckedGet<VtMatrix4dArray>();
  if (primvar->values.IsHolding<VtMatrix4fArray>()) {
    const auto& single = primvar->values.UncheckedGet<VtMatrix4fArray>();
    VtMatrix4dArray transforms(single.size());
    std::transform(single.cbegin(), single.cend(), transforms.begin(),
                   [](const GfMatrix4f& m) { return GfMatrix4d(m); });
    return transforms;
  }
  return std::nullopt;
}

// `values` as an array of `T` if it holds an array of `Source`.
template <class T, class Source>
bool Converted(const VtValue& values, VtArray<T>& converted) {
  if (!values.IsHolding<VtArray<Source>>()) return false;
  const auto& held = values.UncheckedGet<VtArray<Source>>();
  converted.reserve(held.size());
  for (const Source& value : held) converted.push_back(T(value));
  return true;
}

// A point instancer's per-point array of `T`, or of one of the types `From` converted to it; empty when it has none.
template <class T, class... From>
VtArray<T> PointValues(const PrimRecord& instancer, const TfToken& name) {
  const PrimvarRecord* primvar = instancer.FindPrimvar(name);
  if (!primvar || primvar->indices) return {};
  VtArray<T> converted;
  Converted<T, T>(primvar->values, converted) || (Converted<T, From>(primvar->values, converted) || ...);
  return converted;
}

// Each point's transform in the instancer's space, as UsdGeomPointInstancer::ComputeInstanceTransformsAtTime composes
// it without the prototype root's transform, which the prototype's flattened matrices already hold: scale, then
// rotation, then translation, after any instance transform. Row vectors, as Gf's. The bridge's PointTransforms.
std::vector<GfMatrix4d> PointTransforms(const PrimRecord& instancer, std::size_t points) {
  const auto translations = PointValues<GfVec3d, GfVec3f, GfVec3h>(instancer, HdInstancerTokens->instanceTranslations);
  const auto rotations = PointValues<GfQuatd, GfQuatf, GfQuath>(instancer, HdInstancerTokens->instanceRotations);
  const auto scales = PointValues<GfVec3d, GfVec3f, GfVec3h>(instancer, HdInstancerTokens->instanceScales);
  const std::optional<VtMatrix4dArray> instanceTransforms = InstanceTransforms(instancer);
  std::vector<GfMatrix4d> transforms(points, GfMatrix4d(1.0));
  for (std::size_t i = 0; i < points; ++i) {
    GfMatrix4d& transform = transforms[i];
    if (instanceTransforms && i < instanceTransforms->size()) transform = (*instanceTransforms)[i];
    if (i < scales.size()) transform *= GfMatrix4d(1.0).SetScale(scales[i]);
    if (i < rotations.size()) transform *= GfMatrix4d(1.0).SetRotate(GfRotation(rotations[i]));
    if (i < translations.size()) transform *= GfMatrix4d(1.0).SetTranslate(translations[i]);
  }
  return transforms;
}

// The point-instance path element naming `point` (DECISIONS.md "Point instancers"): __id_<id> by its authored id,
// __id_n<id> for a negative one, or __index_<index> when the instancer authors no ids; empty for a point the authored
// ids leave out.
TfToken PointName(const PrimRecord& instancer, std::size_t point) {
  if (!instancer.pointIds) return TfToken("__index_" + std::to_string(point));
  if (point >= instancer.pointIds->size()) return {};
  const int64_t id = (*instancer.pointIds)[point];
  // The magnitude as unsigned, so the most negative id doesn't overflow.
  const uint64_t magnitude = id < 0 ? uint64_t{0} - static_cast<uint64_t>(id) : static_cast<uint64_t>(id);
  return TfToken((id < 0 ? "__id_n" : "__id_") + std::to_string(magnitude));
}

// The purposes with their own visibility. Built on first use, after Hydra's static tokens.
const std::array<TfToken, 3>& Purposes() {
  static const std::array<TfToken, 3> purposes{HdRenderTagTokens->guide, HdRenderTagTokens->proxy,
                                               HdRenderTagTokens->render};
  return purposes;
}

// The nearest authored opinion on `path` or its ancestors, below `stop`; null for none.
const TfToken* NearestOpinion(const PrimTable& table, SdfPath path, const SdfPath& stop, const TfToken& purpose) {
  for (; !path.IsEmpty() && path != stop && !path.IsAbsoluteRootPath(); path = path.GetParentPath())
    if (const PrimRecord* prim = table.Find(path))
      if (const TfToken* opinion = prim->PurposeVisibilityOf(purpose)) return opinion;
  return nullptr;
}

// The opinion for `purpose` among `opinions`; null for none.
const TfToken* Inherited(const PurposeVisibility& opinions, const TfToken& purpose) {
  for (const auto& [authored, visibility] : opinions)
    if (authored == purpose) return &visibility;
  return nullptr;
}

}  // namespace

const TfToken* PurposeVisibilityOpinion(const PrimTable& table, const PrimRecord& prim, const DrawnCopy& copy) {
  if (std::find(Purposes().begin(), Purposes().end(), prim.purpose) == Purposes().end()) return nullptr;
  const TfToken* opinion = NearestOpinion(table, prim.path, copy.hydraRoot, prim.purpose);
  return opinion ? opinion : Inherited(copy.purposeVisibility, prim.purpose);
}

bool EffectivelyVisible(const PrimTable& table, const PrimRecord& prim, const DrawnCopy& copy) {
  if (!prim.visible || !copy.visible) return false;
  if (std::find(Purposes().begin(), Purposes().end(), prim.purpose) == Purposes().end()) return true;
  const TfToken* opinion = PurposeVisibilityOpinion(table, prim, copy);
  if (!opinion) return prim.purpose != HdRenderTagTokens->guide;
  // A guide only when explicitly visible; a proxy or render prim unless invisible.
  return prim.purpose == HdRenderTagTokens->guide ? *opinion == UsdGeomTokens->visible
                                                  : *opinion != UsdGeomTokens->invisible;
}

InstanceResolver::InstanceResolver(const PrimTable& table, bool honorResets)
    : table_(table), honorResets_(honorResets) {}

const std::vector<DrawnCopy>& InstanceResolver::CopiesOf(const PrimRecord& prim) { return CopiesOf(prim, 0); }

bool InstanceResolver::ResetsBelow(SdfPath path, const SdfPath& prototypeRoot) const {
  if (!honorResets_ || prototypeRoot.IsAbsoluteRootPath()) return false;
  for (; !path.IsEmpty() && path != prototypeRoot && !path.IsAbsoluteRootPath(); path = path.GetParentPath())
    if (const PrimRecord* prim = table_.Find(path); prim && prim->resetsXformStack) return true;
  return false;
}

// CopiesOf, CopiesUnder, and Expand recurse once per nesting level, bounded by kMaxDepth.
const std::vector<DrawnCopy>& InstanceResolver::CopiesOf(const PrimRecord& prim,  // NOLINT(misc-no-recursion)
                                                         int depth) {
  if (!prim.instancedBy) return top_;
  const InstancedByRecord& by = *prim.instancedBy;
  // Native instancing gives each prototype copy exactly one instancer.
  if (by.instancers.size() != 1 || by.prototypeRoots.size() != 1) {
    Report(prim.path, DiagnosticCode::kUnsupportedInstancing,
           "Prims instanced by several instancers are not translated");
    return none_;
  }
  return CopiesUnder(by.instancers[0], by.prototypeRoots[0], depth);
}

const std::vector<DrawnCopy>& InstanceResolver::CopiesUnder(  // NOLINT(misc-no-recursion)
    const SdfPath& instancer, const SdfPath& prototypeRoot, int depth) {
  if (auto found = cache_.find(prototypeRoot); found != cache_.end()) return found->second;
  // Inserted before expanding, so a cycle in malformed data ends with no copies. References into an unordered_map
  // survive later insertions.
  std::vector<DrawnCopy>& copies = cache_[prototypeRoot];
  const PrimRecord* record = table_.Find(instancer);
  if (!record || !record->instancer)
    Report(instancer, DiagnosticCode::kInvalidInstancer, "The instancer is missing or has no topology");
  else if (depth > kMaxDepth)
    Report(instancer, DiagnosticCode::kInvalidInstancer, "Instancing nests too deeply");
  else
    copies = Expand(*record, *record->instancer, prototypeRoot, depth);
  return copies;
}

std::vector<DrawnCopy> InstanceResolver::Expand(  // NOLINT(misc-no-recursion)
    const PrimRecord& instancer, const InstancerRecord& topology, const SdfPath& prototypeRoot, int depth) {
  const auto found = std::find(topology.prototypes.cbegin(), topology.prototypes.cend(), prototypeRoot);
  const auto p = static_cast<std::size_t>(found - topology.prototypes.cbegin());
  if (found == topology.prototypes.cend() || p >= topology.instanceIndices.size()) {
    Report(instancer.path, DiagnosticCode::kInvalidInstancer,
           "Prototype root " + prototypeRoot.GetString() + " has no instances");
    return {};
  }
  // A point instancer has no instance locations (HdInstancerTopologySchema).
  const VtArray<SdfPath>& locations = topology.instanceLocations;
  if (locations.empty()) return ExpandPoints(instancer, topology, p, depth);
  const std::optional<VtMatrix4dArray> transforms = InstanceTransforms(instancer);
  if (!transforms) {
    Report(instancer.path, DiagnosticCode::kInvalidInstancer,
           "The native instancer has no unindexed instance transforms");
    return {};
  }
  const std::vector<DrawnCopy>& outers = CopiesOf(instancer, depth + 1);
  if (outers.empty()) return {};
  // The instances in range, each with what its instance root and its ancestors inside the outer prototype give it:
  // whether one resets the stack (WORKAROUND for OpenUSD #862), and the nearest purpose-visibility opinions. Every
  // outer copy has the same hydraRoot, so each is found once.
  struct Instance {
    std::size_t index;
    bool resets;
    std::array<const TfToken*, 3> opinions;  // per Purposes(); null for none
  };
  const SdfPath& outerRoot = outers.front().hydraRoot;
  std::vector<Instance> instances;
  bool invalidIndex = false;
  for (const int k : topology.instanceIndices[p]) {
    const auto index = static_cast<std::size_t>(k);
    if (k < 0 || index >= locations.size() || index >= transforms->size()) {
      invalidIndex = true;
      continue;
    }
    Instance instance{index, ResetsBelow(locations[index], outerRoot), {}};
    for (std::size_t i = 0; i < Purposes().size(); ++i)
      instance.opinions.at(i) = NearestOpinion(table_, locations[index], outerRoot, Purposes().at(i));
    instances.push_back(instance);
  }
  if (invalidIndex)
    Report(instancer.path, DiagnosticCode::kInvalidInstancer, "Instance indices out of range were skipped");
  const VtBoolArray& mask = topology.mask;
  std::vector<DrawnCopy> copies;
  copies.reserve(outers.size() * instances.size());
  for (const DrawnCopy& outer : outers) {
    for (const auto& [index, resets, opinions] : instances) {
      DrawnCopy copy;
      copy.hydraRoot = prototypeRoot;
      copy.usdRoot = outer.Map(locations[index]);
      copy.context = outer.context;
      copy.context.push_back(copy.usdRoot);
      copy.hydraInstanceRoot = locations[index];
      // Row vectors: the instance's own transform first, then the outer copy's, unless it resets.
      const GfMatrix4d& own = (*transforms)[index];
      copy.world = resets ? own : own * outer.world;
      // The mask already folds in the instance root's flattened visibility, its ancestors' included.
      copy.visible = outer.visible && (mask.empty() || (index < mask.size() && mask[index]));
      // Each purpose's nearest opinion inside the outer prototype, else the outer copy's.
      for (std::size_t i = 0; i < Purposes().size(); ++i) {
        const TfToken* opinion = opinions.at(i);
        if (!opinion) opinion = Inherited(outer.purposeVisibility, Purposes().at(i));
        if (opinion) copy.purposeVisibility.emplace_back(Purposes().at(i), *opinion);
      }
      copies.push_back(std::move(copy));
    }
  }
  return copies;
}

std::vector<DrawnCopy> InstanceResolver::ExpandPoints(  // NOLINT(misc-no-recursion)
    const PrimRecord& instancer, const InstancerRecord& topology, std::size_t p, int depth) {
  const SdfPath& prototypeRoot = topology.prototypes[p];
  // Hydra copies each prototype under its original root as ForInstancer<hash>, so the original names the copies.
  if (!TfStringStartsWith(prototypeRoot.GetName(), "ForInstancer")) {
    Report(instancer.path, DiagnosticCode::kInvalidInstancer,
           "Prototype " + prototypeRoot.GetString() + " is not a propagated copy");
    return {};
  }
  const std::vector<DrawnCopy>& outers = CopiesOf(instancer, depth + 1);
  if (outers.empty()) return {};
  std::size_t points = topology.mask.size();
  for (const VtIntArray& indices : topology.instanceIndices)
    for (const int k : indices) points = std::max(points, static_cast<std::size_t>(std::max(k, 0)) + 1);
  const std::vector<GfMatrix4d> transforms = PointTransforms(instancer, points);
  // What the instancer and its ancestors inside the outer prototype give each copy, found once, as Expand does.
  const SdfPath& outerRoot = outers.front().hydraRoot;
  const bool resets = ResetsBelow(instancer.path, outerRoot);
  std::array<const TfToken*, 3> opinions{};
  for (std::size_t i = 0; i < Purposes().size(); ++i)
    opinions.at(i) = NearestOpinion(table_, instancer.path, outerRoot, Purposes().at(i));
  const GfMatrix4d local = instancer.matrix.value_or(GfMatrix4d(1.0));
  const VtBoolArray& mask = topology.mask;
  const TfToken prototypeName = prototypeRoot.GetParentPath().GetNameToken();
  std::vector<DrawnCopy> copies;
  bool invalidPoint = false;
  for (const DrawnCopy& outer : outers) {
    const SdfPath instancerPath = outer.Map(instancer.path);
    // The instancer's world transform in the outer copy, unless it or an ancestor inside the outer prototype resets
    // the stack (WORKAROUND for OpenUSD #862).
    const GfMatrix4d world = resets ? local : local * outer.world;
    for (const int k : topology.instanceIndices[p]) {
      const auto point = static_cast<std::size_t>(k);
      const TfToken name = k < 0 || point >= transforms.size() ? TfToken() : PointName(instancer, point);
      if (name.IsEmpty()) {
        invalidPoint = true;
        continue;
      }
      DrawnCopy copy;
      copy.hydraRoot = prototypeRoot;
      // The point-instance path's root: the instancer, the point, then the prototype root's name.
      copy.usdRoot = instancerPath.AppendChild(name).AppendChild(prototypeName);
      copy.context = outer.context;
      copy.context.push_back(instancerPath);
      copy.context.push_back(instancerPath.AppendChild(name));
      copy.world = transforms[point] * world;
      copy.visible = outer.visible && instancer.visible && (mask.empty() || (point < mask.size() && mask[point]));
      for (std::size_t i = 0; i < Purposes().size(); ++i) {
        const TfToken* opinion = opinions.at(i);
        if (!opinion) opinion = Inherited(outer.purposeVisibility, Purposes().at(i));
        if (opinion) copy.purposeVisibility.emplace_back(Purposes().at(i), *opinion);
      }
      copies.push_back(std::move(copy));
    }
  }
  if (invalidPoint)
    Report(instancer.path, DiagnosticCode::kInvalidInstancer,
           "Points out of range, or without an authored id, were skipped");
  return copies;
}

void InstanceResolver::Report(const SdfPath& hydraPath, DiagnosticCode code, const std::string& message) {
  diagnostics_.push_back({code, SdfPath(), message + " (Hydra prim " + hydraPath.GetString() + ")", {}, {}, {}});
}

}  // namespace proscenium
