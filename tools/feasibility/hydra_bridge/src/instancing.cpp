#include "instancing.h"

#include <pxr/base/gf/matrix4f.h>
#include <pxr/base/gf/vec2f.h>
#include <pxr/base/gf/vec3d.h>
#include <pxr/base/gf/vec3f.h>
#include <pxr/base/gf/vec4f.h>
#include <pxr/imaging/hd/primvarSchema.h>
#include <pxr/imaging/hd/tokens.h>

#include <algorithm>
#include <optional>

PXR_NAMESPACE_USING_DIRECTIVE

namespace hydra_bridge {

namespace {

// Deeper nesting than any real scene; malformed data must not recurse without bound.
constexpr int kMaxDepth = 64;

// Element k of an instance-rate primvar, as a one-element array. Empty for an unsupported type;
// `invalid` is set when k or its index is out of range.
template <class T>
bool TryElement(const PrimvarRecord &primvar, size_t k, VtValue &out, bool &invalid) {
    if (!primvar.values.IsHolding<VtArray<T>>()) return false;
    const auto &values = primvar.values.UncheckedGet<VtArray<T>>();
    size_t element = k;
    if (primvar.indices) {
        if (k >= primvar.indices->size() || (*primvar.indices)[k] < 0) return invalid = true;
        element = static_cast<size_t>((*primvar.indices)[k]);
    }
    if (element >= values.size()) return invalid = true;
    out = VtValue(VtArray<T>(1, values[element]));
    return true;
}

template <class... Ts>
VtValue ElementAt(const PrimvarRecord &primvar, size_t k, bool &invalid) {
    VtValue out;
    (TryElement<Ts>(primvar, k, out, invalid) || ...);
    return out;
}

std::optional<VtMatrix4dArray> InstanceTransforms(const PrimRecord &instancer) {
    const PrimvarRecord *primvar = instancer.FindPrimvar(HdInstancerTokens->instanceTransforms);
    if (!primvar || primvar->indices) return std::nullopt;
    if (primvar->values.IsHolding<VtMatrix4dArray>()) return primvar->values.UncheckedGet<VtMatrix4dArray>();
    if (primvar->values.IsHolding<VtMatrix4fArray>()) {
        const auto &single = primvar->values.UncheckedGet<VtMatrix4fArray>();
        VtMatrix4dArray transforms(single.size());
        std::transform(single.cbegin(), single.cend(), transforms.begin(), [](const GfMatrix4f &m) { return GfMatrix4d(m); });
        return transforms;
    }
    return std::nullopt;
}

}  // namespace

InstanceResolver::InstanceResolver(const PrimTable &table, Diagnostics &diagnostics)
    : table_(table), diagnostics_(diagnostics) {}

const std::vector<Frame> &InstanceResolver::FramesOf(const PrimRecord &prim) { return FramesOf(prim, 0); }

const std::vector<Frame> &InstanceResolver::FramesOf(const PrimRecord &prim, int depth) {
    if (!prim.instancedBy) return top_;
    const InstancedByRecord &by = *prim.instancedBy;
    // Native instancing gives each prototype copy exactly one instancer.
    if (by.instancers.size() != 1 || by.prototypeRoots.size() != 1) {
        Report(prim, "unsupported-instancing", "Prims instanced by several instancers are not translated");
        return none_;
    }
    return FramesUnder(by.instancers[0], by.prototypeRoots[0], depth);
}

const std::vector<Frame> &InstanceResolver::FramesUnder(const SdfPath &instancerPath, const SdfPath &prototypeRoot,
                                                        int depth) {
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

std::vector<Frame> InstanceResolver::Expand(const PrimRecord &instancer, const SdfPath &prototypeRoot, int depth) {
    const InstancerRecord &topology = *instancer.instancer;
    auto prototype = std::find(topology.prototypes.begin(), topology.prototypes.end(), prototypeRoot);
    const auto p = static_cast<size_t>(prototype - topology.prototypes.begin());
    if (prototype == topology.prototypes.end() || p >= topology.instanceIndices.size()) {
        Report(instancer, "invalid-instancer", "Prototype root " + prototypeRoot.GetString() + " has no instances");
        return {};
    }
    // Point instancers have no instance locations: their identity is (instancer, point index).
    if (topology.instanceLocations.empty()) {
        Report(instancer, "unsupported-point-instancer", "Point instancers are not translated by the prototype");
        return {};
    }
    std::optional<VtMatrix4dArray> transforms = InstanceTransforms(instancer);
    if (!transforms) {
        Report(instancer, "invalid-instancer", "Native instancer has no instance transforms");
        return {};
    }
    std::vector<const PrimvarRecord *> perInstance;
    for (const PrimvarRecord &primvar : instancer.primvars)
        if (primvar.interpolation == HdPrimvarSchemaTokens->instance && primvar.name != HdInstancerTokens->instanceTransforms)
            perInstance.push_back(&primvar);

    std::vector<Frame> frames;
    bool invalidIndex = false, invalidPrimvar = false;
    for (const Frame &outer : FramesOf(instancer, depth + 1)) {
        for (int k : topology.instanceIndices[p]) {
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
            frame.visible = outer.visible && (topology.mask.empty() || (index < topology.mask.size() && topology.mask[index]));
            for (const PrimvarRecord *primvar : perInstance) {
                VtValue value = ElementAt<GfVec3f, GfVec4f, GfVec2f, GfVec3d, float, double, int>(*primvar, index,
                                                                                                  invalidPrimvar);
                if (!value.IsEmpty()) frame.instancePrimvars.emplace_back(primvar->name, std::move(value));
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
    if (invalidPrimvar) Report(instancer, "invalid-primvar", "Per-instance primvar indices out of range were skipped");
    return frames;
}

// Instancers are reported by Hydra path: a native instancer has no USD counterpart.
void InstanceResolver::Report(const PrimRecord &prim, const std::string &code, const std::string &message) {
    diagnostics_.push_back({Severity::Error, code, SdfPath(), message + " (Hydra prim " + prim.path.GetString() + ")"});
}

}  // namespace hydra_bridge
