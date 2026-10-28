#include "instancing.h"

#include <pxr/base/gf/half.h>
#include <pxr/base/gf/matrix4f.h>
#include <pxr/base/gf/vec2d.h>
#include <pxr/base/gf/vec2f.h>
#include <pxr/base/gf/vec2i.h>
#include <pxr/base/gf/vec3d.h>
#include <pxr/base/gf/vec3f.h>
#include <pxr/base/gf/vec3h.h>
#include <pxr/base/gf/vec3i.h>
#include <pxr/base/gf/vec4d.h>
#include <pxr/base/gf/vec4f.h>
#include <pxr/base/gf/vec4i.h>
#include <pxr/imaging/hd/primvarSchema.h>
#include <pxr/imaging/hd/tokens.h>

#include <algorithm>
#include <array>
#include <optional>

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

InstanceResolver::InstanceResolver(const PrimTable &table, Diagnostics &diagnostics)
    : table_(table),
      diagnostics_(diagnostics) {}

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
    // Point instancers have no instance locations: their identity is (instancer, point index). They aren't
    // translated: the planner gives the point instancer itself a placeholder and diagnostic.
    if (topology.instanceLocations.empty()) return {};
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
            Frame frame;
            frame.hydraRoot = prototypeRoot;
            frame.usdRoot = outer.Map(topology.instanceLocations[index]);
            frame.context = outer.context;
            frame.context.push_back(frame.usdRoot);
            // Row vectors: the instance's own transform first, then the frame it sits in.
            frame.world = (*transforms)[index] * outer.world;
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
            const SdfPath &location = topology.instanceLocations[index];
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
            // Opinions at or above the instance root, inside the outer prototype, then the outer frame's.
            for (const TfToken &purpose : Purposes()) {
                const TfToken *opinion =
                    NearestOpinion(table_, topology.instanceLocations[index], outer.hydraRoot, purpose);
                if (!opinion) opinion = Inherited(outer.purposeVisibility, purpose);
                if (opinion) frame.purposeVisibility.emplace_back(purpose, *opinion);
            }
            // An inner instance root is nearer the prim than an outer one, so its values win.
            for (const auto &inherited : outer.instancePrimvars) {
                auto same = [&](const auto &entry) { return entry.first == inherited.first; };
                if (std::none_of(frame.instancePrimvars.begin(), frame.instancePrimvars.end(), same))
                    frame.instancePrimvars.push_back(inherited);
            }
            frames.push_back(std::move(frame));
        }
    }
    if (invalidIndex) Report(instancer, "invalid-instancer", "Instance indices out of range were skipped");
    if (invalidPrimvar)
        Report(instancer, "invalid-primvar", "Instance-root primvars with invalid indices were skipped");
    return frames;
}

// Instancers are reported by Hydra path: a native instancer has no USD counterpart.
void InstanceResolver::Report(const PrimRecord &prim, const std::string &code, const std::string &message) {
    diagnostics_.push_back({Severity::Error, code, SdfPath(), message + " (Hydra prim " + prim.path.GetString() + ")"});
}

}  // namespace hydra_bridge
