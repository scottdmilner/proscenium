#include "prim_reader.h"

#include <pxr/base/work/loops.h>
#include <pxr/imaging/hd/dataSourceMaterialNetworkInterface.h>
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
    return source ? source->GetTypedValue(kNow) : fallback;
}

void ReadPrimvars(const HdContainerDataSourceHandle &source, PrimRecord &record) {
    HdPrimvarsSchema primvars = HdPrimvarsSchema::GetFromParent(source);
    if (!primvars) return;
    for (const TfToken &name : primvars.GetPrimvarNames()) {
        HdPrimvarSchema primvar = primvars.GetPrimvar(name);
        if (!primvar) continue;
        PrimvarRecord out;
        out.name = name;
        out.interpolation = ValueOr(primvar.GetInterpolation());
        out.role = ValueOr(primvar.GetRole());
        // Unflattened values whether or not the primvar is indexed; GetPrimvarValue would flatten.
        if (HdSampledDataSourceHandle values = primvar.GetIndexedPrimvarValue()) out.values = values->GetValue(kNow);
        if (primvar.IsIndexed()) out.indices = ValueOr(primvar.GetIndices());
        // Blocked primvars, such as the points of a skinned mesh before pruning, have no value.
        if (!out.values.IsEmpty()) record.primvars.push_back(std::move(out));
    }
}

// Absent scheme and orientation take USD's schema fallbacks; an authored bad token reaches validation.
MeshRecord ReadMesh(const HdMeshSchema &mesh) {
    HdMeshTopologySchema topology = mesh.GetTopology();
    return MeshRecord{PxOsdMeshTopology(ValueOr(mesh.GetSubdivisionScheme(), PxOsdOpenSubdivTokens->catmullClark),
                                        ValueOr(topology.GetOrientation(), PxOsdOpenSubdivTokens->rightHanded),
                                        ValueOr(topology.GetFaceVertexCounts()),
                                        ValueOr(topology.GetFaceVertexIndices()), ValueOr(topology.GetHoleIndices())),
                      ValueOr(mesh.GetDoubleSided(), false)};
}

InstancerRecord ReadInstancer(const HdInstancerTopologySchema &topology) {
    InstancerRecord out;
    out.prototypes = ValueOr(topology.GetPrototypes());
    HdIntArrayVectorSchema indices = topology.GetInstanceIndices();
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
    HdMaterialNetworkSchema network = material.GetMaterialNetwork();
    if (!network) return out;
    HdDataSourceMaterialNetworkInterface interface(path, network.GetContainer(), prim);
    const auto [connected, terminal] = interface.GetTerminalConnection(HdMaterialTerminalTokens->surface);
    if (!connected) return out;
    const TfToken &node = terminal.upstreamNodeName;
    out.surfaceIdentifier = interface.GetNodeType(node);
    for (const TfToken &name : interface.GetAuthoredNodeParameterNames(node))
        out.surfaceParameters.emplace_back(name, interface.GetNodeParameterValue(node, name));
    return out;
}

}  // namespace

const TfTokenVector &PlannedSchemas() {
    static const TfTokenVector schemas{
        UsdImagingUsdPrimInfoSchema::GetSchemaToken(), HdPrimOriginSchema::GetSchemaToken(),
        HdXformSchema::GetSchemaToken(),               HdVisibilitySchema::GetSchemaToken(),
        HdPurposeSchema::GetSchemaToken(),             HdMaterialBindingsSchema::GetSchemaToken(),
        HdPrimvarsSchema::GetSchemaToken(),            HdMeshSchema::GetSchemaToken(),
        HdGeomSubsetSchema::GetSchemaToken(),          HdInstancedBySchema::GetSchemaToken(),
        HdInstancerTopologySchema::GetSchemaToken(),   HdMaterialSchema::GetSchemaToken(),
    };
    return schemas;
}

// Copies everything planning reads; returns false for a path with no prim.
bool ReadPrim(const HdSceneIndexBase &scene, const SdfPath &path, PrimRecord &record) {
    HdSceneIndexPrim prim = scene.GetPrim(path);
    if (!prim.dataSource) return false;
    const HdContainerDataSourceHandle &source = prim.dataSource;
    record.path = path;
    record.type = prim.primType;
    record.usdTypeName = ValueOr(UsdImagingUsdPrimInfoSchema::GetFromParent(source).GetTypeName());
    record.originPath = HdPrimOriginSchema::GetFromParent(source).GetOriginPath(HdPrimOriginSchemaTokens->scenePath);
    if (HdMatrixDataSourceHandle matrix = HdXformSchema::GetFromParent(source).GetMatrix())
        record.matrix = matrix->GetTypedValue(kNow);
    record.visible = ValueOr(HdVisibilitySchema::GetFromParent(source).GetVisibility(), true);
    record.purpose = ValueOr(HdPurposeSchema::GetFromParent(source).GetPurpose());
    record.materialBinding = ValueOr(HdMaterialBindingsSchema::GetFromParent(source).GetMaterialBinding().GetPath());
    ReadPrimvars(source, record);
    if (HdMeshSchema mesh = HdMeshSchema::GetFromParent(source)) record.mesh = ReadMesh(mesh);
    if (HdGeomSubsetSchema subset = HdGeomSubsetSchema::GetFromParent(source))
        record.geomSubset = GeomSubsetRecord{ValueOr(subset.GetType()), ValueOr(subset.GetIndices())};
    if (HdInstancedBySchema instancedBy = HdInstancedBySchema::GetFromParent(source))
        record.instancedBy = InstancedByRecord{ValueOr(instancedBy.GetPaths()), ValueOr(instancedBy.GetPrototypeRoots())};
    if (HdInstancerTopologySchema topology = HdInstancerTopologySchema::GetFromParent(source))
        record.instancer = ReadInstancer(topology);
    if (HdMaterialSchema material = HdMaterialSchema::GetFromParent(source))
        record.material = ReadMaterial(path, source, material);
    return true;
}

PrimTable ReadPrims(const HdSceneIndexBaseRefPtr &scene) {
    SdfPathVector paths;
    for (const SdfPath &path : HdSceneIndexPrimView(scene, SdfPath::AbsoluteRootPath())) paths.push_back(path);
    std::vector<PrimRecord> records(paths.size());
    std::vector<char> present(paths.size(), 0);
    WorkParallelForN(paths.size(), [&](size_t begin, size_t end) {
        for (size_t i = begin; i < end; ++i) present[i] = ReadPrim(*scene, paths[i], records[i]);
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
