// BuildPlan: meshes with material slots, objects per drawn copy, placeholders, and diagnostics.
#include "fact_timings.h"
#include "instancing.h"
#include "mesh_builder.h"
#include "plan.h"
#include "prim_reader.h"

#include <pxr/base/work/loops.h>
#include <pxr/imaging/hd/primvarSchema.h>
#include <pxr/imaging/hd/tokens.h>
#include <pxr/imaging/pxOsd/tokens.h>

#include <algorithm>
#include <array>
#include <optional>
#include <set>
#include <unordered_map>
#include <utility>
#include <vector>

PXR_NAMESPACE_USING_DIRECTIVE

namespace hydra_bridge {

namespace {

// USD types the scene-index graph converts to meshes inexactly: curved implicit surfaces become fixed coarse
// cages, and NURBS patches their control hull. Hydra itself gives no signal.
bool Approximated(const TfToken &usdTypeName) {
    static const std::array kTypes{TfToken("Sphere"), TfToken("Cone"), TfToken("Cylinder"), TfToken("Capsule"),
                                   TfToken("NurbsPatch")};
    return std::find(kTypes.begin(), kTypes.end(), usdTypeName) != kTypes.end();
}

// Geometry the prototype draws only as a placeholder.
bool Untranslated(const TfToken &type) {
    return type != HdPrimTypeTokens->mesh &&
           (HdPrimTypeIsGprim(type) || type == HdPrimTypeTokens->nurbsCurves || type == HdPrimTypeTokens->nurbsPatch ||
            type == HdPrimTypeTokens->tetMesh);
}

class Planner {
public:
    // The records are read from the snapshot's frozen scene index, in parallel.
    Planner(const Snapshot &snapshot, PlanSettings settings)
        : snapshot_(snapshot),
          settings_(std::move(settings)),
          table_(TimedRead(snapshot.scene)),
          plan_(std::make_shared<Plan>()),
          resolver_(table_, plan_->diagnostics) {
        plan_->time = snapshot.time;
    }

    PlanPtr Run() {
        const ScopedFactTiming timing(FactTiming::PlanRun);
        for (const PrimRecord &prim : table_.prims)
            if (prim.geomSubset) subsets_[prim.path.GetParentPath()].emplace_back(prim);
        // A point instancer's prototype originals carry Hydra's piPropagatedPrototypes marker; they are drawn
        // only as copies under the instancer, so neither they nor their descendants get objects.
        auto inPointInstancerPrototype = [&](SdfPath path) {
            for (; !path.IsEmpty() && !path.IsAbsoluteRootPath(); path = path.GetParentPath())
                if (const PrimRecord *record = table_.Find(path); record && record->pointInstancerPrototype)
                    return true;
            return false;
        };
        std::vector<BuiltMesh> built = BuildMeshes();
        for (size_t i = 0; i < table_.prims.size(); ++i) {
            const PrimRecord &prim = table_.prims[i];
            if (prim.type == HdPrimTypeTokens->mesh && prim.mesh)
                AddMesh(prim, built[i]);
            else if (Untranslated(prim.type))
                AddObjects(prim, -1, prim.type);
            else if ((prim.instancer && prim.instancer->instanceLocations.empty()) ||
                     (prim.type.IsEmpty() && prim.isGprim && !inPointInstancerPrototype(prim.path)))
                // A point instancer, which the prototype doesn't translate (Hydra leaves instanceLocations null
                // for point instancers, HdInstancerTopologySchema), or a gprim Hydra doesn't image, such as
                // HermiteCurves, whose type the source-info filter supplies.
                AddObjects(prim, -1, prim.usdTypeName);
        }
        for (const Diagnostic &diagnostic : snapshot_.diagnostics) MapToSources(diagnostic);
        plan_->correspondence = BuildCorrespondence(*plan_);
        return plan_;
    }

private:
    // BuildMesh's results for one prim, before anything is added to the plan.
    struct BuiltMesh {
        std::optional<MeshData> mesh;
        Diagnostics problems;
        PrimRefs slots;
    };

    // Every mesh, built in parallel: BuildMesh reads only its prim and the prim's subsets. Everything that
    // adds to the plan (meshes, objects, materials, diagnostics, and the instance resolver's cache) runs
    // after, in prim order, so the plan is the one a serial build makes. A mesh with no drawn copy is built
    // and then dropped, as deciding that first would move the resolver's diagnostics.
    std::vector<BuiltMesh> BuildMeshes() const {
        std::vector<BuiltMesh> built(table_.prims.size());
        static const PrimRefs kNoSubsets;
        WorkParallelForN(table_.prims.size(), [&](size_t begin, size_t end) {
            for (size_t i = begin; i < end; ++i) {
                const PrimRecord &prim = table_.prims[i];
                if (prim.type != HdPrimTypeTokens->mesh || !prim.mesh) continue;
                const ScopedFactTiming timing(FactTiming::PlanBuildMesh);
                const auto found = subsets_.find(prim.path);
                BuiltMesh &result = built[i];
                result.mesh = BuildMesh(prim, found == subsets_.end() ? kNoSubsets : found->second, result.problems,
                                        result.slots);
            }
        });
        return built;
    }

    static PrimTable TimedRead(const HdSceneIndexBaseRefPtr &scene) {
        const ScopedFactTiming timing(FactTiming::PlanRead);
        return ReadPrims(scene);
    }

    void AddMesh(const PrimRecord &prim, BuiltMesh &built) {
        if (resolver_.FramesOf(prim).empty()) return;
        std::optional<MeshData> &mesh = built.mesh;
        const PrimRefs &slots = built.slots;
        for (const Diagnostic &problem : built.problems) MapToSources(problem);
        if (!mesh) {
            AddObjects(prim, -1, HdPrimTypeTokens->mesh);
            return;
        }
        const bool subdivided = mesh->subdivisionScheme == PxOsdOpenSubdivTokens->catmullClark ||
                                mesh->subdivisionScheme == PxOsdOpenSubdivTokens->loop;
        plan_->meshes.push_back(std::move(*mesh));
        AddObjects(prim, static_cast<int>(plan_->meshes.size() - 1), TfToken(), slots);
        // A subset has no object of its own; its bindings are reported on the mesh's copies.
        for (const PrimRecord &subset : subsets_[prim.path])
            WarnBindingsWithoutApi(subset, prim.path, "Subset " + subset.path.GetName() + ": ");
        if (!prim.materialBindFamilyIssue.empty())
            MapToSources({Severity::Warning, "invalid-subset-family", prim.path,
                          "USD rejects the materialBind family: " + prim.materialBindFamilyIssue});
        // The prototype displays the control cage; converted implicit shapes are diagnosed as approximations.
        if (subdivided && !Approximated(prim.usdTypeName))
            MapToSources({Severity::Warning, "subdivision-not-applied", prim.path,
                          "Subdivision is not applied: the control cage is displayed"});
        if (Approximated(prim.usdTypeName))
            MapToSources({Severity::Warning, "approximated-surface", prim.path,
                          prim.usdTypeName.GetString() + " is displayed as a mesh approximation"});
    }

    // One object per drawn copy, or two when the copy displays in both destinations with different
    // materials: they share the mesh, and each displays in one destination. A copy that displays in neither
    // still gets one (hidden) object. A placeholder when `mesh` is -1. `slots` is the prim whose binding
    // each of the mesh's material slots takes; a placeholder has none.
    void AddObjects(const PrimRecord &prim, int mesh, const TfToken &placeholderType, const PrimRefs &slots = {}) {
        const ScopedFactTiming timing(FactTiming::PlanObjects);
        const std::vector<Frame> &frames = resolver_.FramesOf(prim);
        const ConstantPrimvars own = OwnConstants(prim);
        // An unimaged prim can lack a purpose; USD's default is Hydra's "geometry".
        const TfToken purpose = prim.purpose.IsEmpty() ? HdRenderTagTokens->geometry : prim.purpose;
        auto includes = [&](const Destination &destination) {
            const TfTokenVector &purposes = destination.purposes;
            return std::find(purposes.begin(), purposes.end(), purpose) != purposes.end();
        };
        for (const Frame &frame : frames) {
            ObjectEntry object;
            object.source = frame.Map(prim.path);
            object.instanceContext = frame.context;
            object.mesh = mesh;
            object.placeholderType = placeholderType;
            if (mesh == -1) object.bounds = prim.extent;
            object.matrix = prim.matrix.value_or(GfMatrix4d(1.0)) * frame.world;
            object.visible = EffectivelyVisible(table_, prim, frame);
            object.purpose = purpose;
            object.constantPrimvars = Constants(prim, own, frame);
            object.properties = Properties(object);
            object.inViewport = object.visible && includes(settings_.viewport);
            object.inRender = object.visible && includes(settings_.render);
            if (!slots.empty()) {
                // Resolved per drawn copy, not once per Hydra prim, so each copy stays correct even if
                // UsdImaging stops splitting native instances with different bindings into different
                // prototypes, as Pixar plans (M1b plan, Phase C log: "Splitting by binding is Pixar's
                // current policy").
                // Only for the destinations the object displays in, so a material nothing displays isn't planned.
                // A copy in neither keeps the viewport's, for correspondence.
                const bool forViewport = object.inViewport || !object.inRender;
                std::vector<int> viewport, render;
                if (forViewport) viewport = Materials(slots, frame, settings_.viewport.materialPurpose);
                if (object.inRender) render = Materials(slots, frame, settings_.render.materialPurpose);
                if (object.inViewport && object.inRender && viewport != render) {
                    ObjectEntry forRender = object;
                    object.inRender = false;
                    object.materialSlots = std::move(viewport);
                    forRender.inViewport = false;
                    forRender.materialSlots = std::move(render);
                    plan_->objects.push_back(std::move(object));
                    plan_->objects.push_back(std::move(forRender));
                    continue;
                }
                // Shared by both destinations when they agree; otherwise the destination it displays in.
                object.materialSlots = forViewport ? std::move(viewport) : std::move(render);
            }
            plan_->objects.push_back(std::move(object));
        }
        if (mesh == -1 && placeholderType != HdPrimTypeTokens->mesh) {
            // A bounding box when Hydra has an extent, otherwise an empty marker; both are warned.
            const std::string shown = prim.extent ? "a bounding-box placeholder" : "an empty marker (no extent)";
            std::string what = "Hydra type '" + prim.type.GetString() + "'";
            if (prim.type.IsEmpty())
                what = "USD type '" + prim.usdTypeName.GetString() + "', which Hydra doesn't image,";
            else if (prim.instancer)
                what = "Point instancer (USD type '" + prim.usdTypeName.GetString() +
                       "'), which the prototype doesn't translate,";
            MapToSources({Severity::Warning, "untranslated-type", prim.path, what + " is displayed as " + shown});
        }
        // UsdImaging passes only schema attributes and primvars to Hydra; anything else is lost.
        if (!prim.droppedAttributes.empty()) {
            std::string names;
            for (const TfToken &name : prim.droppedAttributes) names += (names.empty() ? "" : ", ") + name.GetString();
            MapToSources({Severity::Warning, "dropped-attribute", prim.path,
                          "Attributes that are neither primvars nor schema attributes are not transferred: " + names});
        }
        WarnBindingsWithoutApi(prim, prim.path, "");
    }

    // UsdShade honors a binding authored without MaterialBindingAPI, but only for compatibility.
    void WarnBindingsWithoutApi(const PrimRecord &bound, const SdfPath &source, const std::string &what) {
        if (bound.bindingsWithoutApi.empty()) return;
        std::string names;
        for (const TfToken &name : bound.bindingsWithoutApi) names += (names.empty() ? "" : ", ") + name.GetString();
        MapToSources({Severity::Warning, "binding-without-api", source,
                      what +
                          "Material bindings authored without MaterialBindingAPI, which UsdShade honors only for "
                          "compatibility: " +
                          names});
    }

    // The prim's own constant primvars, an indexed one flattened through its index.
    ConstantPrimvars OwnConstants(const PrimRecord &prim) {
        ConstantPrimvars constants;
        for (const PrimvarRecord &primvar : prim.primvars) {
            if (primvar.interpolation != HdPrimvarSchemaTokens->constant || primvar.name == HdTokens->points) continue;
            VtValue value;
            std::string error;
            if (FlattenedConstant(primvar, value, error)) {
                constants.emplace_back(primvar.name, std::move(value));
                continue;
            }
            MapToSources({Severity::Error, "invalid-primvar", prim.path,
                          "Constant primvar '" + primvar.name.GetString() + "': its index is invalid (" + error + ")"});
        }
        return constants;
    }

    // A primvar on the prim itself, of any interpolation, shadows an inherited instance value.
    static ConstantPrimvars Constants(const PrimRecord &prim, const ConstantPrimvars &own, const Frame &frame) {
        ConstantPrimvars constants = own;
        for (const auto &[name, value] : frame.instancePrimvars)
            if (!prim.FindPrimvar(name)) constants.emplace_back(name, value);
        return constants;
    }

    // The object's constant primvars as ID properties. One that Blender can't hold is warned once per source.
    std::vector<std::pair<std::string, PropertyValue>> Properties(const ObjectEntry &object) {
        std::vector<std::pair<std::string, PropertyValue>> properties;
        for (const auto &[name, value] : object.constantPrimvars) {
            std::string why, warning;
            if (PropertyNameUsable(name.GetString(), why))
                if (std::optional<PropertyValue> property = ToProperty(value, why, warning)) {
                    properties.emplace_back(name.GetString(), std::move(*property));
                    if (!warning.empty() && unconverted_.emplace(object.source, name).second)
                        plan_->diagnostics.push_back({Severity::Warning, "narrowed-primvar", object.source,
                                                      "Constant primvar '" + name.GetString() + "': " + warning});
                    continue;
                }
            if (unconverted_.emplace(object.source, name).second)
                plan_->diagnostics.push_back(
                    {Severity::Warning, "untransferred-primvar", object.source,
                     "Constant primvar '" + name.GetString() + "' is not an object property: " + why});
        }
        return properties;
    }

    // The plan material of each slot's binding, for `purpose`.
    std::vector<int> Materials(const PrimRefs &slots, const Frame &frame, const TfToken &purpose) {
        std::vector<int> materials;
        materials.reserve(slots.size());
        for (const PrimRecord &slot : slots) materials.push_back(MaterialIndex(SlotMaterial(slot, frame, purpose)));
        return materials;
    }

    // The Hydra material a slot binds in one drawn copy.
    SdfPath SlotMaterial(const PrimRecord &slot, const Frame &frame, const TfToken &purpose) {
        // WORKAROUND for OpenUSD #3690 (copy_bindings.h): a copy a binding collection reaches takes
        // UsdShade's own answer for its instance-proxy path.
        const CopyBindings *copies = snapshot_.copyBindings.get();
        if (copies && !frame.context.empty()) {
            const std::optional<size_t> index = MaterialPurposeIndex(purpose);
            const auto found = copies->materials.find(frame.Map(slot.path));
            if (index && found != copies->materials.end()) return HydraMaterial(found->second[*index]);
        }
        return BoundMaterial(table_, slot, frame, purpose);
    }

    // The Hydra material prim that draws USD material `usdPath` (an instance proxy for a material inside an
    // instance); `usdPath` itself if none does, which MaterialIndex reports as missing. Built on first use, so
    // scenes without per-copy bindings plan exactly as before.
    SdfPath HydraMaterial(const SdfPath &usdPath) {
        if (usdPath.IsEmpty()) return usdPath;
        if (!materialsByUsdPath_) {
            materialsByUsdPath_.emplace();
            for (const PrimRecord &prim : table_.prims)
                if (prim.material)
                    for (const Frame &frame : resolver_.FramesOf(prim))
                        materialsByUsdPath_->emplace(frame.Map(prim.path), prim.path);
        }
        const auto found = materialsByUsdPath_->find(usdPath);
        return found != materialsByUsdPath_->end() ? found->second : usdPath;
    }

    int MaterialIndex(const SdfPath &path) {
        if (path.IsEmpty()) return -1;
        if (auto found = materials_.find(path); found != materials_.end()) return found->second;
        int &index = materials_[path];
        index = -1;
        const PrimRecord *prim = table_.Find(path);
        if (!prim || !prim->material) {
            plan_->diagnostics.push_back({Severity::Warning, "missing-material", SdfPath(),
                                          "Bound Hydra material " + path.GetString() + " has no material network"});
            return index;
        }
        MaterialData material;
        material.name = path.GetName();
        for (const Frame &frame : resolver_.FramesOf(*prim)) material.sources.push_back(frame.Map(path));
        material.surfaceIdentifier = prim->material->surfaceIdentifier;
        material.surfaceParameters = prim->material->surfaceParameters;
        plan_->materials.push_back(std::move(material));
        index = static_cast<int>(plan_->materials.size() - 1);
        return index;
    }

    // A diagnostic about a Hydra prim, once per USD source it is drawn as.
    void MapToSources(const Diagnostic &diagnostic) {
        // Null for a diagnostic without a source, or one naming a prim the snapshot doesn't hold.
        const PrimRecord *prim = diagnostic.source.IsEmpty() ? nullptr : table_.Find(diagnostic.source);
        if (!prim || resolver_.FramesOf(*prim).empty()) {
            Diagnostic unmapped = diagnostic;
            unmapped.source = SdfPath();
            if (!diagnostic.source.IsEmpty()) unmapped.message += " (Hydra prim " + diagnostic.source.GetString() + ")";
            plan_->diagnostics.push_back(std::move(unmapped));
            return;
        }
        for (const Frame &frame : resolver_.FramesOf(*prim)) {
            Diagnostic mapped = diagnostic;
            mapped.source = frame.Map(diagnostic.source);
            plan_->diagnostics.push_back(std::move(mapped));
        }
    }

    const Snapshot &snapshot_;
    const PlanSettings settings_;
    const PrimTable table_;
    std::shared_ptr<Plan> plan_;
    InstanceResolver resolver_;
    std::unordered_map<SdfPath, PrimRefs, SdfPath::Hash> subsets_;  // by mesh path
    std::unordered_map<SdfPath, int, SdfPath::Hash> materials_;
    std::optional<std::unordered_map<SdfPath, SdfPath, SdfPath::Hash>> materialsByUsdPath_;  // see HydraMaterial
    std::set<std::pair<SdfPath, TfToken>> unconverted_;  // constant primvars already warned about, by source
};

}  // namespace

const char *DomainName(Domain domain) {
    switch (domain) {
    case Domain::Point:
        return "POINT";
    case Domain::Face:
        return "FACE";
    case Domain::Corner:
        return "CORNER";
    }
    return "POINT";
}

const char *DataTypeName(DataType type) {
    switch (type) {
    case DataType::Float:
        return "FLOAT";
    case DataType::Float2:
        return "FLOAT2";
    case DataType::FloatVector:
        return "FLOAT_VECTOR";
    case DataType::FloatColor:
        return "FLOAT_COLOR";
    case DataType::Int:
        return "INT";
    }
    return "FLOAT";
}

PlanPtr BuildPlan(const Snapshot &snapshot, const PlanSettings &settings) { return Planner(snapshot, settings).Run(); }

}  // namespace hydra_bridge
