#include "prim_reader.h"

#include "source_info_scene_index.h"

#include <pxr/base/work/loops.h>
#include <pxr/imaging/hd/dataSourceMaterialNetworkInterface.h>
#include <pxr/imaging/hd/extentSchema.h>
#include <pxr/imaging/hd/geomSubsetSchema.h>
#include <pxr/imaging/hd/instancedBySchema.h>
#include <pxr/imaging/hd/instancerTopologySchema.h>
#include <pxr/imaging/hd/materialBindingSchema.h>
#include <pxr/imaging/hd/materialBindingsSchema.h>
#include <pxr/imaging/hd/materialNetworkSchema.h>
#include <pxr/imaging/hd/materialSchema.h>
#include <pxr/imaging/hd/meshSchema.h>
#include <pxr/imaging/hd/meshTopologySchema.h>
#include <pxr/imaging/hd/primOriginSchema.h>
#include <pxr/imaging/hd/primvarsSchema.h>
#include <pxr/imaging/hd/purposeSchema.h>
#include <pxr/imaging/hd/sceneIndexPrimView.h>
#include <pxr/imaging/hd/tokens.h>
#include <pxr/imaging/hd/visibilitySchema.h>
#include <pxr/imaging/hd/xformSchema.h>
#include <pxr/imaging/pxOsd/tokens.h>
#include <pxr/usdImaging/usdImaging/usdPrimInfoSchema.h>

#include <utility>

PXR_NAMESPACE_USING_DIRECTIVE

namespace hydra_bridge {

namespace {

// Snapshot data sources are static copies; offset 0 is their only sample.
constexpr HdSampledDataSource::Time kNow = 0.0f;

// The typed value of a data source, or `fallback` when the source is absent.
template <class Handle, class T = decltype(std::declval<Handle>()->GetTypedValue(kNow))>
T ValueOr(const Handle &source, T fallback = T()) {
    return source ? source->GetTypedValue(kNow) : std::move(fallback);
}

void ReadPrimvars(const HdContainerDataSourceHandle &source, PrimRecord &record) {
    const HdPrimvarsSchema primvars = HdPrimvarsSchema::GetFromParent(source);
    if (!primvars) return;
    for (const TfToken &name : primvars.GetPrimvarNames()) {
        const HdPrimvarSchema primvar = primvars.GetPrimvar(name);
        if (!primvar) continue;
        PrimvarRecord out;
        out.name = name;
        out.interpolation = ValueOr(primvar.GetInterpolation());
        out.role = ValueOr(primvar.GetRole());
        // Unflattened values whether or not the primvar is indexed; GetPrimvarValue would flatten.
        if (const HdSampledDataSourceHandle values = primvar.GetIndexedPrimvarValue())
            out.values = values->GetValue(kNow);
        if (primvar.IsIndexed()) out.indices = ValueOr(primvar.GetIndices());
        // Blocked primvars, such as the points of a skinned mesh before pruning, have no value.
        if (!out.values.IsEmpty()) record.primvars.push_back(std::move(out));
    }
}

// Absent scheme and orientation take USD's schema fallbacks; an authored bad token reaches validation.
MeshRecord ReadMesh(const HdMeshSchema &mesh) {
    const HdMeshTopologySchema topology = mesh.GetTopology();
    return MeshRecord{PxOsdMeshTopology(ValueOr(mesh.GetSubdivisionScheme(), PxOsdOpenSubdivTokens->catmullClark),
                                        ValueOr(topology.GetOrientation(), PxOsdOpenSubdivTokens->rightHanded),
                                        ValueOr(topology.GetFaceVertexCounts()),
                                        ValueOr(topology.GetFaceVertexIndices()), ValueOr(topology.GetHoleIndices())),
                      ValueOr(mesh.GetDoubleSided(), false)};
}

InstancerRecord ReadInstancer(const HdInstancerTopologySchema &topology) {
    InstancerRecord out;
    out.prototypes = ValueOr(topology.GetPrototypes());
    const HdIntArrayVectorSchema indices = topology.GetInstanceIndices();
    for (size_t i = 0; i < indices.GetNumElements(); ++i) out.instanceIndices.push_back(ValueOr(indices.GetElement(i)));
    out.mask = ValueOr(topology.GetMask());
    out.instanceLocations = ValueOr(topology.GetInstanceLocations());
    return out;
}

// The surface terminal's node, read through the interface Hydra's own material filters use. The
// network falls back to the universal render context.
MaterialRecord ReadMaterial(const SdfPath &path, const HdContainerDataSourceHandle &prim,
                            const HdMaterialSchema &material) {
    MaterialRecord out;
    const HdMaterialNetworkSchema network = material.GetMaterialNetwork();
    if (!network) return out;
    const HdDataSourceMaterialNetworkInterface interface(path, network.GetContainer(), prim);
    const auto [connected, terminal] = interface.GetTerminalConnection(HdMaterialTerminalTokens->surface);
    if (!connected) return out;
    const TfToken &node = terminal.upstreamNodeName;
    out.surfaceIdentifier = interface.GetNodeType(node);
    for (const TfToken &name : interface.GetAuthoredNodeParameterNames(node))
        out.surfaceParameters.emplace_back(name, interface.GetNodeParameterValue(node, name));
    return out;
}

// A stage path the source-info filter reported for `record`, in Hydra's namespace. Inside a prototype the
// prim's origin is prototype-relative, so the prim's Hydra path minus that many components is the Hydra
// prototype root, and a path under the stage's /__Prototype_N maps under it. Other paths are the same in both.
SdfPath ToHydraPath(const PrimRecord &record, const SdfPath &stagePath) {
    const SdfPath &origin = record.originPath;
    if (origin.IsEmpty() || origin.IsAbsolutePath() || stagePath.GetPathElementCount() == 0) return stagePath;
    const SdfPath prototype = stagePath.GetPrefixes().front();
    if (!TfStringStartsWith(prototype.GetName(), "__Prototype_")) return stagePath;
    SdfPath root = record.path;
    for (size_t i = 0; i < origin.GetPathElementCount() && !root.IsAbsoluteRootPath(); ++i) root = root.GetParentPath();
    return stagePath.ReplacePrefix(prototype, root);
}

// What the source-info filter added; see source_info_scene_index.h.
void ReadSourceInfo(const HdContainerDataSourceHandle &source, PrimRecord &record) {
    auto info = HdContainerDataSource::Cast(source->Get(SourceInfoTokens::Schema()));
    if (!info) return;
    auto get = [&](const TfToken &name) { return info->Get(name); };
    if (record.usdTypeName.IsEmpty())
        record.usdTypeName = ValueOr(HdTokenDataSource::Cast(get(SourceInfoTokens::TypeName())));
    record.isGprim = ValueOr(HdBoolDataSource::Cast(get(SourceInfoTokens::IsGprim())), false);
    if (auto doubleSided = HdBoolDataSource::Cast(get(SourceInfoTokens::DoubleSided())))
        record.sourceDoubleSided = doubleSided->GetTypedValue(kNow);
    record.resetsXformStack = ValueOr(HdBoolDataSource::Cast(get(SourceInfoTokens::ResetsXformStack())), false);
    for (const TfToken &purpose : {HdRenderTagTokens->guide, HdRenderTagTokens->proxy, HdRenderTagTokens->render})
        if (auto visibility = HdTokenDataSource::Cast(get(purpose)))
            record.purposeVisibility.emplace_back(purpose, visibility->GetTypedValue(kNow));
    auto tokens = [&](const TfToken &name, TfTokenVector &out) {
        if (auto array = HdTypedSampledDataSource<VtTokenArray>::Cast(get(name))) {
            const VtTokenArray values = array->GetTypedValue(kNow);
            out.assign(values.begin(), values.end());
        }
    };
    tokens(SourceInfoTokens::StrongPurposes(), record.strongBindingPurposes);
    tokens(SourceInfoTokens::DroppedAttributes(), record.droppedAttributes);
    tokens(SourceInfoTokens::BindingsWithoutApi(), record.bindingsWithoutApi);
    if (auto bindings = HdContainerDataSource::Cast(get(SourceInfoTokens::Bindings()))) {
        static const TfToken kAllPurpose("allPurpose");
        for (const TfToken &purpose : bindings->GetNames())
            if (auto material = HdTokenDataSource::Cast(bindings->Get(purpose))) {
                const std::string path = material->GetTypedValue(kNow).GetString();
                record.usdBindings.emplace_back(purpose == kAllPurpose ? TfToken() : purpose,
                                                path.empty() ? SdfPath() : ToHydraPath(record, SdfPath(path)));
            }
    }
    if (auto issue = HdTokenDataSource::Cast(get(SourceInfoTokens::FamilyIssue())))
        record.materialBindFamilyIssue = issue->GetTypedValue(kNow).GetString();
    if (record.geomSubset)
        record.geomSubset->familyName = ValueOr(HdTokenDataSource::Cast(get(SourceInfoTokens::FamilyName())));
}

void ReadMaterialBindings(const HdContainerDataSourceHandle &source, PrimRecord &record) {
    const HdMaterialBindingsSchema bindings = HdMaterialBindingsSchema::GetFromParent(source);
    if (!bindings) return;
    for (const TfToken &purpose : bindings.GetContainer()->GetNames()) {
        SdfPath path = ValueOr(bindings.GetMaterialBinding(purpose).GetPath());
        if (!path.IsEmpty()) record.materialBindings.emplace_back(purpose, std::move(path));
    }
}

}  // namespace

const TfTokenVector &PlannedSchemas() {
    static const TfTokenVector schemas{
        UsdImagingUsdPrimInfoSchema::GetSchemaToken(),
        HdPrimOriginSchema::GetSchemaToken(),
        HdXformSchema::GetSchemaToken(),
        HdVisibilitySchema::GetSchemaToken(),
        HdPurposeSchema::GetSchemaToken(),
        HdMaterialBindingsSchema::GetSchemaToken(),
        HdPrimvarsSchema::GetSchemaToken(),
        HdMeshSchema::GetSchemaToken(),
        HdGeomSubsetSchema::GetSchemaToken(),
        HdInstancedBySchema::GetSchemaToken(),
        HdInstancerTopologySchema::GetSchemaToken(),
        HdMaterialSchema::GetSchemaToken(),
        HdExtentSchema::GetSchemaToken(),
        SourceInfoTokens::Schema(),
    };
    return schemas;
}

// Copies everything planning reads; returns false for a path with no prim.
bool ReadPrim(const HdSceneIndexBase &scene, const SdfPath &path, PrimRecord &record) {
    const HdSceneIndexPrim prim = scene.GetPrim(path);
    if (!prim.dataSource) return false;
    const HdContainerDataSourceHandle &source = prim.dataSource;
    record.path = path;
    record.type = prim.primType;
    const UsdImagingUsdPrimInfoSchema primInfo = UsdImagingUsdPrimInfoSchema::GetFromParent(source);
    record.usdTypeName = ValueOr(primInfo.GetTypeName());
    record.pointInstancerPrototype = static_cast<bool>(primInfo.GetPiPropagatedPrototypes());
    record.originPath = HdPrimOriginSchema::GetFromParent(source).GetOriginPath(HdPrimOriginSchemaTokens->scenePath);
    if (const HdMatrixDataSourceHandle matrix = HdXformSchema::GetFromParent(source).GetMatrix())
        record.matrix = matrix->GetTypedValue(kNow);
    record.visible = ValueOr(HdVisibilitySchema::GetFromParent(source).GetVisibility(), true);
    record.purpose = ValueOr(HdPurposeSchema::GetFromParent(source).GetPurpose());
    ReadMaterialBindings(source, record);
    if (const HdExtentSchema extent = HdExtentSchema::GetFromParent(source)) {
        if (const HdVec3dDataSourceHandle min = extent.GetMin(), max = extent.GetMax(); min && max)
            record.extent = GfRange3d(min->GetTypedValue(kNow), max->GetTypedValue(kNow));
    }
    ReadPrimvars(source, record);
    if (const HdMeshSchema mesh = HdMeshSchema::GetFromParent(source)) record.mesh = ReadMesh(mesh);
    if (const HdGeomSubsetSchema subset = HdGeomSubsetSchema::GetFromParent(source))
        record.geomSubset = GeomSubsetRecord{ValueOr(subset.GetType()), ValueOr(subset.GetIndices()), TfToken()};
    if (const HdInstancedBySchema instancedBy = HdInstancedBySchema::GetFromParent(source))
        record.instancedBy =
            InstancedByRecord{ValueOr(instancedBy.GetPaths()), ValueOr(instancedBy.GetPrototypeRoots())};
    if (const HdInstancerTopologySchema topology = HdInstancerTopologySchema::GetFromParent(source))
        record.instancer = ReadInstancer(topology);
    if (const HdMaterialSchema material = HdMaterialSchema::GetFromParent(source))
        record.material = ReadMaterial(path, source, material);
    ReadSourceInfo(source, record);
    return true;
}

PrimTable ReadPrims(const HdSceneIndexBaseRefPtr &scene) {
    SdfPathVector paths;
    for (const SdfPath &path : HdSceneIndexPrimView(scene, SdfPath::AbsoluteRootPath())) paths.push_back(path);
    std::vector<PrimRecord> records(paths.size());
    std::vector<char> present(paths.size(), 0);  // not vector<bool>, whose packed bits parallel writes would race on
    WorkParallelForN(paths.size(), [&](size_t begin, size_t end) {
        for (size_t i = begin; i < end; ++i) present[i] = static_cast<char>(ReadPrim(*scene, paths[i], records[i]));
    });
    PrimTable table;
    for (size_t i = 0; i < records.size(); ++i) {
        if (!present[i]) continue;
        table.index.emplace(records[i].path, table.prims.size());
        table.prims.push_back(std::move(records[i]));
    }
    return table;
}

}  // namespace hydra_bridge
