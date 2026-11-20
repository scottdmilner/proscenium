// The reader of a snapshot's records (prim_record.h).
#pragma once

#include "prim_record.h"
#include "snapshot.h"

namespace proscenium {

// Every prim of the snapshot as a record, read once, in parallel, as the bridge's reader does. It reads only the
// snapshot's static copies; a Tf error posted on a worker thread would be printed, not raised, as in the bridge.
PrimTable ReadPrims(const Snapshot& snapshot);

// Frozen original prototype roots, read only when a point-instanced prim needs diagnostic provenance.
PXR_NS::VtArray<PXR_NS::TfToken> ReadPointPrototypeOrigins(const Snapshot& snapshot, const PXR_NS::SdfPath& path);

}  // namespace proscenium
