// BuildPlan: meshes with material slots, objects per drawn copy, placeholders, and diagnostics.
#include "instancing.h"
#include "mesh_builder.h"
#include "plan.h"
#include "prim_reader.h"

#include <pxr/imaging/hd/primvarSchema.h>
#include <pxr/imaging/hd/tokens.h>

#include <algorithm>
#include <unordered_map>

PXR_NAMESPACE_USING_DIRECTIVE

namespace hydra_bridge {

namespace {

// USD types the scene-index graph converts to meshes inexactly: curved implicit surfaces become fixed coarse
// cages, and NURBS patches their control hull. Hydra itself gives no signal.
bool Approximated(const TfToken &usdTypeName) {
    static const TfToken kTypes[] = {TfToken("Sphere"), TfToken("Cone"), TfToken("Cylinder"), TfToken("Capsule"),
                                     TfToken("NurbsPatch")};
    return std::find(std::begin(kTypes), std::end(kTypes), usdTypeName) != std::end(kTypes);
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
    explicit Planner(const Snapshot &snapshot)
        : snapshot_(snapshot),
          table_(ReadPrims(snapshot.scene)),
          plan_(std::make_shared<Plan>()),
          resolver_(table_, plan_->diagnostics) {
        plan_->time = snapshot.time;
    }

    PlanPtr Run() {
        for (const PrimRecord &prim : table_.prims)
            if (prim.geomSubset) subsets_[prim.path.GetParentPath()].push_back(&prim);
        for (const PrimRecord &prim : table_.prims) {
            if (prim.type == HdPrimTypeTokens->mesh && prim.mesh)
                AddMesh(prim);
            else if (Untranslated(prim.type))
                AddObjects(prim, -1, prim.type);
        }
        for (const Diagnostic &diagnostic : snapshot_.diagnostics) MapToSources(diagnostic);
        return plan_;
    }

private:
    void AddMesh(const PrimRecord &prim) {
        if (resolver_.FramesOf(prim).empty()) return;
        Diagnostics problems;
        auto lookup = [this](const SdfPath &material) { return MaterialIndex(material); };
        std::optional<MeshData> mesh = BuildMesh(prim, subsets_[prim.path], lookup, problems);
        for (const Diagnostic &problem : problems) MapToSources(problem);
        if (!mesh) {
            AddObjects(prim, -1, HdPrimTypeTokens->mesh);
            return;
        }
        plan_->meshes.push_back(std::move(*mesh));
        AddObjects(prim, static_cast<int>(plan_->meshes.size() - 1), TfToken());
        if (Approximated(prim.usdTypeName))
            MapToSources({Severity::Warning, "approximated-surface", prim.path,
                          prim.usdTypeName.GetString() + " is displayed as a mesh approximation"});
    }

    // One object per drawn copy; a placeholder when `mesh` is -1.
    void AddObjects(const PrimRecord &prim, int mesh, const TfToken &placeholderType) {
        const std::vector<Frame> &frames = resolver_.FramesOf(prim);
        for (const Frame &frame : frames) {
            ObjectEntry object;
            object.source = frame.Map(prim.path);
            object.instanceContext = frame.context;
            object.mesh = mesh;
            object.placeholderType = placeholderType;
            object.matrix = prim.matrix.value_or(GfMatrix4d(1.0)) * frame.world;
            object.visible = prim.visible && frame.visible;
            object.purpose = prim.purpose;
            object.constantPrimvars = Constants(prim, frame);
            plan_->objects.push_back(std::move(object));
        }
        if (mesh == -1 && placeholderType != HdPrimTypeTokens->mesh)
            MapToSources({Severity::Warning, "untranslated-type", prim.path,
                          "Hydra type '" + placeholderType.GetString() + "' is displayed as a placeholder"});
    }

    // A primvar on the prim itself, of any interpolation, shadows an inherited instance value.
    static ConstantPrimvars Constants(const PrimRecord &prim, const Frame &frame) {
        ConstantPrimvars constants;
        for (const PrimvarRecord &primvar : prim.primvars)
            if (primvar.interpolation == HdPrimvarSchemaTokens->constant && !primvar.indices &&
                primvar.name != HdTokens->points)
                constants.emplace_back(primvar.name, primvar.values);
        for (const auto &[name, value] : frame.instancePrimvars)
            if (!prim.FindPrimvar(name)) constants.emplace_back(name, value);
        return constants;
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
        const PrimRecord *prim = diagnostic.source.IsEmpty() ? nullptr : table_.Find(diagnostic.source);
        const std::vector<Frame> *frames = prim ? &resolver_.FramesOf(*prim) : nullptr;
        if (!frames || frames->empty()) {
            Diagnostic unmapped = diagnostic;
            unmapped.source = SdfPath();
            if (!diagnostic.source.IsEmpty()) unmapped.message += " (Hydra prim " + diagnostic.source.GetString() + ")";
            plan_->diagnostics.push_back(std::move(unmapped));
            return;
        }
        for (const Frame &frame : *frames) {
            Diagnostic mapped = diagnostic;
            mapped.source = frame.Map(diagnostic.source);
            plan_->diagnostics.push_back(std::move(mapped));
        }
    }

    const Snapshot &snapshot_;
    const PrimTable table_;
    std::shared_ptr<Plan> plan_;
    InstanceResolver resolver_;
    std::unordered_map<SdfPath, std::vector<const PrimRecord *>, SdfPath::Hash> subsets_;  // by mesh path
    std::unordered_map<SdfPath, int, SdfPath::Hash> materials_;
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

PlanPtr BuildPlan(const Snapshot &snapshot) { return Planner(snapshot).Run(); }

}  // namespace hydra_bridge
