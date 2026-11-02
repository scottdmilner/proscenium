// BuildPlan: meshes with material slots, objects per drawn copy, placeholders, and diagnostics.
#include "fact_timings.h"
#include "instancing.h"
#include "mesh_builder.h"
#include "mesh_sharing.h"
#include "plan.h"
#include "prim_reader.h"

#include <pxr/base/work/loops.h>
#include <pxr/imaging/hd/primvarSchema.h>
#include <pxr/imaging/hd/tokens.h>
#include <pxr/imaging/pxOsd/tokens.h>

#include <algorithm>
#include <array>
#include <cstddef>
#include <cstdint>
#include <optional>
#include <set>
#include <string>
#include <string_view>
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

// M4 Phase E: a set of aspects, one bit each.
using Aspects = std::uint8_t;
constexpr std::array kAspects{Aspect::Transform, Aspect::Visibility, Aspect::Mesh,
                              Aspect::Materials, Aspect::Properties, Aspect::Bounds};
constexpr Aspects Bit(Aspect aspect) { return static_cast<Aspects>(1U << static_cast<unsigned>(aspect)); }
// Locator prefixes: primvars, a point instancer's per-instance transforms, and the source-info filter's container,
// which holds authored purpose visibility.
constexpr std::string_view kPrimvars("primvars/"), kInstanceTransforms("primvars/hydra:instance"),
    kSource("prosceniumSource/");

bool StartsWith(const std::string &locator, std::string_view prefix) {
    return locator.compare(0, prefix.size(), prefix) == 0;
}

// The purpose whose authored visibility `locator` names (the filter's prosceniumSource/<purpose>), or nullopt.
std::optional<TfToken> PurposeVisibility(const std::string &locator) {
    if (!StartsWith(locator, kSource)) return std::nullopt;
    for (const TfToken &purpose : {HdRenderTagTokens->guide, HdRenderTagTokens->proxy, HdRenderTagTokens->render})
        if (locator.compare(kSource.size(), std::string::npos, purpose.GetString()) == 0) return purpose;
    return std::nullopt;
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
    Planner(const Snapshot &snapshot, PlanSettings settings, const Plan *previous)
        : snapshot_(snapshot),
          settings_(std::move(settings)),
          previous_(previous ? previous->builds.get() : nullptr),
          table_(TimedRead(snapshot.scene)),
          plan_(std::make_shared<Plan>()),
          resolver_(table_, plan_->diagnostics, settings_.pointInstancers) {
        plan_->time = snapshot.time;
        // M4 Phase E: the two lookups DirtiedAspects maps to objects, from the snapshot's dirty notices.
        for (const Event &event : snapshot.events) {
            if (event.kind != EventKind::Dirtied) continue;  // added, removed, and renamed prims say nothing of time
            // Each prim's dirtied locators, once each: several notices can dirty one prim in a capture (the
            // filter's and UsdImaging's, and the time dependencies the previous capture handed on).
            std::vector<std::string> &locators = dirtiedLocators_[event.path];
            for (const std::string &locator : event.locators) {
                if (std::find(locators.begin(), locators.end(), locator) != locators.end()) continue;
                locators.push_back(locator);
                // The prims whose own purpose visibility is dirtied, with the purpose: Hydra doesn't flatten it,
                // so DirtiedAspects finds an object's ancestors among these rather than walking up to each.
                if (const std::optional<TfToken> purpose = PurposeVisibility(locator))
                    dirtiedPurposeVisibility_.emplace_back(event.path, *purpose);
            }
        }
    }

    PlanPtr Run() {
        const ScopedFactTiming timing(FactTiming::PlanRun);
        for (const PrimRecord &prim : table_.prims)
            if (prim.geomSubset) subsets_[prim.path.GetParentPath()].emplace_back(prim);
        static const TfToken kPointInstancer("PointInstancer");
        // A point instancer's descendants are drawn only as copies of its prototypes, as UsdImaging culls them:
        // its prototype originals (which carry Hydra's piPropagatedPrototypes marker) and anything else under it,
        // such as a prototype it doesn't target, get no objects.
        auto underPointInstancer = [&](SdfPath path) {
            for (; !path.IsEmpty() && !path.IsAbsoluteRootPath(); path = path.GetParentPath()) {
                const PrimRecord *record = table_.Find(path);
                if (record && (record->pointInstancerPrototype || record->usdTypeName == kPointInstancer)) return true;
            }
            return false;
        };
        auto builds = std::make_shared<MeshBuilds>();
        std::vector<BuiltMesh> built = BuildMeshes(*builds);
        plan_->builds = std::move(builds);
        for (size_t i = 0; i < table_.prims.size(); ++i) {
            const PrimRecord &prim = table_.prims[i];
            if (prim.type == HdPrimTypeTokens->mesh && prim.mesh)
                AddMesh(prim, built[i]);
            else if (Untranslated(prim.type))
                AddObjects(prim, -1, prim.type);
            else if ((!settings_.pointInstancers && prim.instancer && prim.instancer->instanceLocations.empty()) ||
                     (prim.type.IsEmpty() && prim.isGprim && !underPointInstancer(prim.path)))
                // A point instancer, unless the settings translate them (Hydra leaves instanceLocations null for
                // point instancers, HdInstancerTopologySchema), or a gprim Hydra doesn't image, such as
                // HermiteCurves, whose type the source-info filter supplies.
                AddObjects(prim, -1, prim.usdTypeName);
        }
        for (const Diagnostic &diagnostic : snapshot_.diagnostics) MapToSources(diagnostic);
        HoldDisplayColors();
        plan_->correspondence = BuildCorrespondence(*plan_);
        return plan_;
    }

private:
    // BuildMesh's results for one prim, before anything is added to the plan.
    struct BuiltMesh {
        std::optional<MeshData> mesh;
        std::size_t contentHash = 0;
        Diagnostics problems;
        PrimRefs slots;
    };

    // Every mesh, built in parallel: BuildMesh reads only its prim and the prim's subsets. Everything that
    // adds to the plan (meshes, objects, materials, diagnostics, and the instance resolver's cache) runs
    // after, in prim order, so the plan is the one a serial build makes. A mesh with no drawn copy is built
    // and then dropped, as deciding that first would move the resolver's diagnostics. Each build goes into
    // `builds`, and one the previous plan made from the same containers is reused (D9); any other build the
    // previous plan made of the prim gives BuildMesh what still holds (E4).
    std::vector<BuiltMesh> BuildMeshes(MeshBuilds &builds) const {
        std::vector<BuiltMesh> built(table_.prims.size());
        std::vector<std::optional<MeshBuild>> kept(table_.prims.size());
        static const PrimRefs kNoSubsets;
        const HdRetainedSceneIndex &scene = *snapshot_.scene;
        WorkParallelForN(table_.prims.size(), [&](size_t begin, size_t end) {
            for (size_t i = begin; i < end; ++i) {
                const PrimRecord &prim = table_.prims[i];
                if (prim.type != HdPrimTypeTokens->mesh || !prim.mesh) continue;
                const auto found = subsets_.find(prim.path);
                const PrimRefs &subsets = found == subsets_.end() ? kNoSubsets : found->second;
                MeshBuild build;
                build.prim = scene.GetPrim(prim.path).dataSource;
                for (const PrimRecord &subset : subsets) build.subsets.push_back(scene.GetPrim(subset.path).dataSource);
                build.topology = prim.mesh->topology;
                build.primvars = prim.primvars;
                BuiltMesh &result = built[i];
                if (!Reuse(prim.path, build, result)) {
                    const ScopedFactTiming timing(FactTiming::PlanBuildMesh);
                    result.mesh = BuildMesh(prim, subsets, result.problems, result.slots, build.topologyWork,
                                            Previous(prim.path));
                    if (result.mesh) result.contentHash = ContentHash(*result.mesh);
                }
                build.mesh = result.mesh;
                build.contentHash = result.contentHash;
                build.problems = result.problems;
                for (const PrimRecord &slot : result.slots) build.slots.push_back(slot.path);
                kept[i] = std::move(build);
            }
        });
        for (size_t i = 0; i < kept.size(); ++i) {
            std::optional<MeshBuild> &build = kept[i];
            if (build) builds.emplace(table_.prims[i].path, std::move(*build));
        }
        return built;
    }

    // The previous plan's build of the mesh at `path`; null for none.
    const MeshBuild *Previous(const SdfPath &path) const {
        if (!previous_) return nullptr;
        const auto found = previous_->find(path);
        return found == previous_->end() ? nullptr : &found->second;
    }

    // Fills `result` and `build` from the previous plan's build of the mesh at `path`, if it was made from the
    // containers `build` names; false otherwise.
    bool Reuse(const SdfPath &path, MeshBuild &build, BuiltMesh &result) const {
        const MeshBuild *old = Previous(path);
        if (!old || !build.prim || old->prim != build.prim || old->subsets != build.subsets) return false;
        PrimRefs slots;
        for (const SdfPath &slot : old->slots) {
            const PrimRecord *record = table_.Find(slot);
            if (!record) return false;
            slots.emplace_back(*record);
        }
        result.mesh = old->mesh;
        result.contentHash = old->contentHash;
        result.problems = old->problems;
        result.slots = std::move(slots);
        build.topologyWork = old->topologyWork;
        return true;
    }

    static PrimTable TimedRead(const HdSceneIndexBaseRefPtr &scene) {
        const ScopedFactTiming timing(FactTiming::PlanRead);
        return ReadPrims(scene);
    }

    void AddMesh(const PrimRecord &prim, BuiltMesh &built) {
        if (resolver_.CopiesOf(prim).empty()) return;
        std::optional<MeshData> &mesh = built.mesh;
        const PrimRefs &slots = built.slots;
        for (const Diagnostic &problem : built.problems) MapToSources(problem);
        if (!mesh) {
            AddObjects(prim, -1, HdPrimTypeTokens->mesh);
            return;
        }
        const bool subdivided = mesh->subdivisionScheme == PxOsdOpenSubdivTokens->catmullClark ||
                                mesh->subdivisionScheme == PxOsdOpenSubdivTokens->loop;
        // A mesh whose content another already has shares it (M4, B5), with the least of its uses' names, so its
        // name doesn't depend on the order prims are planned in.
        int index = contents_.Find(*mesh, built.contentHash, plan_->meshes);
        if (index == -1) {
            plan_->meshes.push_back(std::move(*mesh));
            plan_->meshHashes.push_back(built.contentHash);
            index = static_cast<int>(plan_->meshes.size() - 1);
            contents_.Add(built.contentHash, index);
        } else if (mesh->name < plan_->meshes[index].name) {
            plan_->meshes[index].name = std::move(mesh->name);
        }
        AddObjects(prim, index, TfToken(), slots);
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
        const std::vector<DrawnCopy> &copies = resolver_.CopiesOf(prim);
        const ConstantPrimvars constants = OwnConstants(prim);
        // An unimaged prim can lack a purpose; USD's default is Hydra's "geometry".
        const TfToken purpose = prim.purpose.IsEmpty() ? HdRenderTagTokens->geometry : prim.purpose;
        auto includes = [&](const Destination &destination) {
            const TfTokenVector &purposes = destination.purposes;
            return std::find(purposes.begin(), purposes.end(), purpose) != purposes.end();
        };
        const Aspects own = dirtiedLocators_.empty() ? 0 : OwnDirtiedAspects(prim, mesh == -1, purpose);
        for (const DrawnCopy &copy : copies) {
            ObjectEntry object;
            object.source = copy.Map(prim.path);
            object.instanceContext = copy.context;
            object.mesh = mesh;
            object.placeholderType = placeholderType;
            if (mesh == -1) object.bounds = prim.extent;
            object.matrix = prim.matrix.value_or(GfMatrix4d(1.0));
            // A reset inside the prototype drops the instance's transform too (WORKAROUND for OpenUSD #862).
            if (!ResetsBelow(table_, prim.path, copy.hydraRoot)) object.matrix *= copy.world;
            object.visible = EffectivelyVisible(table_, prim, copy);
            object.purpose = purpose;
            object.constantPrimvars = Constants(prim, constants, copy);
            object.properties = Properties(object);
            if (!dirtiedLocators_.empty()) object.dirtiedAspects = DirtiedAspects(prim, copy, own, purpose);
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
                if (forViewport) viewport = Materials(slots, copy, settings_.viewport.materialPurpose);
                if (object.inRender) render = Materials(slots, copy, settings_.render.materialPurpose);
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

    // M4 Phase E (E3): the aspects the snapshot's dirtied locators reach in an object of `prim` drawn in `copy`, from
    // those of the prim, its subsets, and its instance roots or point instancers, and, for purpose visibility, which
    // Hydra doesn't flatten, their ancestors. Hydra forwards an ancestor's transform and visibility to its descendants'
    // and to instance roots, and a skeleton's animation to the points it skins. `own` is the prim's
    // (OwnDirtiedAspects), the same for each of its copies; the instance roots' are memoized, and the ancestors'
    // purpose visibility is found by prefix among the few prims dirtied in one, so an object costs a lookup per
    // instance root.
    std::vector<Aspect> DirtiedAspects(const PrimRecord &prim, const DrawnCopy &copy, Aspects own,
                                       const TfToken &purpose) {
        Aspects found = own;
        for (std::size_t i = 0; i < copy.hydraContext.size(); ++i) {
            const SdfPath &path = copy.hydraContext[i];
            if (i == 0 || path != copy.hydraContext[i - 1])
                found |= ContextDirtiedAspects(path);  // a point's two entries
        }
        for (const auto &visibility : dirtiedPurposeVisibility_) {
            const SdfPath &path = visibility.first;  // a lambda can't capture a structured binding before C++20
            if (visibility.second != purpose) continue;
            const bool above = (prim.path != path && prim.path.HasPrefix(path)) ||
                               std::any_of(copy.hydraContext.begin(), copy.hydraContext.end(),
                                           [&](const SdfPath &root) { return root.HasPrefix(path); });
            if (above) found |= Bit(Aspect::Visibility);
        }
        std::vector<Aspect> aspects;
        for (const Aspect aspect : kAspects)
            if (found & Bit(aspect)) aspects.push_back(aspect);
        return aspects;
    }

    // The aspects the locators dirtied on `prim` and its subsets reach in each of its objects. A constant primvar is a
    // property, and a display color or opacity also the mesh's, which may hold it (D13); any other value is the
    // mesh's, or a placeholder's bounds.
    Aspects OwnDirtiedAspects(const PrimRecord &prim, bool placeholder, const TfToken &purpose) const {
        const Aspects shape = Bit(placeholder ? Aspect::Bounds : Aspect::Mesh);
        Aspects found = 0;
        if (const auto dirtied = dirtiedLocators_.find(prim.path); dirtied != dirtiedLocators_.end()) {
            for (const std::string &locator : dirtied->second) {
                if (const std::optional<Aspects> placed = Placement(locator, purpose)) {
                    found |= *placed;
                } else if (!StartsWith(locator, kPrimvars)) {
                    found |= shape;
                } else {
                    const std::string name = PrimvarName(locator);
                    const auto constant = std::find_if(prim.primvars.begin(), prim.primvars.end(), [&](const auto &p) {
                        return p.name.GetString() == name && p.interpolation == HdPrimvarSchemaTokens->constant;
                    });
                    if (constant == prim.primvars.end()) {
                        found |= shape;
                        continue;
                    }
                    found |= Bit(Aspect::Properties);
                    if (!placeholder &&
                        (name == HdTokens->displayColor.GetString() || name == HdTokens->displayOpacity.GetString()))
                        found |= Bit(Aspect::Mesh);
                }
            }
        }
        if (const auto subsets = subsets_.find(prim.path); subsets != subsets_.end())
            for (const PrimRecord &subset : subsets->second)
                if (dirtiedLocators_.count(subset.path)) found |= shape;
        return found;
    }

    // The aspects the locators dirtied on an instance root or point instancer reach in the objects drawn through it,
    // memoized.
    // On a point instancer, per-instance transforms and its topology are every copy's: Hydra doesn't say which
    // instances vary. Purpose visibility is DirtiedAspects'.
    Aspects ContextDirtiedAspects(const SdfPath &path) {
        if (const auto known = contextAspects_.find(path); known != contextAspects_.end()) return known->second;
        Aspects found = 0;
        if (const auto dirtied = dirtiedLocators_.find(path); dirtied != dirtiedLocators_.end()) {
            for (const std::string &locator : dirtied->second) {
                if (const std::optional<Aspects> placed = Placement(locator, TfToken()))
                    found |= *placed;
                else if (StartsWith(locator, "instancerTopology"))
                    found |= Bit(Aspect::Visibility);
                else if (StartsWith(locator, kInstanceTransforms))
                    found |= Bit(Aspect::Transform);
                else if (StartsWith(locator, kPrimvars))
                    found |= Bit(Aspect::Properties);  // an instance's primvars, which its contents inherit
            }
        }
        contextAspects_.emplace(path, found);
        return found;
    }

    // Transform and visibility, on any prim, and `purpose`'s visibility; nullopt for any other locator. Another
    // purpose's visibility reaches nothing.
    static std::optional<Aspects> Placement(const std::string &locator, const TfToken &purpose) {
        if (locator == "xform") return Bit(Aspect::Transform);
        if (locator == "visibility") return Bit(Aspect::Visibility);
        if (!StartsWith(locator, kSource)) return std::nullopt;
        return locator.compare(kSource.size(), std::string::npos, purpose.GetString()) == 0 ? Bit(Aspect::Visibility)
                                                                                            : Aspects{0};
    }

    static std::string PrimvarName(const std::string &locator) {
        const std::size_t end = locator.find('/', kPrimvars.size());
        return locator.substr(kPrimvars.size(), end - kPrimvars.size());
    }

    // Each mesh whose copies all have one constant display color holds it (MeshData::heldColor).
    void HoldDisplayColors() {
        // Per mesh: the color its copies share so far, or nullopt once two differ or one has none.
        std::vector<std::optional<std::optional<GfVec4f>>> shared(plan_->meshes.size());
        for (const ObjectEntry &object : plan_->objects) {
            if (object.mesh < 0) continue;
            std::optional<std::optional<GfVec4f>> &held = shared[static_cast<std::size_t>(object.mesh)];
            const std::optional<GfVec4f> color = ConstantDisplayColor(object);
            if (!held)
                held = color;
            else if (*held != color)
                *held = std::nullopt;
        }
        for (std::size_t i = 0; i < shared.size(); ++i) {
            const std::optional<std::optional<GfVec4f>> &held = shared[i];
            if (!held || !*held) continue;
            plan_->meshes[i].heldColor = **held;
            plan_->meshHashes[i] = WithHeldColor(plan_->meshHashes[i], **held);
        }
    }

    // A copy's constant displayColor, with its constant displayOpacity as alpha, as apply.object_color reads them
    // (opaque white for a value of another shape); nullopt for a copy with no constant displayColor.
    static std::optional<GfVec4f> ConstantDisplayColor(const ObjectEntry &object) {
        std::optional<GfVec4f> color;
        float alpha = 1.0f;
        for (const auto &[name, property] : object.properties) {
            const VtValue &value = property.value;
            if (name == HdTokens->displayColor.GetString()) {
                color = GfVec4f(1.0f);
                if (value.IsHolding<VtDoubleArray>() && property.tupleSize == 0) {
                    const auto &rgb = value.UncheckedGet<VtDoubleArray>();
                    if (rgb.size() == 3)
                        color = GfVec4f(static_cast<float>(rgb[0]), static_cast<float>(rgb[1]),
                                        static_cast<float>(rgb[2]), 1.0f);
                }
            } else if (name == HdTokens->displayOpacity.GetString() && value.IsHolding<double>()) {
                alpha = static_cast<float>(value.UncheckedGet<double>());
            }
        }
        if (color) (*color)[3] = alpha;
        return color;
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
    static ConstantPrimvars Constants(const PrimRecord &prim, const ConstantPrimvars &own, const DrawnCopy &copy) {
        ConstantPrimvars constants = own;
        for (const auto &[name, value] : copy.instancePrimvars)
            if (!prim.FindPrimvar(name)) constants.emplace_back(name, value);
        return constants;
    }

    // The object's constant primvars as ID properties. One that Blender can't hold is warned once per source, and
    // a string is noted once per source.
    std::vector<std::pair<std::string, PropertyValue>> Properties(const ObjectEntry &object) {
        std::vector<std::pair<std::string, PropertyValue>> properties;
        for (const auto &[name, value] : object.constantPrimvars) {
            if (IsText(value)) {
                if (unconverted_.emplace(object.source, name).second)
                    plan_->diagnostics.push_back({Severity::Info, "untransferred-primvar", object.source,
                                                  "Constant primvar '" + name.GetString() +
                                                      "' is not transferred: no Blender shading node reads a string"});
                continue;
            }
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
    std::vector<int> Materials(const PrimRefs &slots, const DrawnCopy &copy, const TfToken &purpose) {
        std::vector<int> materials;
        materials.reserve(slots.size());
        for (const PrimRecord &slot : slots) materials.push_back(MaterialIndex(SlotMaterial(slot, copy, purpose)));
        return materials;
    }

    // The Hydra material a slot binds in one drawn copy.
    SdfPath SlotMaterial(const PrimRecord &slot, const DrawnCopy &copy, const TfToken &purpose) {
        // WORKAROUND for OpenUSD #3690 (copy_bindings.h): a copy a binding collection reaches takes
        // UsdShade's own answer for its instance-proxy path.
        const CopyBindings *bindings = snapshot_.copyBindings.get();
        if (bindings && !copy.context.empty()) {
            const std::optional<size_t> index = MaterialPurposeIndex(purpose);
            const auto found = bindings->materials.find(copy.Map(slot.path));
            if (index && found != bindings->materials.end()) return HydraMaterial(found->second[*index]);
        }
        return BoundMaterial(table_, slot, copy, purpose);
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
                    for (const DrawnCopy &copy : resolver_.CopiesOf(prim))
                        materialsByUsdPath_->emplace(copy.Map(prim.path), prim.path);
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
        for (const DrawnCopy &copy : resolver_.CopiesOf(*prim)) material.sources.push_back(copy.Map(path));
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
        if (!prim || resolver_.CopiesOf(*prim).empty()) {
            Diagnostic unmapped = diagnostic;
            unmapped.source = SdfPath();
            if (!diagnostic.source.IsEmpty()) unmapped.message += " (Hydra prim " + diagnostic.source.GetString() + ")";
            plan_->diagnostics.push_back(std::move(unmapped));
            return;
        }
        for (const DrawnCopy &copy : resolver_.CopiesOf(*prim)) {
            Diagnostic mapped = diagnostic;
            mapped.source = copy.Map(diagnostic.source);
            plan_->diagnostics.push_back(std::move(mapped));
        }
    }

    const Snapshot &snapshot_;
    const PlanSettings settings_;
    const MeshBuilds *previous_;  // the previous plan's builds to reuse; null for none (D9)
    const PrimTable table_;
    std::shared_ptr<Plan> plan_;
    InstanceResolver resolver_;
    std::unordered_map<SdfPath, PrimRefs, SdfPath::Hash> subsets_;  // by mesh path
    // M4 Phase E: by Hydra path, the locators the snapshot's events dirty; the paths whose purpose visibility is
    // dirtied, with the purpose; and ContextDirtiedAspects' memo.
    std::unordered_map<SdfPath, std::vector<std::string>, SdfPath::Hash> dirtiedLocators_;
    std::vector<std::pair<SdfPath, TfToken>> dirtiedPurposeVisibility_;
    std::unordered_map<SdfPath, Aspects, SdfPath::Hash> contextAspects_;
    MeshContents contents_;
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

const char *AspectName(Aspect aspect) {
    switch (aspect) {
    case Aspect::Transform:
        return "transform";
    case Aspect::Visibility:
        return "visibility";
    case Aspect::Mesh:
        return "mesh";
    case Aspect::Materials:
        return "materials";
    case Aspect::Properties:
        return "properties";
    case Aspect::Bounds:
        return "bounds";
    }
    return "";
}

PlanPtr BuildPlan(const Snapshot &snapshot, const PlanSettings &settings, const Plan *previous) {
    return Planner(snapshot, settings, previous).Run();
}

}  // namespace hydra_bridge
