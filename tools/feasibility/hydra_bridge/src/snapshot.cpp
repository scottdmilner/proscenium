#include "snapshot.h"

namespace hydra_bridge {

const char *SceneIndexEventKindName(SceneIndexEventKind kind) {
    switch (kind) {
    case SceneIndexEventKind::Added:
        return "added";
    case SceneIndexEventKind::Removed:
        return "removed";
    case SceneIndexEventKind::Dirtied:
        return "dirtied";
    case SceneIndexEventKind::Renamed:
        return "renamed";
    }
    return "added";
}

}  // namespace hydra_bridge
