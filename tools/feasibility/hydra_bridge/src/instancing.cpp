#include "instancing.h"

#include <pxr/base/gf/half.h>
#include <pxr/base/gf/matrix2d.h>
#include <pxr/base/gf/matrix2f.h>
#include <pxr/base/gf/matrix3d.h>
#include <pxr/base/gf/matrix3f.h>
#include <pxr/base/gf/matrix4f.h>
#include <pxr/base/gf/quatd.h>
#include <pxr/base/gf/quatf.h>
#include <pxr/base/gf/quath.h>
#include <pxr/base/gf/rotation.h>
#include <pxr/base/gf/vec2d.h>
#include <pxr/base/gf/vec2f.h>
#include <pxr/base/gf/vec2h.h>
#include <pxr/base/gf/vec2i.h>
#include <pxr/base/gf/vec3d.h>
#include <pxr/base/gf/vec3f.h>
#include <pxr/base/gf/vec3h.h>
#include <pxr/base/gf/vec3i.h>
#include <pxr/base/gf/vec4d.h>
#include <pxr/base/gf/vec4f.h>
#include <pxr/base/gf/vec4h.h>
#include <pxr/base/gf/vec4i.h>
#include <pxr/base/tf/stringUtils.h>
#include <pxr/imaging/hd/primvarSchema.h>
#include <pxr/imaging/hd/tokens.h>

#include <algorithm>
#include <array>
#include <cstdint>
#include <optional>
#include <string>

PXR_NAMESPACE_USING_DIRECTIVE

namespace hydra_bridge {

namespace {

// Deeper nesting than any real scene; malformed data must not recurse without bound.
constexpr int kMaxDepth = 64;

std::optional<VtMatrix4dArray> InstanceTransforms(const PrimRecord &instancer) {
    const PrimvarRecord *primvar = instancer.FindPrimvar(HdInstancerTokens->instanceTransforms);
    if (!primvar || primvar->indices) return std::nullopt;
    if (primvar->values.IsHolding<VtMatrix4dArray>()) return primvar->values.UncheckedGet<VtMatrix4dArray>();
    if (primvar->values.IsHolding<VtMatrix4fArray>()) {
        const auto &single = primvar->values.UncheckedGet<VtMatrix4fArray>();
        VtMatrix4dArray transforms(single.size());
        std::transform(single.cbegin(), single.cend(), transforms.begin(),
                       [](const GfMatrix4f &m) { return GfMatrix4d(m); });
        return transforms;
    }
    return std::nullopt;
}

// `values` converted to an array of `T` if it holds an array of `Source`.
template <class T, class Source>
bool Converted(const VtValue &values, VtArray<T> &converted) {
    if (!values.IsHolding<VtArray<Source>>()) return false;
    const auto &held = values.UncheckedGet<VtArray<Source>>();
    converted.reserve(held.size());
    for (const Source &value : held) converted.push_back(T(value));
    return true;
}

// A point instancer's per-point array of `T`, or of one of the types `From` converted to it; empty when it has
// none.
template <class T, class... From>
VtArray<T> PointValues(const PrimRecord &instancer, const TfToken &name) {
    const PrimvarRecord *primvar = instancer.FindPrimvar(name);
    if (!primvar || primvar->indices) return {};
    VtArray<T> converted;
    Converted<T, T>(primvar->values, converted) || (Converted<T, From>(primvar->values, converted) || ...);
    return converted;
}

// Each point's transform in the instancer's space, as UsdGeomPointInstancer::ComputeInstanceTransformsAtTime
// composes it without the prototype root's transform, which the prototype's flattened matrices already hold:
// scale, then rotation, then translation, after any instance transform. Row vectors, as Gf's.
std::vector<GfMatrix4d> PointTransforms(const PrimRecord &instancer, size_t points) {
    const auto translations =
        PointValues<GfVec3d, GfVec3f, GfVec3h>(instancer, HdInstancerTokens->instanceTranslations);
    const auto rotations = PointValues<GfQuatd, GfQuatf, GfQuath>(instancer, HdInstancerTokens->instanceRotations);
    const auto scales = PointValues<GfVec3d, GfVec3f, GfVec3h>(instancer, HdInstancerTokens->instanceScales);
    const std::optional<VtMatrix4dArray> instanceTransforms = InstanceTransforms(instancer);
    std::vector<GfMatrix4d> transforms(points, GfMatrix4d(1.0));
    for (size_t i = 0; i < points; ++i) {
        GfMatrix4d &transform = transforms[i];
        if (instanceTransforms && i < instanceTransforms->size()) transform = (*instanceTransforms)[i];
        if (i < scales.size()) transform *= GfMatrix4d(1.0).SetScale(scales[i]);
        if (i < rotations.size()) transform *= GfMatrix4d(1.0).SetRotate(GfRotation(rotations[i]));
        if (i < translations.size()) transform *= GfMatrix4d(1.0).SetTranslate(translations[i]);
    }
    return transforms;
}

template <class... Types>
struct TypeList {};

// Types a point's primvar value can take, as properties.cpp converts constant primvars.
using PointTypes =
    TypeList<bool, int, unsigned char, unsigned int, int64_t, uint64_t, GfHalf, float, double, std::string, TfToken,
             GfVec2i, GfVec3i, GfVec4i, GfVec2h, GfVec3h, GfVec4h, GfVec2f, GfVec3f, GfVec4f, GfVec2d, GfVec3d, GfVec4d,
             GfMatrix2f, GfMatrix3f, GfMatrix4f, GfMatrix2d, GfMatrix3d, GfMatrix4d>;

bool PointValue(const VtValue &, size_t, VtValue &, TypeList<>) { return false; }

// One point's value of a flattened per-point primvar, as a one-element array: a constant primvar's form.
template <class T, class... Rest>
bool PointValue(const VtValue &values, size_t point, VtValue &value, TypeList<T, Rest...>) {
    if (!values.IsHolding<VtArray<T>>()) return PointValue(values, point, value, TypeList<Rest...>{});
    const auto &elements = values.UncheckedGet<VtArray<T>>();
    if (point >= elements.size()) return false;
    value = VtValue(VtArray<T>(1, elements[point]));
    return true;
}

// The purposes with their own visibility. Built on first use, after Hydra's static tokens.
const std::array<TfToken, 3> &Purposes() {
    static const std::array<TfToken, 3> purposes{HdRenderTagTokens->guide, HdRenderTagTokens->proxy,
                                                 HdRenderTagTokens->render};
    return purposes;
}

// The nearest authored opinion on `path` or its ancestors, below `stop`; null for none.
const TfToken *NearestOpinion(const PrimTable &table, SdfPath path, const SdfPath &stop, const TfToken &purpose) {
    for (; !path.IsEmpty() && path != stop && !path.IsAbsoluteRootPath(); path = path.GetParentPath()) {
        if (const PrimRecord *prim = table.Find(path))
            if (const TfToken *opinion = prim->PurposeVisibilityOf(purpose)) return opinion;
    }
    return nullptr;
}

// The opinion for `purpose` among `opinions`; null for none.
const TfToken *Inherited(const PurposeVisibility &opinions, const TfToken &purpose) {
    for (const auto &[authored, visibility] : opinions)
        if (authored == purpose) return &visibility;
    return nullptr;
}

// What a frame inherits from its outer frame, once its own values are set: for each purpose, the nearest
// visibility opinion at or above `root` (its instance root or point instancer) inside the outer prototype, else
// the outer frame's; and each of the outer frame's instance primvars the frame doesn't set, since an inner
// instance root is nearer the prim than an outer one.
void Inherit(const PrimTable &table, const SdfPath &root, const Frame &outer, Frame &frame) {
    for (const TfToken &purpose : Purposes()) {
        const TfToken *opinion = NearestOpinion(table, root, outer.hydraRoot, purpose);
        if (!opinion) opinion = Inherited(outer.purposeVisibility, purpose);
        if (opinion) frame.purposeVisibility.emplace_back(purpose, *opinion);
    }
    for (const auto &inherited : outer.instancePrimvars) {
        auto same = [&](const auto &entry) { return entry.first == inherited.first; };
        if (std::none_of(frame.instancePrimvars.begin(), frame.instancePrimvars.end(), same))
            frame.instancePrimvars.push_back(inherited);
    }
}

using Bindings = std::vector<std::pair<TfToken, SdfPath>>;

// The binding for `purpose`; null if there is none, and an empty path for a binding to nothing.
const SdfPath *FindBinding(const Bindings &bindings, const TfToken &purpose) {
    for (const auto &[bound, material] : bindings)
        if (bound == purpose) return &material;
    return nullptr;
}

bool Contains(const TfTokenVector &tokens, const TfToken &token) {
    return std::find(tokens.begin(), tokens.end(), token) != tokens.end();
}

// Whether `path` or an ancestor below `stop` has `purpose` in the token list `field` selects.
bool AuthoredBelow(const PrimTable &table, SdfPath path, const SdfPath &stop, const TfToken &purpose,
                   TfTokenVector PrimRecord::*field) {
    for (; !path.IsEmpty() && path != stop && !path.IsAbsoluteRootPath(); path = path.GetParentPath())
        if (const PrimRecord *prim = table.Find(path); prim && Contains(prim->*field, purpose)) return true;
    return false;
}

// The binding for exactly `purpose`, without the allPurpose fallback, as BoundMaterial describes; nullopt
// when nothing binds that purpose. A value can be an empty path, which binds nothing and ends the search.
std::optional<SdfPath> CorrectedBinding(const PrimTable &, const PrimRecord &prim, const Frame &frame,
                                        const TfToken &purpose) {
    const SdfPath *own = FindBinding(prim.usdBindings, purpose);
    const SdfPath *fromRoot = frame.context.empty() ? nullptr : FindBinding(frame.bindings, purpose);
    // A strong binding at or above the instance root beats anything the prototype authors.
    if (fromRoot && Contains(frame.strongPurposes, purpose)) return *fromRoot;
    if (own) return *own;
    if (fromRoot) return *fromRoot;
    return std::nullopt;
}

}  // namespace

SdfPath BoundMaterial(const PrimTable &table, const PrimRecord &prim, const Frame &frame, const TfToken &purpose) {
    // As UsdShade: the purpose across the whole hierarchy first, then allPurpose.
    for (const TfToken &tried : {purpose, TfToken()})
        if (std::optional<SdfPath> material = CorrectedBinding(table, prim, frame, tried)) return *material;
    return {};
}

bool EffectivelyVisible(const PrimTable &table, const PrimRecord &prim, const Frame &frame) {
    if (!prim.visible || !frame.visible) return false;
    const TfToken &purpose = prim.purpose;
    if (std::find(Purposes().begin(), Purposes().end(), purpose) == Purposes().end()) return true;
    const TfToken *opinion = NearestOpinion(table, prim.path, frame.hydraRoot, purpose);
    if (!opinion) opinion = Inherited(frame.purposeVisibility, purpose);
    if (!opinion) return purpose != HdRenderTagTokens->guide;
    // The nearest authored opinion decides, "inherited" included, as in UsdGeom. A guide displays only when
    // it is explicitly visible (spec VIS-04); proxy and render prims unless invisible.
    static const TfToken kVisible("visible"), kInvisible("invisible");
    return purpose == HdRenderTagTokens->guide ? *opinion == kVisible : *opinion != kInvisible;
}

TfToken PointName(size_t point) { return TfToken("__point_" + std::to_string(point)); }

bool ResetsBelow(const PrimTable &table, SdfPath path, const SdfPath &prototypeRoot) {
    for (; !path.IsEmpty() && path != prototypeRoot && !path.IsAbsoluteRootPath(); path = path.GetParentPath())
        if (const PrimRecord *prim = table.Find(path); prim && prim->resetsXformStack) return true;
    return false;
}

InstanceResolver::InstanceResolver(const PrimTable &table, Diagnostics &diagnostics, bool pointInstancers)
    : table_(table),
      diagnostics_(diagnostics),
      pointInstancers_(pointInstancers) {}

const std::vector<Frame> &InstanceResolver::FramesOf(const PrimRecord &prim) { return FramesOf(prim, 0); }

// FramesOf, FramesUnder, and Expand recurse once per nesting level, bounded by kMaxDepth.
const std::vector<Frame> &InstanceResolver::FramesOf(const PrimRecord &prim,  // NOLINT(misc-no-recursion)
                                                     int depth) {
    if (!prim.instancedBy) return top_;
    const InstancedByRecord &by = *prim.instancedBy;
    // Native instancing gives each prototype copy exactly one instancer.
    if (by.instancers.size() != 1 || by.prototypeRoots.size() != 1) {
        Report(prim, "unsupported-instancing", "Prims instanced by several instancers are not translated");
        return none_;
    }
    return FramesUnder(by.instancers[0], by.prototypeRoots[0], depth);
}

const std::vector<Frame> &InstanceResolver::FramesUnder(  // NOLINT(misc-no-recursion)
    const SdfPath &instancerPath, const SdfPath &prototypeRoot, int depth) {
    if (auto found = cache_.find(prototypeRoot); found != cache_.end()) return found->second;
    // Inserted before expanding, so a cycle in malformed data ends with no frames. References into
    // an unordered_map survive later insertions.
    std::vector<Frame> &frames = cache_[prototypeRoot];
    const PrimRecord *instancer = table_.Find(instancerPath);
    if (!instancer || !instancer->instancer) {
        diagnostics_.push_back({Severity::Error, "invalid-instancer", SdfPath(),
                                "Hydra instancer " + instancerPath.GetString() + " is missing or has no topology"});
    } else if (depth > kMaxDepth) {
        Report(*instancer, "invalid-instancer", "Instancing nests too deeply");
    } else {
        frames = Expand(*instancer, prototypeRoot, depth);
    }
    return frames;
}

std::vector<Frame> InstanceResolver::Expand(  // NOLINT(misc-no-recursion)
    const PrimRecord &instancer, const SdfPath &prototypeRoot, int depth) {
    const InstancerRecord &topology = *instancer.instancer;
    auto prototype = std::find(topology.prototypes.begin(), topology.prototypes.end(), prototypeRoot);
    const auto p = static_cast<size_t>(prototype - topology.prototypes.begin());
    if (prototype == topology.prototypes.end() || p >= topology.instanceIndices.size()) {
        Report(instancer, "invalid-instancer", "Prototype root " + prototypeRoot.GetString() + " has no instances");
        return {};
    }
    // Point instancers have no instance locations: their identity is (instancer, point index). Without
    // pointInstancers_, the planner gives the point instancer itself a placeholder and diagnostic.
    if (topology.instanceLocations.empty())
        return pointInstancers_ ? ExpandPoints(instancer, topology, p, depth) : none_;
    std::optional<VtMatrix4dArray> transforms = InstanceTransforms(instancer);
    if (!transforms) {
        Report(instancer, "invalid-instancer", "Native instancer has no instance transforms");
        return {};
    }
    std::vector<Frame> frames;
    bool invalidIndex = false, invalidPrimvar = false;
    for (const Frame &outer : FramesOf(instancer, depth + 1)) {
        for (const int k : topology.instanceIndices[p]) {
            const auto index = static_cast<size_t>(k);
            if (k < 0 || index >= topology.instanceLocations.size() || index >= transforms->size()) {
                invalidIndex = true;
                continue;
            }
            const SdfPath &location = topology.instanceLocations[index];
            Frame frame;
            frame.hydraRoot = prototypeRoot;
            frame.usdRoot = outer.Map(location);
            frame.context = outer.context;
            frame.context.push_back(frame.usdRoot);
            // Row vectors: the instance's own transform first, then the frame it sits in, unless the instance root
            // or an ancestor inside the outer prototype resets the stack (WORKAROUND for OpenUSD #862).
            frame.world = ResetsBelow(table_, location, outer.hydraRoot) ? (*transforms)[index]
                                                                         : (*transforms)[index] * outer.world;
            frame.visible =
                outer.visible && (topology.mask.empty() || (index < topology.mask.size() && topology.mask[index]));
            // The instance root's own constant primvars, flattened within its namespace, with the type and
            // shape USD authored. Hydra's instancer has them too, as instance-rate primvars, but its
            // aggregation keeps only the first element of an array value and takes names and types from the
            // first instance (v26.03 niInstanceAggregationSceneIndex.cpp).
            if (const PrimRecord *rootRecord = table_.Find(topology.instanceLocations[index])) {
                for (const PrimvarRecord &primvar : rootRecord->primvars) {
                    if (primvar.interpolation != HdPrimvarSchemaTokens->constant) continue;
                    VtValue value;
                    std::string error;
                    if (FlattenedConstant(primvar, value, error))
                        frame.instancePrimvars.emplace_back(primvar.name, std::move(value));
                    else
                        invalidPrimvar = true;
                }
            }
            static const std::array kPurposesBound{TfToken(), TfToken("preview"), TfToken("full")};
            if (const PrimRecord *root = table_.Find(location)) {
                for (const TfToken &purpose : kPurposesBound) {
                    if (std::optional<SdfPath> material = CorrectedBinding(table_, *root, outer, purpose))
                        frame.bindings.emplace_back(purpose, std::move(*material));
                    // Strong at the instance root or above it inside the outer prototype, or above that.
                    if (Contains(outer.strongPurposes, purpose) ||
                        AuthoredBelow(table_, location, outer.hydraRoot, purpose, &PrimRecord::strongBindingPurposes))
                        frame.strongPurposes.push_back(purpose);
                }
            }
            // The mask already folds in the instance root's flattened visibility, its ancestors included.
            Inherit(table_, location, outer, frame);
            frames.push_back(std::move(frame));
        }
    }
    if (invalidIndex) Report(instancer, "invalid-instancer", "Instance indices out of range were skipped");
    if (invalidPrimvar)
        Report(instancer, "invalid-primvar", "Instance-root primvars with invalid indices were skipped");
    return frames;
}

std::vector<Frame> InstanceResolver::ExpandPoints(  // NOLINT(misc-no-recursion)
    const PrimRecord &instancer, const InstancerRecord &topology, size_t prototype, int depth) {
    const SdfPath &prototypeRoot = topology.prototypes[prototype];
    // Hydra copies each prototype under its original, as ForInstancer<hash>, so the original is its source.
    if (!TfStringStartsWith(prototypeRoot.GetName(), "ForInstancer")) {
        Report(instancer, "invalid-instancer", "Prototype " + prototypeRoot.GetString() + " is not a propagated copy");
        return {};
    }
    size_t points = topology.mask.size();
    for (const VtIntArray &indices : topology.instanceIndices)
        for (const int k : indices) points = std::max(points, static_cast<size_t>(std::max(k, 0)) + 1);
    const std::vector<GfMatrix4d> transforms = PointTransforms(instancer, points);
    // One value per point of the instancer's per-point primvars, which USD authors as vertex or varying
    // primvars on the instancer and Hydra gives instance interpolation; each copy takes its point's, as an
    // instance's primvar. Hydra's own per-point transforms aren't primvars of the copies, and the instancer's
    // constant primvars Hydra already gives the prototype copies, as their ancestor's.
    std::vector<std::pair<TfToken, VtValue>> perPoint;
    bool invalidPrimvar = false;
    for (const PrimvarRecord &primvar : instancer.primvars) {
        if (primvar.interpolation != HdPrimvarSchemaTokens->instance ||
            TfStringStartsWith(primvar.name.GetString(), "hydra:"))
            continue;
        VtValue value;
        std::string error;
        if (FlattenedConstant(primvar, value, error))
            perPoint.emplace_back(primvar.name, std::move(value));
        else
            invalidPrimvar = true;
    }
    std::vector<Frame> frames;
    bool invalidIndex = false;
    for (const Frame &outer : FramesOf(instancer, depth + 1)) {
        const SdfPath instancerPath = outer.Map(instancer.path);
        const SdfPath usdRoot = outer.Map(prototypeRoot.GetParentPath());
        // The instancer's world transform in this frame, unless it or an ancestor inside the outer prototype resets
        // the stack (WORKAROUND for OpenUSD #862).
        const GfMatrix4d local = instancer.matrix.value_or(GfMatrix4d(1.0));
        const GfMatrix4d world = ResetsBelow(table_, instancer.path, outer.hydraRoot) ? local : local * outer.world;
        for (const int k : topology.instanceIndices[prototype]) {
            const auto point = static_cast<size_t>(k);
            if (k < 0 || point >= transforms.size()) {
                invalidIndex = true;
                continue;
            }
            Frame frame;
            frame.hydraRoot = prototypeRoot;
            frame.usdRoot = usdRoot;
            frame.context = outer.context;
            frame.context.push_back(instancerPath);
            frame.context.push_back(instancerPath.AppendChild(PointName(point)));
            frame.world = transforms[point] * world;
            frame.visible = outer.visible && instancer.visible &&
                            (topology.mask.empty() || (point < topology.mask.size() && topology.mask[point]));
            for (const auto &[name, values] : perPoint) {
                VtValue value;
                if (PointValue(values, point, value, PointTypes{}))
                    frame.instancePrimvars.emplace_back(name, std::move(value));
                else
                    invalidPrimvar = true;
            }
            // The prototypes are the instancer's descendants, so the bindings UsdShade resolves on them already
            // include the instancer's and its ancestors' inside the outer prototype; above that, the outer frame's.
            frame.bindings = outer.bindings;
            frame.strongPurposes = outer.strongPurposes;
            Inherit(table_, instancer.path, outer, frame);
            frames.push_back(std::move(frame));
        }
    }
    if (invalidIndex) Report(instancer, "invalid-instancer", "Point indices out of range were skipped");
    if (invalidPrimvar)
        Report(instancer, "invalid-primvar", "Point instancer primvars with invalid indices or types were skipped");
    return frames;
}

// Instancers are reported by Hydra path: a native instancer has no USD counterpart.
void InstanceResolver::Report(const PrimRecord &prim, const std::string &code, const std::string &message) {
    diagnostics_.push_back({Severity::Error, code, SdfPath(), message + " (Hydra prim " + prim.path.GetString() + ")"});
}

}  // namespace hydra_bridge
