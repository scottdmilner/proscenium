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

#include <cstddef>
#include <memory>
#include <unordered_map>

#include "diagnostics.h"

namespace proscenium {

// The schemas a capture copies, the only ones planning reads.
const PXR_NS::TfTokenVector& PlannedSchemas();
// The primvars a capture copies, out of each prim's primvars schema: a native instancer's instance transforms, and a
// point instancer's per-point translations, rotations, and scales.
const PXR_NS::TfTokenVector& PlannedPrimvars();

struct Snapshot {
  PXR_NS::UsdTimeCode timeCode;
  // Every prim of the chain's terminal; never modified after capture. A capture shares the containers of the prims no
  // notice named since the chain's capture before it.
  PXR_NS::HdRetainedSceneIndexRefPtr sceneIndex;
  // The stage's metadata as UsdGeom reads it, its fallbacks included, which coordinate conversion reads (transforms.md
  // "Coordinate Conversion").
  double metersPerUnit;
  PXR_NS::TfToken upAxis;  // UsdGeomTokens' y or z
  // The Tf errors and warnings posted while capturing, each exact repeat once: first the chain's own, with no source
  // (those posted while building it join its first capture), then each prim's, about its Hydra path, in prim order.
  Diagnostics diagnostics;
  // Each prim's own diagnostics, by Hydra path, so a later capture that shares the prim's copy shares them too.
  std::unordered_map<PXR_NS::SdfPath, Diagnostics, PXR_NS::SdfPath::Hash> primDiagnostics;
  std::size_t copiedPrimCount;  // prims this capture copied, rather than shared with the chain's capture before it
};

using SnapshotPtr = std::shared_ptr<const Snapshot>;

}  // namespace proscenium
