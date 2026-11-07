// Source facts the UsdImaging chain doesn't keep, read from USD for one prim: what the source-info filter adds
// (source_info_scene_index.h). The facts sit under one container, so they survive instance propagation and reach the
// snapshot like any other schema.
#pragma once

#include <pxr/base/tf/token.h>
#include <pxr/imaging/hd/dataSource.h>
#include <pxr/pxr.h>
#include <pxr/usd/usd/prim.h>
#include <pxr/usd/usd/timeCode.h>

#include <cstdint>
#include <functional>
#include <mutex>

namespace proscenium {

// The container and its fields.
struct SourceInfoTokens {
  static const PXR_NS::TfToken& Schema();   // prosceniumSource
  static const PXR_NS::TfToken& IsGprim();  // bool, on a prim Hydra doesn't image: whether USD's type is a gprim
};

// Builds its contents from the prim as it is now, not as it was when made: downstream scene indices keep the input
// container between notices. A build is reused until `generation` changes.
class LazyContainer final : public PXR_NS::HdContainerDataSource {
 public:
  HD_DECLARE_DATASOURCE(LazyContainer);

  PXR_NS::TfTokenVector GetNames() override;
  PXR_NS::HdDataSourceBaseHandle Get(const PXR_NS::TfToken& name) override;

 private:
  LazyContainer(std::function<PXR_NS::HdContainerDataSourceHandle()> build, std::function<uint64_t()> generation);
  PXR_NS::HdContainerDataSourceHandle Built();

  std::function<PXR_NS::HdContainerDataSourceHandle()> build_;
  std::function<uint64_t()> generation_;
  std::mutex mutex_;
  bool valid_ = false;
  uint64_t builtAt_ = 0;
  PXR_NS::HdContainerDataSourceHandle built_;
};

// The source facts of a prim Hydra doesn't image (the prosceniumSource container's contents); null for none.
PXR_NS::HdContainerDataSourceHandle UnimagedSourceInfo(const PXR_NS::UsdPrim& prim);

// Whether USD computes the extent of `prim` for the filter when none is authored: point-based prims that Hydra
// doesn't draw as meshes, such as curves and points.
bool ComputesExtent(const PXR_NS::UsdPrim& prim);

// USD's computed extent at `time` for a prim ComputesExtent accepts, as an extent schema container; null otherwise.
PXR_NS::HdContainerDataSourceHandle ComputedExtent(const PXR_NS::UsdPrim& prim, PXR_NS::UsdTimeCode time);

}  // namespace proscenium
