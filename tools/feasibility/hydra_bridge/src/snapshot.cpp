#include "snapshot.h"

namespace hydra_bridge {

const char *EventKindName(EventKind kind) {
    switch (kind) {
    case EventKind::Added:
        return "added";
    case EventKind::Removed:
        return "removed";
    case EventKind::Dirtied:
        return "dirtied";
    case EventKind::Renamed:
        return "renamed";
    }
    return "added";
}

}  // namespace hydra_bridge
