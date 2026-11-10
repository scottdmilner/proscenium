// The reader of a snapshot's records (prim_record.h).
#pragma once

#include "prim_record.h"
#include "snapshot.h"

namespace proscenium {

// Every prim of the snapshot as a record, read once, in parallel, as the bridge's reader does. It reads only the
// snapshot's static copies; a Tf error posted on a worker thread would be printed, not raised, as in the bridge.
PrimTable ReadPrims(const Snapshot& snapshot);

}  // namespace proscenium
