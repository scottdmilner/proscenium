// An immutable capture of the terminal scene index at one time code, built with Hydra's own tools:
// HdMakeStaticCopy of the schemas planning reads (PlannedSchemas), per prim, in an HdRetainedSceneIndex.
// Later stage edits and time changes cannot reach it, and Hydra's traversal and debug printing work on
// it. VtArrays share storage copy-on-write, so copying arrays is cheap. Paths here are Hydra paths.
#pragma once

#include "copy_bindings.h"
#include "diagnostics.h"

#include <pxr/pxr.h>
#include <pxr/imaging/hd/retainedSceneIndex.h>
#include <pxr/usd/sdf/path.h>
#include <pxr/usd/usd/timeCode.h>

#include <memory>
#include <string>
#include <unordered_map>
#include <vector>

namespace hydra_bridge {

// The scene-index observer notices, one per prim entry.
enum class EventKind { Added, Removed, Dirtied, Renamed };

const char *EventKindName(EventKind kind);  // "added", "removed", "dirtied", "renamed"

struct Event {
    EventKind kind;
    pxr::SdfPath path;                  // for a rename, the new path
    pxr::SdfPath oldPath;               // renamed only
    std::vector<std::string> locators;  // dirtied only
};

struct Snapshot {
    pxr::UsdTimeCode time;
    // Every prim, with the planned schemas sampled at the capture time. Never modified after capture.
    // An incremental capture shares the previous snapshot's containers for prims no notice named.
    pxr::HdRetainedSceneIndexRefPtr scene;
    std::vector<Event> events;  // notices delivered since the previous capture
    size_t copied = 0;          // prims copied by this capture, rather than shared with the previous one
    // Errors and warnings posted while copying each prim, kept so a shared prim keeps its diagnostics.
    std::unordered_map<pxr::SdfPath, Diagnostics, pxr::SdfPath::Hash> primDiagnostics;
    Diagnostics diagnostics;  // all of them, without duplicates; sources are Hydra paths
    // WORKAROUND for OpenUSD #3690 (copy_bindings.h): UsdShade's bindings for the copies binding collections
    // reach, by USD path. Shared between captures until a binding or collection edit or a resync.
    std::shared_ptr<const CopyBindings> copyBindings;
};

using SnapshotPtr = std::shared_ptr<const Snapshot>;

}  // namespace hydra_bridge
