#include "capture.h"

#include "prim_reader.h"

#include <pxr/base/work/loops.h>
#include <pxr/imaging/hd/retainedDataSource.h>
#include <pxr/imaging/hd/sceneIndexPrimView.h>

#include <set>
#include <string>
#include <tuple>
#include <unordered_set>
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

// The paths the notices since the previous capture name: exactly, or with all their descendants.
class Affected {
public:
    explicit Affected(const std::vector<Event> &events) {
        for (const Event &event : events) {
            switch (event.kind) {
            case EventKind::Added:
            case EventKind::Dirtied:
                exact_.insert(event.path);
                break;
            case EventKind::Removed:
                subtrees_.insert(event.path);
                break;
            case EventKind::Renamed:
                subtrees_.insert(event.oldPath);
                subtrees_.insert(event.path);
                break;
            }
        }
    }

    bool Contains(const SdfPath &path) const {
        if (exact_.count(path)) return true;
        for (SdfPath ancestor = path; !ancestor.IsEmpty(); ancestor = ancestor.GetParentPath()) {
            if (subtrees_.count(ancestor)) return true;
            if (ancestor.IsAbsoluteRootPath()) break;
        }
        return false;
    }

private:
    std::unordered_set<SdfPath, SdfPath::Hash> exact_;
    std::unordered_set<SdfPath, SdfPath::Hash> subtrees_;
};

// Appends diagnostics, skipping exact repeats: a warning is posted once per read of a value, and Hydra
// may read a value more than once.
class UniqueAppender {
public:
    explicit UniqueAppender(Diagnostics &to) : to_(to) {
        for (const Diagnostic &diagnostic : to) seen_.insert(Key(diagnostic));
    }

    void Append(const Diagnostics &from) {
        for (const Diagnostic &diagnostic : from)
            if (seen_.insert(Key(diagnostic)).second) to_.push_back(diagnostic);
    }

private:
    using KeyType = std::tuple<Severity, std::string, SdfPath, std::string>;
    static KeyType Key(const Diagnostic &d) { return {d.severity, d.code, d.source, d.message}; }

    Diagnostics &to_;
    std::set<KeyType> seen_;
};

}  // namespace

SnapshotPtr Capture(SceneIndexGraph &graph, UsdTimeCode time, const Snapshot *previous, Diagnostics carried) {
    auto snapshot = std::make_shared<Snapshot>();
    snapshot->time = time;
    WarningCollector warnings;
    SdfPathVector paths;
    Diagnostics graphDiagnostics = std::move(carried);
    // Prim attribution is per capture; a carried warning names no prim of this snapshot.
    for (Diagnostic &diagnostic : graphDiagnostics) diagnostic.source = SdfPath();
    {
        TfErrorMark mark;
        graph.Advance(time);
        // Depth-first, parents before children, with an explicit stack rather than recursion.
        for (const SdfPath &path : HdSceneIndexPrimView(graph.Terminal(), SdfPath::AbsoluteRootPath()))
            paths.push_back(path);
        HarvestErrors(mark, SdfPath(), graphDiagnostics);
    }
    snapshot->events = graph.TakeEvents();
    const Affected affected(snapshot->events);

    // Reads are threadsafe by contract; nothing mutates the graph until this pass ends. Copying samples
    // the planned schemas at the current time, which also registers them with the stage scene index
    // for time-change dirtying.
    std::vector<HdRetainedSceneIndex::AddedPrimEntry> entries(paths.size());
    std::vector<char> copied(paths.size(), 0);
    std::vector<Diagnostics> errors(paths.size());
    const HdSceneIndexBase &scene = *graph.Terminal();
    WorkParallelForN(paths.size(), [&](size_t begin, size_t end) {
        for (size_t i = begin; i < end; ++i) {
            if (previous && !affected.Contains(paths[i])) {
                HdSceneIndexPrim kept = previous->scene->GetPrim(paths[i]);
                if (kept.dataSource) {
                    entries[i] = {paths[i], kept.primType, kept.dataSource};
                    continue;
                }
            }
            WarningCollector::ScopedSource source(paths[i]);
            TfErrorMark mark;
            HdSceneIndexPrim prim = scene.GetPrim(paths[i]);
            entries[i] = {paths[i], prim.primType, CopyPlannedSchemas(prim.dataSource)};
            copied[i] = 1;
            HarvestErrors(mark, paths[i], errors[i]);
        }
    });

    snapshot->scene = HdRetainedSceneIndex::New();
    snapshot->scene->AddPrims(entries);
    // Warnings attributed to a copied prim belong to it; the rest were posted by the graph itself.
    std::unordered_map<SdfPath, Diagnostics, SdfPath::Hash> warned;
    for (Diagnostic &warning : warnings.Take()) {
        if (warning.source.IsEmpty())
            graphDiagnostics.push_back(std::move(warning));
        else
            warned[warning.source].push_back(std::move(warning));
    }
    UniqueAppender all(snapshot->diagnostics);
    all.Append(graphDiagnostics);
    for (size_t i = 0; i < paths.size(); ++i) {
        Diagnostics own;
        if (copied[i]) {
            ++snapshot->copied;
            UniqueAppender appender(own);
            appender.Append(errors[i]);
            if (auto found = warned.find(paths[i]); found != warned.end()) appender.Append(found->second);
        } else if (auto kept = previous->primDiagnostics.find(paths[i]); kept != previous->primDiagnostics.end()) {
            own = kept->second;
        }
        if (own.empty()) continue;
        all.Append(own);
        snapshot->primDiagnostics.emplace(paths[i], std::move(own));
    }
    return snapshot;
}

}  // namespace hydra_bridge
