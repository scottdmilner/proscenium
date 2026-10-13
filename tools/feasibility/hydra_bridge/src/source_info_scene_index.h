// Source facts the UsdImaging chain drops, added under one container (`prosceniumSource`) so they survive
// instance propagation and reach the snapshot like any other schema:
// - a GeomSubset's familyName (Hydra keeps every family's subsets but not which family each is in);
// - authored guide, proxy, and render visibility (UsdGeomVisibilityAPI is not imaged);
// - a gprim's doubleSided (the implicit-surface filter loses a Cube's authored true);
// - USD's verdict on a mesh's materialBind family (UsdGeomSubset::ValidateFamily);
// - an extent computed by USD (ComputeExtentFromPlugins) for a point-based prim Hydra gives none, such as
//   curves or points, so its placeholder can show bounds;
// - the USD type name and whether it is a gprim, for prims Hydra doesn't image at all (HermiteCurves),
//   whose __usdPrimInfo is then missing. Such prims also get UsdImaging's own data for a prim without an
//   adapter (UsdImagingDataSourcePrim: transform, visibility, purpose, extent, primvars), as UsdImaging gives
//   any prim it has no adapter for, so flattening applies them;
// - UsdShade's resolved binding per material purpose, which inside a prototype covers what the prototype
//   authors (Hydra misses collection bindings there and mis-roots nested ones), and the purposes a prim binds
//   strongerThanDescendants (see BoundMaterial in instancing.h);
// - the authored attributes of a gprim or point instancer that UsdImaging drops (custom attributes: not in
//   its schemas, not primvars), so the planner can warn that they are lost.
// It runs right after the stage scene index (UsdImagingCreateSceneIndices' overrides callback), where
// paths are still USD paths, prototypes included. Its containers read USD on every access, at the graph's
// current time: downstream scene indices keep input containers between notices, so values fixed when a
// container was built would go stale. The UsdImaging data sources it hands out run on the filter's own
// stage globals (Globals), which give them the graph's time and record what they flag as time-varying, so
// SetTime dirties exactly that, as UsdImagingStageSceneIndex::SetTime does. Hydra doesn't notice edits to
// most of what it adds, so the filter listens to the stage itself and dirties the prims concerned when the
// graph advances (ApplyPendingUpdates), asking UsdImagingDataSourcePrim::Invalidate which locators changed.
#pragma once

#include "source_facts.h"

#include <pxr/pxr.h>
#include <pxr/base/tf/token.h>
#include <pxr/imaging/hd/filteringSceneIndex.h>
#include <pxr/base/tf/notice.h>
#include <pxr/usd/usd/notice.h>
#include <pxr/usd/usd/stage.h>
#include <pxr/usd/usd/timeCode.h>
#include <pxr/usdImaging/usdImaging/dataSourceStageGlobals.h>

#include <atomic>
#include <cstdint>
#include <memory>
#include <mutex>
#include <unordered_map>
#include <unordered_set>

namespace hydra_bridge {


class SourceInfoSceneIndex;
using SourceInfoSceneIndexRefPtr = pxr::TfRefPtr<SourceInfoSceneIndex>;
using SourceInfoSceneIndexPtr = pxr::TfWeakPtr<SourceInfoSceneIndex>;

class SourceInfoSceneIndex final : public pxr::HdSingleInputFilteringSceneIndexBase {
public:
    // The stage is held weakly: the stage scene index already holds it until the graph is released.
    static SourceInfoSceneIndexRefPtr New(const pxr::HdSceneIndexBaseRefPtr &input, const pxr::UsdStagePtr &stage);

    ~SourceInfoSceneIndex() override;

    // Call before the stage scene index's SetTime, never alongside reads.
    void SetTime(pxr::UsdTimeCode time);
    // Dirties the prims whose added values stage edits since the last call may have changed. Call after the
    // stage scene index's ApplyPendingUpdates, never alongside reads.
    void ApplyPendingUpdates();
    // Stops adding anything and drops every container, so prims Hydra re-reads while the graph drops the
    // stage aren't built again from USD. Call before the stage scene index's SetStage(nullptr), never
    // alongside reads.
    void Detach();

    pxr::HdSceneIndexPrim GetPrim(const pxr::SdfPath &primPath) const override;
    pxr::SdfPathVector GetChildPrimPaths(const pxr::SdfPath &primPath) const override;

protected:
    // Hydra's notices pass through unchanged; the filter adds its own for the values it supplies.
    void _PrimsAdded(const pxr::HdSceneIndexBase &, const pxr::HdSceneIndexObserver::AddedPrimEntries &entries) override;
    void _PrimsRemoved(const pxr::HdSceneIndexBase &,
                       const pxr::HdSceneIndexObserver::RemovedPrimEntries &entries) override;
    void _PrimsDirtied(const pxr::HdSceneIndexBase &,
                       const pxr::HdSceneIndexObserver::DirtiedPrimEntries &entries) override;

private:
    SourceInfoSceneIndex(const pxr::HdSceneIndexBaseRefPtr &input, const pxr::UsdStagePtr &stage);

    pxr::HdContainerDataSourceHandle Added(const pxr::UsdPrim &prim, const pxr::HdContainerDataSourceHandle &input,
                                           bool imaged, const pxr::TfToken &hydraType) const;
    // Makes the cached container of `path` rebuild on its next access, including copies downstream scene
    // indices hold. Call with mutex_ held.
    void Invalidate(const pxr::SdfPath &path) const;
    void InvalidateAll() const;
    void Forget(const pxr::SdfPath &root) const;  // invalidates and drops the containers at and below root
    void OnObjectsChanged(const pxr::UsdNotice::ObjectsChanged &notice, const pxr::UsdStageWeakPtr &sender);

    // The stage globals for the UsdImaging data sources the filter hands out: the graph's time, and a record
    // of what they flag as time-varying. Asset-path dependencies aren't tracked.
    class Globals final : public pxr::UsdImagingDataSourceStageGlobals {
    public:
        explicit Globals(const SourceInfoSceneIndex &owner) : owner_(owner) {}
        pxr::UsdTimeCode GetTime() const override;
        void FlagAsTimeVarying(const pxr::SdfPath &hydraPath, const pxr::HdDataSourceLocator &locator) const override;
        void FlagAsAssetPathDependent(const pxr::SdfPath &) const override {}

    private:
        const SourceInfoSceneIndex &owner_;
    };

    using PathSet = std::unordered_set<pxr::SdfPath, pxr::SdfPath::Hash>;

    pxr::UsdStagePtr stage_;
    pxr::UsdTimeCode time_{0.0};  // the stage scene index's starting time
    pxr::TfNotice::Key noticeKey_;
    // One container per prim, built once and rebuilt only when its own generation moves: when the prim is
    // dirtied, or when something its facts depend on changes (an ancestor's binding, a collection, a
    // mesh's subsets), so one edit doesn't rebuild every prim.
    struct Cached {
        pxr::HdContainerDataSourceHandle container;
        std::shared_ptr<std::atomic<uint64_t>> generation;
    };
    mutable std::unordered_map<pxr::SdfPath, Cached, pxr::SdfPath::Hash> cache_;  // guarded by mutex_
    std::unique_ptr<Globals> globals_;
    mutable std::mutex mutex_;
    mutable PathSet supplied_;  // prims given UsdImaging's prim data (Hydra doesn't image them)
    // Locators flagged as time-varying, per prim, dirtied on every time change.
    mutable std::unordered_map<pxr::SdfPath, pxr::HdDataSourceLocatorSet, pxr::SdfPath::Hash> timeVarying_;
    // Properties stage edits changed since the last ApplyPendingUpdates, per prim.
    std::unordered_map<pxr::SdfPath, pxr::TfTokenVector, pxr::SdfPath::Hash> pending_;
};

}  // namespace hydra_bridge
