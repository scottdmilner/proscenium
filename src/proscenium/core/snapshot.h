// The evaluated source snapshot (pipeline.md "Evaluated Source Snapshot"): values captured from the scene-index
// chain at one time code, which planning reads. It holds plain values only, so no later stage edit, time change, or
// released stage can reach it, and it borrows nothing from the chain (SNAP-08, SNAP-10).
//
// M6 replaces the capture and the snapshot's contents; the snapshot's role at the boundary stays.
#pragma once

#include <pxr/base/gf/matrix4d.h>
#include <pxr/base/gf/range3d.h>
#include <pxr/pxr.h>
#include <pxr/usd/sdf/path.h>
#include <pxr/usd/usd/timeCode.h>

#include <memory>
#include <optional>
#include <vector>

namespace proscenium {

// Temporary: M5's minimal capture, all its placeholder planner reads, for each drawn gprim outside native and point
// instancing. M6's capture replaces it with what its planner reads.
struct DrawnGprim {
  PXR_NS::SdfPath source;                   // on the composed stage, never a Hydra path
  PXR_NS::GfMatrix4d world{1.0};            // USD's row-vector convention
  std::optional<PXR_NS::GfRange3d> bounds;  // local; absent when Hydra gives the gprim no extent
};

struct Snapshot {
  PXR_NS::UsdTimeCode time;
  std::vector<DrawnGprim> gprims;  // sorted by source path; temporary, as DrawnGprim is
};

using SnapshotPtr = std::shared_ptr<const Snapshot>;

}  // namespace proscenium
