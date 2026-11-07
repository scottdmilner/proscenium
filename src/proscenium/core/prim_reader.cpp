#include "prim_reader.h"

#include <pxr/imaging/hd/extentSchema.h>
#include <pxr/imaging/hd/instancedBySchema.h>
#include <pxr/imaging/hd/instancerTopologySchema.h>
#include <pxr/imaging/hd/primOriginSchema.h>
#include <pxr/imaging/hd/primvarsSchema.h>
#include <pxr/imaging/hd/purposeSchema.h>
#include <pxr/imaging/hd/sceneIndexPrimView.h>
#include <pxr/imaging/hd/tokens.h>
#include <pxr/imaging/hd/visibilitySchema.h>
#include <pxr/imaging/hd/xformSchema.h>

#include <cstddef>
#include <type_traits>
#include <utility>

#include "source_facts.h"

PXR_NAMESPACE_USING_DIRECTIVE

namespace proscenium {
namespace {

// The snapshot's data sources are static copies; offset 0 is their only sample.
constexpr HdSampledDataSource::Time kNow = 0.0F;

// The source's value, or its type's default when there is no source.
template <class Handle>
auto ValueOf(const Handle& source) -> std::decay_t<decltype(source->GetTypedValue(kNow))> {
  if (!source) return {};
  return source->GetTypedValue(kNow);
}

void ReadPrimvars(const HdContainerDataSourceHandle& source, PrimRecord& record) {
  const HdPrimvarsSchema primvars = HdPrimvarsSchema::GetFromParent(source);
  if (!primvars) return;
  for (const TfToken& name : primvars.GetPrimvarNames()) {
    const HdPrimvarSchema primvar = primvars.GetPrimvar(name);
    if (!primvar) continue;
    PrimvarRecord out;
    out.name = name;
    // Unflattened values whether or not the primvar is indexed; GetPrimvarValue would flatten.
    if (const HdSampledDataSourceHandle values = primvar.GetIndexedPrimvarValue()) out.values = values->GetValue(kNow);
    if (primvar.IsIndexed()) out.indices = ValueOf(primvar.GetIndices());
    if (!out.values.IsEmpty()) record.primvars.push_back(std::move(out));
  }
}

InstancerRecord ReadInstancer(const HdInstancerTopologySchema& topology) {
  InstancerRecord out;
  out.prototypes = ValueOf(topology.GetPrototypes());
  const HdIntArrayVectorSchema indices = topology.GetInstanceIndices();
  for (std::size_t i = 0; i < indices.GetNumElements(); ++i)
    out.instanceIndices.push_back(ValueOf(indices.GetElement(i)));
  out.instanceLocations = ValueOf(topology.GetInstanceLocations());
  out.mask = ValueOf(topology.GetMask());
  return out;
}

// What the source-info filter added; see source_info_scene_index.h.
void ReadSourceInfo(const HdContainerDataSourceHandle& source, PrimRecord& record) {
  const auto info = HdContainerDataSource::Cast(source->Get(SourceInfoTokens::Schema()));
  if (!info) return;
  record.isGprim = ValueOf(HdBoolDataSource::Cast(info->Get(SourceInfoTokens::IsGprim())));
  record.resetsXformStack = ValueOf(HdBoolDataSource::Cast(info->Get(SourceInfoTokens::ResetsXformStack())));
  for (const TfToken& purpose : {HdRenderTagTokens->guide, HdRenderTagTokens->proxy, HdRenderTagTokens->render})
    if (const auto visibility = HdTokenDataSource::Cast(info->Get(purpose)))
      record.purposeVisibility.emplace_back(purpose, visibility->GetTypedValue(kNow));
}

// Everything planning reads of the prim at `path`; false for a path with no prim.
bool ReadPrim(const HdSceneIndexBase& scene, const SdfPath& path, PrimRecord& record) {
  const HdSceneIndexPrim prim = scene.GetPrim(path);
  if (!prim.dataSource) return false;
  const HdContainerDataSourceHandle& source = prim.dataSource;
  record.path = path;
  record.type = prim.primType;
  record.originPath = HdPrimOriginSchema::GetFromParent(source).GetOriginPath(HdPrimOriginSchemaTokens->scenePath);
  if (const HdMatrixDataSourceHandle matrix = HdXformSchema::GetFromParent(source).GetMatrix())
    record.matrix = matrix->GetTypedValue(kNow);
  if (const HdBoolDataSourceHandle visible = HdVisibilitySchema::GetFromParent(source).GetVisibility())
    record.visible = visible->GetTypedValue(kNow);
  record.purpose = ValueOf(HdPurposeSchema::GetFromParent(source).GetPurpose());
  if (const HdExtentSchema extent = HdExtentSchema::GetFromParent(source)) {
    if (const HdVec3dDataSourceHandle min = extent.GetMin(), max = extent.GetMax(); min && max)
      record.extent = GfRange3d(min->GetTypedValue(kNow), max->GetTypedValue(kNow));
  }
  ReadPrimvars(source, record);
  if (const HdInstancedBySchema instancedBy = HdInstancedBySchema::GetFromParent(source))
    record.instancedBy = InstancedByRecord{ValueOf(instancedBy.GetPaths()), ValueOf(instancedBy.GetPrototypeRoots())};
  if (const HdInstancerTopologySchema topology = HdInstancerTopologySchema::GetFromParent(source))
    record.instancer = ReadInstancer(topology);
  ReadSourceInfo(source, record);
  return true;
}

}  // namespace

PrimTable ReadPrims(const Snapshot& snapshot) {
  PrimTable table;
  for (const SdfPath& path : HdSceneIndexPrimView(snapshot.scene, SdfPath::AbsoluteRootPath())) {
    PrimRecord record;
    if (!ReadPrim(*snapshot.scene, path, record)) continue;
    table.index.emplace(path, table.prims.size());
    table.prims.push_back(std::move(record));
  }
  return table;
}

}  // namespace proscenium
