// The reader of a snapshot's records (prim_record.h).
#pragma once

#include "prim_record.h"
#include "snapshot.h"

namespace proscenium {

// Every prim of the snapshot as a record, read once. Serial, as capture is, until C6's per-thread error collection
// lets it run in parallel as the bridge's does.
PrimTable ReadPrims(const Snapshot& snapshot);

}  // namespace proscenium
