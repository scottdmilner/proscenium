# Types of the compiled core, proscenium.core._core (module.cpp), so ty checks its callers without a build.
from collections.abc import Buffer, Iterable

from pxr import Gf, Usd

def usd_version() -> tuple[int, int, int]: ...
def _post_tf_error(message: str, then_throw: bool = False) -> None: ...  # for tests of error translation only

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

class Diagnostic:
    """A source-side problem the core reports; Python builds the binding's Diagnostic from it.

    Its code is in binding.results.DiagnosticCode, which gives its category and severity. Fields that don't apply are
    empty.
    """

    @property
    def code(self) -> str: ...
    @property
    def source_path(self) -> str: ...  # a composed-stage path
    @property
    def message(self) -> str: ...
    @property
    def property_path(self) -> str: ...
    @property
    def asset(self) -> str: ...
    @property
    def fallback(self) -> str: ...

def diagnostic_codes() -> tuple[str, ...]: ...  # every code the core reports

class PlanSettings:
    """The binding settings planning reads. Raises ValueError for a name that isn't a USD purpose.

    Each destination's USD purposes, the planner adding guide to the viewport's, so a guide explicitly visible displays
    there; and whether units and up axis are converted, which off makes the correction matrix the identity.
    """

    def __init__(
        self, viewport_purposes: Iterable[str], render_purposes: Iterable[str], coordinate_conversion: bool = False
    ) -> None: ...
    @property
    def viewport_purposes(self) -> tuple[str, ...]: ...  # sorted, each once
    @property
    def render_purposes(self) -> tuple[str, ...]: ...
    @property
    def coordinate_conversion(self) -> bool: ...

class PlanningContext:
    """Plain values captured before planning. Raises ValueError for a unit scale not positive and finite."""

    def __init__(self, unit_scale: float, representation_version: int) -> None: ...
    @property
    def unit_scale(self) -> float: ...
    @property
    def representation_version(self) -> int: ...

# A plan's parts name its resources by their positions in Plan.resources, within that plan only.

class PlannedResource:
    """A planned Blender resource identified by its role, source entity, and index within its copy."""

    @property
    def role(self) -> str: ...
    @property
    def entity(self) -> str: ...  # its copy's source entity
    @property
    def object_index_in_copy(self) -> int: ...  # among its copy's objects
    @property
    def source_entity_paths(self) -> tuple[str, ...]: ...  # composed-stage paths
    @property
    def dependency_resource_indices(self) -> tuple[int, ...]: ...  # dependencies in Plan.resources

class Partition:
    @property
    def resources(self) -> tuple[int, ...]: ...

class CorrespondenceEntry:
    @property
    def object_resource_index(self) -> int: ...  # in Plan.resources: the object showing this source entity
    @property
    def source(self) -> str: ...  # an instance-proxy path inside native instances
    @property
    def instance_context(self) -> tuple[str, ...]: ...  # provisional: native-instance roots, outermost first

class GeometryDescription:
    """Provisional (M8 replaces it): a mesh's geometry, shared by every drawn copy of the mesh."""

    @property
    def source(self) -> str: ...  # its first drawn copy's, in source order
    @property
    def extent(self) -> Buffer: ...  # local (min x, y, z, max x, y, z), a read-only 'f' Vt.FloatArray; empty for none
    @property
    def content_key(self) -> str: ...  # provisional: its source's path; M8 keys a mesh by its content

class BatchGroup:
    """Copies a batch shows as instances of one prototype. Provisional: M9 and M10 add materials, color, primvars."""

    @property
    def geometry(self) -> int: ...  # in Plan.geometries
    @property
    def viewport(self) -> bool: ...
    @property
    def render(self) -> bool: ...
    @property
    def coincident_copy_index(self) -> int: ...  # among groups with the same key, by coincident world transform
    @property
    def members(self) -> Buffer: ...  # 'i': copy indices, ascending

class Plan:
    """The immutable display plan.

    Each read of a tuple property builds the tuple anew, converting every element, so read one once per use. Drawn
    copies are in source order, one per correspondence entry, and their content is read-only buffers (Vt arrays), one
    element per copy unless noted, which lend the plan's storage without copying.
    """

    @property
    def time_code(self) -> Usd.TimeCode: ...
    @property
    def context(self) -> PlanningContext: ...
    @property
    def partitions(self) -> tuple[Partition, ...]: ...
    @property
    def resources(self) -> tuple[PlannedResource, ...]: ...
    @property
    def correspondence(self) -> tuple[CorrespondenceEntry, ...]: ...
    @property
    def copy_count(self) -> int: ...
    @property
    def copy_worlds(self) -> Buffer: ...  # 'f', 16 each: the world matrix in Blender's layout (USD's row-major one)
    @property
    def copy_objects(self) -> Buffer: ...  # 'i': its object, in resources
    @property
    def copy_geometries(self) -> Buffer: ...  # 'i': its geometry description, in geometries; -1 for none
    @property
    def copy_placeholders(self) -> Buffer: ...  # 'i': its placeholder, in placeholder_bounds; -1 for none
    @property
    def placeholder_bounds(self) -> Buffer: ...  # 'f', 6 each: local (min x, y, z, max x, y, z)
    @property
    def copy_viewport(self) -> Buffer: ...  # '?': whether it displays in the viewport
    @property
    def copy_render(self) -> Buffer: ...  # '?': whether it displays in the final render
    @property
    def copy_shears(self) -> Buffer: ...  # 'i': its shear split, in the two buffers below; -1 for none
    @property
    def shear_parent_worlds(self) -> Buffer: ...  # 'f', 16 each, as copy_worlds: its shear parent's world matrix
    @property
    def shear_object_bases(self) -> Buffer: ...  # 'f', 16 each: its object's basis below the shear parent
    @property
    def geometries(self) -> tuple[GeometryDescription, ...]: ...
    @property
    def diagnostics(self) -> tuple[Diagnostic, ...]: ...
    def batch_groups(
        self, minimum: int
    ) -> tuple[
        tuple[BatchGroup, ...], Buffer
    ]: ...  # groups, and single copies  # in the order found; once per prim for its copies

def plan(snapshot: Snapshot, settings: PlanSettings, context: PlanningContext) -> Plan: ...  # ValueError: version

# EXCEPTION to the rule against test-only API (with the user, 2026-11-06): each drawn copy's world transform, by source,
# as Hydra's own values compose it, ignoring a reset transform stack inside an instance. Only the known-gap check for
# OpenUSD #862 calls it: the bug shows only in Hydra's composition, which nothing else exposes.
def _hydra_composed_worlds(snapshot: Snapshot) -> dict[str, Gf.Matrix4d]: ...
