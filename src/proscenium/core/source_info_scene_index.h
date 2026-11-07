// The source-info filter: what the UsdImaging chain drops, read from the USD prim at the same path (source_facts.h).
// - For a prim UsdImaging doesn't image at all (no __usdPrimInfo, such as a HermiteCurves), UsdImaging's own data for
//   a prim without an adapter (UsdImagingDataSourcePrim: transform, visibility, purpose, extent), so flattening
//   applies them, and whether its USD type is a gprim.
// - For curves and points without an authored extent, USD's computed extent, so their placeholders show bounds.
// It runs right after the stage scene index (UsdImagingCreateSceneIndices' overrides callback), where paths are still
// USD paths. Its containers read USD when built, at the chain's current time, and are rebuilt when their prim is
// dirtied: downstream scene indices keep input containers between notices, so values fixed for good would go stale.
// The UsdImaging data sources it hands out run on the filter's own stage globals (Globals), which give them the
// chain's time and record what they flag as time-varying, so SetTime dirties exactly that, as
// UsdImagingStageSceneIndex::SetTime does.
#pragma once

#include <pxr/base/tf/token.h>
#include <pxr/imaging/hd/filteringSceneIndex.h>
#include <pxr/pxr.h>
#include <pxr/usd/usd/stage.h>
#include <pxr/usd/usd/timeCode.h>
#include <pxr/usdImaging/usdImaging/dataSourceStageGlobals.h>

#include <atomic>
#include <cstdint>
#include <memory>
#include <mutex>
#include <unordered_map>

namespace proscenium {

class SourceInfoSceneIndex;
using SourceInfoSceneIndexRefPtr = PXR_NS::TfRefPtr<SourceInfoSceneIndex>;
using SourceInfoSceneIndexPtr = PXR_NS::TfWeakPtr<SourceInfoSceneIndex>;

class SourceInfoSceneIndex final : public PXR_NS::HdSingleInputFilteringSceneIndexBase {
 public:
  // The stage is held weakly: the stage scene index holds it until the chain is released.
  static SourceInfoSceneIndexRefPtr New(const PXR_NS::HdSceneIndexBaseRefPtr& input, const PXR_NS::UsdStagePtr& stage);

  ~SourceInfoSceneIndex() override = default;
  SourceInfoSceneIndex(const SourceInfoSceneIndex&) = delete;
  SourceInfoSceneIndex& operator=(const SourceInfoSceneIndex&) = delete;
  SourceInfoSceneIndex(SourceInfoSceneIndex&&) = delete;
  SourceInfoSceneIndex& operator=(SourceInfoSceneIndex&&) = delete;

  // Call before the stage scene index's SetTime, never alongside reads.
  void SetTime(PXR_NS::UsdTimeCode time);
  // Stops adding anything and drops every container, so prims Hydra re-reads while the chain drops the stage aren't
  // built again from USD. Call before the stage scene index's SetStage(nullptr), never alongside reads.
  void Detach();

  PXR_NS::HdSceneIndexPrim GetPrim(const PXR_NS::SdfPath& primPath) const override;
  PXR_NS::SdfPathVector GetChildPrimPaths(const PXR_NS::SdfPath& primPath) const override;

 protected:
  // Hydra's notices pass through unchanged; the filter adds its own for the values it supplies. The names are
  // HdSingleInputFilteringSceneIndexBase's virtuals, reserved identifiers USD chose.
  void _PrimsAdded(const PXR_NS::HdSceneIndexBase&,  // NOLINT(bugprone-reserved-identifier)
                   const PXR_NS::HdSceneIndexObserver::AddedPrimEntries& entries) override;
  void _PrimsRemoved(const PXR_NS::HdSceneIndexBase&,  // NOLINT(bugprone-reserved-identifier)
                     const PXR_NS::HdSceneIndexObserver::RemovedPrimEntries& entries) override;
  void _PrimsDirtied(const PXR_NS::HdSceneIndexBase&,  // NOLINT(bugprone-reserved-identifier)
                     const PXR_NS::HdSceneIndexObserver::DirtiedPrimEntries& entries) override;

 private:
  SourceInfoSceneIndex(const PXR_NS::HdSceneIndexBaseRefPtr& input, PXR_NS::UsdStagePtr stage);

  PXR_NS::HdContainerDataSourceHandle Added(const PXR_NS::UsdPrim& prim, bool imaged) const;
  // Makes the cached container of `path` rebuild on its next access, including copies downstream scene indices
  // hold. Call with mutex_ held.
  void Invalidate(const PXR_NS::SdfPath& path) const;

  // The stage globals for the UsdImaging data sources the filter hands out: the chain's time, and a record of what
  // they flag as time-varying. Asset-path dependencies aren't tracked.
  class Globals final : public PXR_NS::UsdImagingDataSourceStageGlobals {
   public:
    explicit Globals(const SourceInfoSceneIndex& owner) : owner_(owner) {}
    [[nodiscard]] PXR_NS::UsdTimeCode GetTime() const override;
    void FlagAsTimeVarying(const PXR_NS::SdfPath& hydraPath, const PXR_NS::HdDataSourceLocator& locator) const override;
    void FlagAsAssetPathDependent(const PXR_NS::SdfPath&) const override {}

   private:
    const SourceInfoSceneIndex& owner_;
  };

  template <class T>
  using PathMap = std::unordered_map<PXR_NS::SdfPath, T, PXR_NS::SdfPath::Hash>;

  PXR_NS::UsdStagePtr stage_;
  PXR_NS::UsdTimeCode time_{0.0};  // the stage scene index's starting time
  // Set once by New, so const members can hand containers a weak pointer to the filter.
  SourceInfoSceneIndexPtr self_;
  // One container per prim, built when first read and rebuilt only when its generation moves.
  struct Cached {
    PXR_NS::HdContainerDataSourceHandle container;
    std::shared_ptr<std::atomic<uint64_t>> generation;
  };
  mutable PathMap<Cached> cache_;  // guarded by mutex_
  std::unique_ptr<Globals> globals_;
  mutable std::mutex mutex_;
  // Locators flagged as time-varying, per prim, dirtied on every time change.
  mutable PathMap<PXR_NS::HdDataSourceLocatorSet> timeVarying_;
};

}  // namespace proscenium
