#include "capture.h"

#include "prim_reader.h"

#include <pxr/base/work/loops.h>
#include <pxr/imaging/hd/retainedDataSource.h>
#include <pxr/imaging/hd/sceneIndexPrimView.h>

#include <utility>

PXR_NAMESPACE_USING_DIRECTIVE

namespace hydra_bridge {

namespace {

// A new prim container holding a frozen copy of each planned schema the prim has; schemas it lacks are
// left out, as are all others, which planning never reads. HdMakeStaticCopy samples every value at
// shutter offset 0 (the graph's current time) into retained data sources, so the copy no longer reads
// the stage and later edits or time changes can't reach it. A value whose type HdMakeStaticCopy can't
// copy is dropped with a Tf error: capture records it as a diagnostic, and planning then sees that
// field as absent.
HdContainerDataSourceHandle CopyPlannedSchemas(const HdContainerDataSourceHandle &source) {
    if (!source) return nullptr;
    TfTokenVector names;
    std::vector<HdDataSourceBaseHandle> copies;
    for (const TfToken &name : PlannedSchemas()) {
        if (HdDataSourceBaseHandle schema = source->Get(name)) {
            names.push_back(name);
            copies.push_back(HdMakeStaticCopy(schema));
        }
    }
    return HdRetainedContainerDataSource::New(names.size(), names.data(), copies.data());
}

}  // namespace

SnapshotPtr Capture(SceneIndexGraph &graph, UsdTimeCode time) {
    auto snapshot = std::make_shared<Snapshot>();
    snapshot->time = time;
    WarningCollector warnings;
    SdfPathVector paths;
    {
        TfErrorMark mark;
        graph.Advance(time);
        // Depth-first, parents before children, with an explicit stack rather than recursion.
        for (const SdfPath &path : HdSceneIndexPrimView(graph.Terminal(), SdfPath::AbsoluteRootPath()))
            paths.push_back(path);
        HarvestErrors(mark, SdfPath(), snapshot->diagnostics);
    }
    snapshot->events = graph.TakeEvents();

    // Reads are threadsafe by contract; nothing mutates the graph until this pass ends. Copying samples
    // the planned schemas at the current time, which also registers them with the stage scene index
    // for time-change dirtying.
    std::vector<HdRetainedSceneIndex::AddedPrimEntry> entries(paths.size());
    std::vector<Diagnostics> errors(paths.size());
    const HdSceneIndexBase &scene = *graph.Terminal();
    WorkParallelForN(paths.size(), [&](size_t begin, size_t end) {
        for (size_t i = begin; i < end; ++i) {
            WarningCollector::ScopedSource source(paths[i]);
            TfErrorMark mark;
            HdSceneIndexPrim prim = scene.GetPrim(paths[i]);
            entries[i] = {paths[i], prim.primType, CopyPlannedSchemas(prim.dataSource)};
            HarvestErrors(mark, paths[i], errors[i]);
        }
    });

    snapshot->scene = HdRetainedSceneIndex::New();
    snapshot->scene->AddPrims(entries);
    for (const Diagnostics &posted : errors)
        snapshot->diagnostics.insert(snapshot->diagnostics.end(), posted.begin(), posted.end());
    Diagnostics warned = warnings.Take();
    snapshot->diagnostics.insert(snapshot->diagnostics.end(), warned.begin(), warned.end());
    return snapshot;
}

}  // namespace hydra_bridge
