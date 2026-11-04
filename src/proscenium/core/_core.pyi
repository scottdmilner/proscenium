# Types of the compiled core, proscenium.core._core (module.cpp), so ty checks its callers without a build.
from pxr import Gf, Usd, Vt

def usd_version() -> tuple[int, int, int]: ...
def _post_tf_error(message: str) -> None: ...  # for tests of error translation only

class StageHandle:
    """The core's own reference to a caller's stage. Raises ValueError for an invalid stage."""

    def __init__(self, stage: Usd.Stage | None) -> None: ...
    def stage(self) -> Usd.Stage | None: ...  # None once the stage has expired
    def release(self) -> None: ...  # drop the handle's reference; idempotent
    @property
    def released(self) -> bool: ...

class SceneIndexChain:
    """The Hydra scene-index chain over an evaluation stage. Raises ValueError for an invalid stage."""

    def __init__(self, stage: Usd.Stage | None) -> None: ...
    def stage(self) -> Usd.Stage | None: ...  # None once the stage has expired
    def capture(self, time_code: Usd.TimeCode | float) -> Snapshot: ...  # RuntimeError once released
    def release(self) -> None: ...  # drop the chain and its stage reference; idempotent
    @property
    def released(self) -> bool: ...

class Snapshot:
    """An immutable capture at one time code, which only planning reads."""

class PlanningContext:
    """Plain values captured before planning. Raises ValueError for a unit scale not positive and finite."""

    def __init__(self, unit_scale: float, representation_version: int) -> None: ...
    @property
    def unit_scale(self) -> float: ...
    @property
    def representation_version(self) -> int: ...

# A plan's parts name its resources by their positions in Plan.resources, within that plan only.

class Resource:
    """A managed resource, as its ownership entry records it; a copy's is identified by role, entity, and place."""

    @property
    def role(self) -> str: ...
    @property
    def entity(self) -> str: ...  # its copy's source entity
    @property
    def place(self) -> int: ...  # among its copy's objects
    @property
    def covers(self) -> tuple[str, ...]: ...  # composed-stage paths
    @property
    def uses(self) -> tuple[int, ...]: ...

class Partition:
    @property
    def resources(self) -> tuple[int, ...]: ...

class CorrespondenceEntry:
    @property
    def element(self) -> int: ...  # the object that shows it
    @property
    def source(self) -> str: ...

class Placeholder:
    @property
    def object(self) -> int: ...
    @property
    def bounds_mesh(self) -> int: ...
    @property
    def world(self) -> Gf.Matrix4d: ...  # USD's row-vector convention
    @property
    def bounds(self) -> Vt.FloatArray: ...  # (min x, y, z, max x, y, z), a read-only 'f' buffer; empty for none

class Plan:
    """The immutable display plan."""

    @property
    def time_code(self) -> Usd.TimeCode: ...
    @property
    def context(self) -> PlanningContext: ...
    @property
    def partitions(self) -> tuple[Partition, ...]: ...
    @property
    def resources(self) -> tuple[Resource, ...]: ...
    @property
    def correspondence(self) -> tuple[CorrespondenceEntry, ...]: ...
    @property
    def placeholders(self) -> tuple[Placeholder, ...]: ...

def plan(snapshot: Snapshot, context: PlanningContext) -> Plan: ...  # ValueError for an unplanned version
