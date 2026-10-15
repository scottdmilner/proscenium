// An immutable capture of the terminal scene index at one time code, built with Hydra's own tools:
// HdMakeStaticCopy of the schemas planning reads (PlannedSchemas), per prim, in an HdRetainedSceneIndex.
// Later stage edits and time changes cannot reach it, and Hydra's traversal and debug printing work on
// it. VtArrays share storage copy-on-write, so copying arrays is cheap. Paths here are Hydra paths.
#pragma once

#include "diagnostics.h"

#include <pxr/pxr.h>
#include <pxr/imaging/hd/retainedSceneIndex.h>
#include <pxr/usd/sdf/path.h>
#include <pxr/usd/usd/timeCode.h>

#include <memory>
#include <string>
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
    pxr::HdRetainedSceneIndexRefPtr scene;
    std::vector<Event> events;  // notices delivered since the previous capture
    Diagnostics diagnostics;    // sources are Hydra paths
};

using SnapshotPtr = std::shared_ptr<const Snapshot>;

}  // namespace hydra_bridge
