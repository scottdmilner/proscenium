#include "source_info_scene_index.h"

#include "fact_timings.h"

#include <pxr/imaging/hd/extentSchema.h>
#include <pxr/imaging/hd/geomSubsetSchema.h>
#include <pxr/imaging/hd/overlayContainerDataSource.h>
#include <pxr/imaging/hd/tokens.h>
#include <pxr/imaging/hd/retainedDataSource.h>
#include <pxr/usd/usdGeom/boundable.h>
#include <pxr/usd/usdGeom/gprim.h>
#include <pxr/usd/usdGeom/mesh.h>
#include <pxr/usd/usdGeom/pointBased.h>
#include <pxr/usd/usdGeom/imageable.h>
#include <pxr/usd/usdGeom/subset.h>
#include <pxr/usd/usdGeom/tokens.h>
#include <pxr/usd/usdShade/materialBindingAPI.h>
#include <pxr/usd/usdShade/tokens.h>
#include <pxr/usdImaging/usdImaging/dataSourcePrim.h>
#include <pxr/usdImaging/usdImaging/usdPrimInfoSchema.h>
#include <pxr/usdImaging/usdImaging/types.h>

#include <algorithm>
#include <cstdint>
#include <functional>
#include <limits>
#include <mutex>
#include <vector>

PXR_NAMESPACE_USING_DIRECTIVE

namespace hydra_bridge {


UsdTimeCode SourceInfoSceneIndex::Globals::GetTime() const { return owner_.time_; }

void SourceInfoSceneIndex::Globals::FlagAsTimeVarying(const SdfPath &hydraPath, const HdDataSourceLocator &locator) const {
    std::lock_guard<std::mutex> lock(owner_.mutex_);
    owner_.timeVarying_[hydraPath].insert(locator);
}

namespace {
constexpr uint64_t kForgotten = std::numeric_limits<uint64_t>::max();
}  // namespace

void SourceInfoSceneIndex::Invalidate(const SdfPath &path) const {
    if (auto found = cache_.find(path); found != cache_.end()) ++*found->second.generation;
}

void SourceInfoSceneIndex::InvalidateAll() const {
    for (auto &[path, cached] : cache_) ++*cached.generation;
}

void SourceInfoSceneIndex::Forget(const SdfPath &root) const {
    for (auto it = cache_.begin(); it != cache_.end();) {
        if (!it->first.HasPrefix(root)) {
            ++it;
            continue;
        }
        // A removed prim's container may still be read downstream; it then builds nothing.
        *it->second.generation = kForgotten;
        it = cache_.erase(it);
    }
}

void SourceInfoSceneIndex::Detach() {
    std::lock_guard<std::mutex> lock(mutex_);
    for (auto &[path, cached] : cache_) *cached.generation = kForgotten;
    cache_.clear();
    stage_ = nullptr;
}

void SourceInfoSceneIndex::SetTime(UsdTimeCode time) {
    if (time == time_) return;
    time_ = time;
    HdSceneIndexObserver::DirtiedPrimEntries dirtied;
    {
        std::lock_guard<std::mutex> lock(mutex_);
        // UsdImaging's data sources (supplied prims, purpose visibility) read the time from Globals and flag
        // themselves; computed extents are retained values, so their prims are rebuilt.
        for (const auto &[path, locators] : timeVarying_) {
            dirtied.emplace_back(path, locators);
            Invalidate(path);
        }
    }
    if (!dirtied.empty()) _SendPrimsDirtied(dirtied);
}


SourceInfoSceneIndexRefPtr SourceInfoSceneIndex::New(const HdSceneIndexBaseRefPtr &input, const UsdStagePtr &stage) {
    SourceInfoSceneIndexRefPtr index = TfCreateRefPtr(new SourceInfoSceneIndex(input, stage));
    if (stage)
        index->noticeKey_ = TfNotice::Register(SourceInfoSceneIndexPtr(index), &SourceInfoSceneIndex::OnObjectsChanged,
                                               UsdStageWeakPtr(stage));
    return index;
}

SourceInfoSceneIndex::SourceInfoSceneIndex(const HdSceneIndexBaseRefPtr &input, const UsdStagePtr &stage)
    : HdSingleInputFilteringSceneIndexBase(input), stage_(stage), globals_(std::make_unique<Globals>(*this)) {}

SourceInfoSceneIndex::~SourceInfoSceneIndex() { TfNotice::Revoke(noticeKey_); }

// Queued, like the stage scene index's own notice handling, and sent when the graph advances. A prim is
// queued for an edit to a source fact on it, or to any property of a prim given a transform, visibility, or
// purpose. Edits inside a prototype are reported at the prototype's path, which propagation forwards.
void SourceInfoSceneIndex::OnObjectsChanged(const UsdNotice::ObjectsChanged &notice, const UsdStageWeakPtr &) {
    std::lock_guard<std::mutex> lock(mutex_);
    auto consider = [&](const SdfPath &path) {
        if (!path.IsPropertyPath()) return;
        const SdfPath prim = path.GetPrimPath();
        if (supplied_.count(prim) || SourceFact(stage_ ? stage_->GetPrimAtPath(prim) : UsdPrim(), path.GetNameToken()))
            pending_[prim].push_back(path.GetNameToken());
    };
    for (const SdfPath &path : notice.GetChangedInfoOnlyPaths()) consider(path);
    for (const SdfPath &path : notice.GetResyncedPaths()) consider(path);
}

void SourceInfoSceneIndex::ApplyPendingUpdates() {
    HdSceneIndexObserver::DirtiedPrimEntries dirtied;
    {
        std::lock_guard<std::mutex> lock(mutex_);
        const HdDataSourceLocatorSet facts{HdDataSourceLocator(SourceInfoTokens::Schema())};
        bool bindingsChanged = false;
        for (const auto &[path, properties] : pending_) {
            for (const TfToken &property : properties)
                bindingsChanged |= TfStringStartsWith(property.GetString(), "material:binding") ||
                                   TfStringStartsWith(property.GetString(), "collection:");
            // A subset edit can change its mesh's family verdict.
            if (const UsdPrim prim = stage_ ? stage_->GetPrimAtPath(path) : UsdPrim(); prim && prim.IsA<UsdGeomSubset>()) {
                dirtied.emplace_back(path.GetParentPath(), facts);
                Invalidate(path.GetParentPath());
            }
            HdDataSourceLocatorSet locators = facts;
            // A computed extent follows the points.
            for (const TfToken &property : properties)
                if (property == UsdGeomTokens->points || property == UsdGeomTokens->extent)
                    locators.insert(HdExtentSchema::GetDefaultLocator());
            // What UsdImaging itself would dirty for these properties on a prim it has no adapter for.
            if (const UsdPrim prim = stage_ ? stage_->GetPrimAtPath(path) : UsdPrim(); prim && supplied_.count(path))
                locators.insert(UsdImagingDataSourcePrim::Invalidate(prim, TfToken(), properties,
                                                                     UsdImagingPropertyInvalidationType::Update));
            dirtied.emplace_back(path, locators);
            Invalidate(path);
        }
        // A binding or collection edit can change what any prim below or in the collection binds, and the
        // strength rules reach across instances, so every prim's bindings are re-resolved. Rare edits; a
        // per-collection dependency map would narrow it.
        if (bindingsChanged) {
            for (const auto &[path, cached] : cache_) dirtied.emplace_back(path, facts);
            InvalidateAll();
        }
        pending_.clear();
    }
    if (dirtied.empty()) return;
    _SendPrimsDirtied(dirtied);
}

// The source facts, and for a prim Hydra doesn't image its transform, visibility, and purpose, as one
// container that reads USD on every access.
HdContainerDataSourceHandle SourceInfoSceneIndex::Added(const UsdPrim &prim, const HdContainerDataSourceHandle &input,
                                                        bool imaged, const TfToken &hydraType) const {
    std::lock_guard<std::mutex> lock(mutex_);
    if (auto found = cache_.find(prim.GetPath()); found != cache_.end()) return found->second.container;
    const SourceInfoSceneIndexPtr self(const_cast<SourceInfoSceneIndex *>(this));
    auto generation = std::make_shared<std::atomic<uint64_t>>(0);
    HdContainerDataSourceHandle container = LazyContainer::New(
        [self, prim, input, imaged, hydraType, generation]() -> HdContainerDataSourceHandle {
            if (!self || generation->load() == kForgotten || !prim.IsValid()) return nullptr;
            const ScopedFactTiming timing(FactTiming::Build);
            HdContainerDataSourceHandle info = SourceInfo(prim, *self->globals_);
            // For a prim UsdImaging has no data for, the data it gives any prim without an adapter.
            HdContainerDataSourceHandle supplied;
            if (!imaged) {
                supplied = UsdImagingDataSourcePrim::New(prim.GetPath(), prim, *self->globals_);
                std::lock_guard<std::mutex> suppliedLock(self->mutex_);
                self->supplied_.insert(prim.GetPath());
            }
            const bool hasExtent = input && input->Get(HdExtentSchema::GetSchemaToken());
            HdContainerDataSourceHandle extent = hasExtent ? nullptr : ComputedExtent(prim, hydraType, self->time_);
            if (extent && UsdGeomPointBased(prim).GetPointsAttr().ValueMightBeTimeVarying())
                self->globals_->FlagAsTimeVarying(prim.GetPath(), HdExtentSchema::GetDefaultLocator());
            // UsdImaging's subset data source reads animated indices at the current time but never flags them,
            // so a time change wouldn't dirty them and an incremental capture would keep stale subsets (Phase D,
            // measured).
            if (UsdGeomSubset subset{prim}; subset && subset.GetIndicesAttr().ValueMightBeTimeVarying())
                self->globals_->FlagAsTimeVarying(
                    prim.GetPath(), HdDataSourceLocator(HdGeomSubsetSchemaTokens->geomSubset, HdGeomSubsetSchemaTokens->indices));
            HdContainerDataSourceHandle added =
                info ? HdRetainedContainerDataSource::New(SourceInfoTokens::Schema(), info) : HdContainerDataSourceHandle();
            for (const HdContainerDataSourceHandle &more : {supplied, extent})
                if (more) added = added ? HdOverlayContainerDataSource::New(added, more) : more;
            return added;
        },
        [generation]() -> uint64_t { return generation->load(); });
    cache_.emplace(prim.GetPath(), Cached{container, generation});
    return container;
}

HdSceneIndexPrim SourceInfoSceneIndex::GetPrim(const SdfPath &primPath) const {
    HdSceneIndexPrim prim = _GetInputSceneIndex()->GetPrim(primPath);
    // Subprims that aren't USD prims, and property paths, have nothing to add.
    if (!stage_ || !primPath.IsAbsoluteRootOrPrimPath()) return prim;
    const UsdPrim usdPrim = stage_->GetPrimAtPath(primPath);
    if (!usdPrim) return prim;
    // Only prims UsdImaging doesn't image at all (no adapter data, so no __usdPrimInfo) get its prim data. A
    // typeless prim it does image, such as an Xform or Scope, already has it; adding a visibility there would
    // override an invisible ancestor's.
    const bool imaged = prim.dataSource && prim.dataSource->Get(UsdImagingUsdPrimInfoSchema::GetSchemaToken());
    HdContainerDataSourceHandle added = Added(usdPrim, prim.dataSource, imaged, prim.primType);
    prim.dataSource = prim.dataSource ? HdOverlayContainerDataSource::New(prim.dataSource, added) : added;
    return prim;
}

SdfPathVector SourceInfoSceneIndex::GetChildPrimPaths(const SdfPath &primPath) const {
    return _GetInputSceneIndex()->GetChildPrimPaths(primPath);
}

// A resync: the re-added prims get new containers. Any prim's bindings can depend on an added prim (a
// material or collection appearing), so everything else rebuilds when next read, without notices.
void SourceInfoSceneIndex::_PrimsAdded(const HdSceneIndexBase &, const HdSceneIndexObserver::AddedPrimEntries &entries) {
    {
        std::lock_guard<std::mutex> lock(mutex_);
        // Hydra lists every added prim, so an exact erase suffices; removals list only subtree roots.
        InvalidateAll();
        for (const auto &entry : entries) {
            if (auto found = cache_.find(entry.primPath); found != cache_.end()) {
                *found->second.generation = kForgotten;
                cache_.erase(found);
            }
        }
    }
    _SendPrimsAdded(entries);
}

void SourceInfoSceneIndex::_PrimsRemoved(const HdSceneIndexBase &,
                                         const HdSceneIndexObserver::RemovedPrimEntries &entries) {
    {
        // A removed prim is no longer dirtied; a re-added one registers again when read.
        std::lock_guard<std::mutex> lock(mutex_);
        for (const auto &entry : entries) {
            for (auto it = supplied_.begin(); it != supplied_.end();)
                it = it->HasPrefix(entry.primPath) ? supplied_.erase(it) : std::next(it);
            for (auto it = timeVarying_.begin(); it != timeVarying_.end();)
                it = it->first.HasPrefix(entry.primPath) ? timeVarying_.erase(it) : std::next(it);
            Forget(entry.primPath);
        }
        InvalidateAll();
    }
    _SendPrimsRemoved(entries);
}

void SourceInfoSceneIndex::_PrimsDirtied(const HdSceneIndexBase &,
                                         const HdSceneIndexObserver::DirtiedPrimEntries &entries) {
    {
        std::lock_guard<std::mutex> lock(mutex_);
        for (const auto &entry : entries) Invalidate(entry.primPath);
    }
    _SendPrimsDirtied(entries);
}

}  // namespace hydra_bridge
