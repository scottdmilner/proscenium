// The evaluated source snapshot (pipeline.md "Evaluated Source Snapshot"): what planning reads from the scene-index
// chain at one time code, as a retained scene index (DECISIONS.md "Evaluated snapshot form"). Each prim holds an
// HdMakeStaticCopy of the schemas planning reads, so no later stage edit, time change, or released stage can reach
// it, and its VtArrays share storage copy-on-write, so the arrays it lends stay alive as long as anything holds them
// (SNAP-08, SNAP-10, SNAP-11). Its paths are Hydra paths; planning maps them back to composed-stage sources.
#pragma once

#include <pxr/base/tf/token.h>
#include <pxr/imaging/hd/retainedSceneIndex.h>
#include <pxr/pxr.h>
#include <pxr/usd/usd/timeCode.h>

#include <memory>

namespace proscenium {

// The schemas a capture copies, the only ones planning reads.
const PXR_NS::TfTokenVector& PlannedSchemas();

struct Snapshot {
  PXR_NS::UsdTimeCode time;
  PXR_NS::HdRetainedSceneIndexRefPtr scene;  // every prim of the chain's terminal; never modified after capture
};

using SnapshotPtr = std::shared_ptr<const Snapshot>;

}  // namespace proscenium
