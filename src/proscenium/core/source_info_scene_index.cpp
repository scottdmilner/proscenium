#include "source_info_scene_index.h"

#include <pxr/imaging/hd/extentSchema.h>
#include <pxr/imaging/hd/overlayContainerDataSource.h>
#include <pxr/imaging/hd/retainedDataSource.h>
#include <pxr/usd/usdGeom/boundable.h>
#include <pxr/usd/usdGeom/curves.h>
#include <pxr/usd/usdGeom/pointBased.h>
#include <pxr/usd/usdGeom/points.h>
#include <pxr/usdImaging/usdImaging/dataSourcePrim.h>
#include <pxr/usdImaging/usdImaging/usdPrimInfoSchema.h>

#include <cstdint>
#include <iterator>
#include <limits>
#include <mutex>
#include <utility>

#include "source_facts.h"

PXR_NAMESPACE_USING_DIRECTIVE

namespace proscenium {
namespace {

constexpr uint64_t kForgotten = std::numeric_limits<uint64_t>::max();

// Whether USD's extent computation for `prim` reads anything animated.
bool ComputedExtentVaries(const UsdPrim& prim) {
  if (UsdGeomPointBased(prim).GetPointsAttr().ValueMightBeTimeVarying()) return true;
  if (const UsdGeomCurves curves{prim}) return curves.GetWidthsAttr().ValueMightBeTimeVarying();
  if (const UsdGeomPoints points{prim}) return points.GetWidthsAttr().ValueMightBeTimeVarying();
  return false;
}

}  // namespace

UsdTimeCode SourceInfoSceneIndex::Globals::GetTime() const { return owner_.time_; }

void SourceInfoSceneIndex::Globals::FlagAsTimeVarying(const SdfPath& hydraPath,
                                                      const HdDataSourceLocator& locator) const {
  const std::scoped_lock lock(owner_.mutex_);
  owner_.timeVarying_[hydraPath].insert(locator);
}

SourceInfoSceneIndexRefPtr SourceInfoSceneIndex::New(const HdSceneIndexBaseRefPtr& input, const UsdStagePtr& stage) {
  // Tf's ref-counted types are created this way: TfCreateRefPtr takes ownership of the new object.
  SourceInfoSceneIndexRefPtr index =
      TfCreateRefPtr(new SourceInfoSceneIndex(input, stage));  // NOLINT(cppcoreguidelines-owning-memory)
  index->self_ = SourceInfoSceneIndexPtr(index);
  return index;
}

SourceInfoSceneIndex::SourceInfoSceneIndex(const HdSceneIndexBaseRefPtr& input, UsdStagePtr stage)
    : HdSingleInputFilteringSceneIndexBase(input),
      stage_(std::move(stage)),
      globals_(std::make_unique<Globals>(*this)) {}

void SourceInfoSceneIndex::Invalidate(const SdfPath& path) const {
  if (auto found = cache_.find(path); found != cache_.end()) ++*found->second.generation;
}

void SourceInfoSceneIndex::Detach() {
  const std::scoped_lock lock(mutex_);
  for (auto& [path, cached] : cache_) *cached.generation = kForgotten;
  cache_.clear();
  stage_ = nullptr;
}

void SourceInfoSceneIndex::SetTime(UsdTimeCode time) {
  if (time == time_) return;
  time_ = time;
  HdSceneIndexObserver::DirtiedPrimEntries dirtied;
  {
    const std::scoped_lock lock(mutex_);
    // UsdImaging's data sources read the time from Globals and flag themselves; computed extents are retained
    // values, so their prims are rebuilt.
    for (const auto& [path, locators] : timeVarying_) {
      dirtied.emplace_back(path, locators);
      Invalidate(path);
    }
  }
  if (!dirtied.empty()) _SendPrimsDirtied(dirtied);
}

// For a prim Hydra doesn't image, UsdImaging's prim data and its source facts; for curves and points without an
// authored extent, USD's computed one. One container per prim, built from USD when first read after it is dirtied.
HdContainerDataSourceHandle SourceInfoSceneIndex::Added(const UsdPrim& prim, bool imaged) const {
  const std::scoped_lock lock(mutex_);
  if (auto found = cache_.find(prim.GetPath()); found != cache_.end()) return found->second.container;
  const SourceInfoSceneIndexPtr self = self_;
  auto generation = std::make_shared<std::atomic<uint64_t>>(0);
  HdContainerDataSourceHandle container = LazyContainer::New(
      [self, prim, imaged, generation]() -> HdContainerDataSourceHandle {
        if (!self || generation->load() == kForgotten || !prim.IsValid()) return nullptr;
        HdContainerDataSourceHandle added;
        auto overlay = [&added](const HdContainerDataSourceHandle& more) {
          if (more) added = added ? HdOverlayContainerDataSource::New(added, more) : more;
        };
        if (!imaged) {
          if (const HdContainerDataSourceHandle info = UnimagedSourceInfo(prim))
            overlay(HdRetainedContainerDataSource::New(SourceInfoTokens::Schema(), info));
          overlay(UsdImagingDataSourcePrim::New(prim.GetPath(), prim, *self->globals_));
        }
        if (ComputesExtent(prim) && !UsdGeomBoundable(prim).GetExtentAttr().HasAuthoredValue()) {
          overlay(ComputedExtent(prim, self->time_));
          if (ComputedExtentVaries(prim))
            self->globals_->FlagAsTimeVarying(prim.GetPath(), HdExtentSchema::GetDefaultLocator());
        }
        return added;
      },
      [generation]() -> uint64_t { return generation->load(); });
  cache_.emplace(prim.GetPath(), Cached{container, generation});
  return container;
}

HdSceneIndexPrim SourceInfoSceneIndex::GetPrim(const SdfPath& primPath) const {
  HdSceneIndexPrim prim = _GetInputSceneIndex()->GetPrim(primPath);
  // Subprims that aren't USD prims, and property paths, have nothing to add.
  if (!stage_ || !primPath.IsAbsoluteRootOrPrimPath()) return prim;
  const UsdPrim usdPrim = stage_->GetPrimAtPath(primPath);
  if (!usdPrim) return prim;
  // Only prims UsdImaging doesn't image at all (no adapter data, so no __usdPrimInfo) get its prim data. A typeless
  // prim it does image, such as an Xform or Scope, already has it; adding a visibility there would override an
  // invisible ancestor's.
  const bool imaged = prim.dataSource && prim.dataSource->Get(UsdImagingUsdPrimInfoSchema::GetSchemaToken());
  if (imaged && !ComputesExtent(usdPrim)) return prim;
  const HdContainerDataSourceHandle added = Added(usdPrim, imaged);
  prim.dataSource = prim.dataSource ? HdOverlayContainerDataSource::New(prim.dataSource, added) : added;
  return prim;
}

SdfPathVector SourceInfoSceneIndex::GetChildPrimPaths(const SdfPath& primPath) const {
  return _GetInputSceneIndex()->GetChildPrimPaths(primPath);
}

// A resync: the re-added prims get new containers.
void SourceInfoSceneIndex::_PrimsAdded(const HdSceneIndexBase&, const HdSceneIndexObserver::AddedPrimEntries& entries) {
  {
    const std::scoped_lock lock(mutex_);
    // Hydra lists every added prim, so an exact erase suffices; removals list only subtree roots.
    for (const auto& entry : entries) {
      if (auto found = cache_.find(entry.primPath); found != cache_.end()) {
        *found->second.generation = kForgotten;
        cache_.erase(found);
      }
    }
  }
  _SendPrimsAdded(entries);
}

void SourceInfoSceneIndex::_PrimsRemoved(const HdSceneIndexBase&,
                                         const HdSceneIndexObserver::RemovedPrimEntries& entries) {
  {
    // A removed prim is no longer dirtied; a re-added one registers again when read.
    const std::scoped_lock lock(mutex_);
    for (const auto& entry : entries) {
      for (auto it = timeVarying_.begin(); it != timeVarying_.end();)
        it = it->first.HasPrefix(entry.primPath) ? timeVarying_.erase(it) : std::next(it);
      // A removed prim's container may still be read downstream; it then builds nothing.
      for (auto it = cache_.begin(); it != cache_.end();) {
        if (!it->first.HasPrefix(entry.primPath)) {
          ++it;
          continue;
        }
        *it->second.generation = kForgotten;
        it = cache_.erase(it);
      }
    }
  }
  _SendPrimsRemoved(entries);
}

// Hydra's own dirtying of a prim rebuilds its container: the points or widths a computed extent follows, or the op
// order UsdImaging's transform data source reads when made.
void SourceInfoSceneIndex::_PrimsDirtied(const HdSceneIndexBase&,
                                         const HdSceneIndexObserver::DirtiedPrimEntries& entries) {
  {
    const std::scoped_lock lock(mutex_);
    for (const auto& entry : entries) Invalidate(entry.primPath);
  }
  _SendPrimsDirtied(entries);
}

}  // namespace proscenium
