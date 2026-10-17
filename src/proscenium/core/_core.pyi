# Types of the compiled core, proscenium.core._core (module.cpp), so ty checks its callers without a build.
from pxr import Usd

def usd_version() -> tuple[int, int, int]: ...
def _post_tf_error(message: str) -> None: ...  # for tests of error translation only

class StageHandle:
    """The core's own reference to a caller's stage. Raises ValueError for an invalid stage."""

    def __init__(self, stage: Usd.Stage | None) -> None: ...
    def stage(self) -> Usd.Stage | None: ...  # None once the stage has expired
    def release(self) -> None: ...  # drop the handle's reference; idempotent
    @property
    def released(self) -> bool: ...
