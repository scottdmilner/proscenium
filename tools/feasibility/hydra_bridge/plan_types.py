"""Types of the plan the compiled module hands to Python, mirroring the dicts src/python_views.cpp builds.

The module itself is untyped (it is imported by name), so these are what callers annotate with. Keep them in
step with PlanView in python_views.cpp. No bpy import: the probes use them too.

Prototype only. Production code should bind the plan's records as classes with attribute access (mesh.positions,
not mesh["positions"]) and ship type stubs for them, so the types come from the bindings rather than from a
hand-kept copy that can drift.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal, Protocol, TypedDict

if TYPE_CHECKING:
    from collections.abc import Sequence

    from pxr import Gf, Sdf, Vt

# The subsets of bpy's AttributeDomainItems and AttributeTypeItems the planner produces (plan.h).
PlanDomain = Literal["POINT", "FACE", "CORNER"]
PlanDataType = Literal["FLOAT", "FLOAT2", "FLOAT_VECTOR", "FLOAT_COLOR", "INT"]
Severity = Literal["info", "warning", "error"]

# The Vt array types plan arrays arrive as, one value per element. Lazy aliases, so this module loads without pxr.
type AttributeArray = Vt.FloatArray | Vt.Vec2fArray | Vt.Vec3fArray | Vt.Vec4fArray | Vt.IntArray
type PlanArray = AttributeArray
type PropertyScalar = bool | int | float | str
type PropertyValue = PropertyScalar | list[PropertyScalar] | list[list[PropertyScalar]]
type PathLike = Sdf.Path | str  # what Interaction takes as a path


class AttributeRecord(TypedDict):
    name: str
    domain: PlanDomain
    data_type: PlanDataType
    data: AttributeArray


class MeshRecord(TypedDict):
    name: str
    positions: Vt.Vec3fArray
    corner_verts: Vt.IntArray  # per corner
    face_offsets: Vt.IntArray  # per face: its first corner (Blender's loop_start)
    material_indices: Vt.IntArray  # per face, its material slot: 0 the mesh's own binding, then each subset's
    slot_count: int
    attributes: list[AttributeRecord]
    subdivision_scheme: str
    double_sided: bool


class MaterialRecord(TypedDict):
    name: str
    sources: list[str]  # USD paths, one per drawn copy
    surface_identifier: str
    parameters: dict[str, Any]  # the surface node's authored inputs, any USD value type


class ObjectRecord(TypedDict):
    source: str  # USD path
    instance_context: tuple[str, ...]  # native instance roots, outermost first
    floor: str  # USD path: the outermost native instance root, or the source outside instance contents
    mesh: int | None  # into Plan.meshes; None for a placeholder
    placeholder_type: str | None  # the untranslated type, for a placeholder
    # A placeholder's local (min, max), when it has an extent. Gf.Vec3d at run time; Sequence because the
    # pxr stubs mistype Vec3d's integer indexing.
    bounds: tuple[Sequence[float], Sequence[float]] | None
    matrix: Gf.Matrix4d  # world, USD row-vector convention
    visible: bool  # effective visibility for the object's own purpose
    viewport: bool  # displays in the viewport: visible, and a purpose the viewport includes
    render: bool  # displays in the final render, likewise
    material_slots: list[int | None]  # per mesh slot, into Plan.materials; None for no material
    purpose: str  # Hydra's name: "geometry" for USD's default
    primvars: dict[str, Any]  # constant primvars as USD authored them (Gf and Vt values)
    # The same primvars as ID properties: bool, int, float, str, or lists (nested by vector or matrix row)
    properties: dict[str, PropertyValue]


class DiagnosticRecord(TypedDict):
    severity: Severity
    code: str
    source: str | None  # USD path, or None when it has none
    message: str


class Plan(Protocol):
    """The module's Plan view. Each property builds a fresh list."""

    @property
    def time(self) -> float | None: ...  # None at default time
    @property
    def meshes(self) -> list[MeshRecord]: ...
    @property
    def materials(self) -> list[MaterialRecord]: ...
    @property
    def objects(self) -> list[ObjectRecord]: ...
    @property
    def universe(self) -> list[str]: ...  # USD paths, sorted: the browsing universe
    @property
    def diagnostics(self) -> list[DiagnosticRecord]: ...


class PlanDiff(TypedDict):
    """What a plan changes from the published one, as diff_plans returns it (M4)."""

    meshes: list[int]  # per new mesh: an old mesh with equal content, or -1
    materials: list[int]  # per new material: an equal old material, or -1
    objects: list[int]  # per new object: the old object with its identity, or -1 for an added one
    changed: list[int]  # new objects whose old counterpart differs, in plan order
    removed: list[int]  # old objects with no new counterpart, in plan order


class ResolvedEntity(TypedDict):
    """An element's source entity, as Interaction.resolve_pick returns it."""

    source: str
    instance_context: tuple[str, ...]  # native instance roots, outermost first
    floor: str


class SourceSelection(TypedDict):
    targets: list[str]  # USD paths, in the order of the selected elements, without repeats
    active: str | None  # the active element's target


class Interaction(Protocol):
    """The module's Interaction (M4): the baseline's core interaction functions over a plan and the live stage.

    Elements are plan object indices; a level is None (the prim level) or a registered kind. Paths are taken as
    Sdf.Path or str and returned as str. Each raises RuntimeError once the live stage has expired.
    """

    def resolve_pick(self, element: int) -> ResolvedEntity | None: ...
    def select_targets(
        self, entities: Sequence[tuple[PathLike, Sequence[PathLike]]], level: str | None = None
    ) -> list[str]: ...  # (source, instance context) pairs
    def displayed(self, paths: Sequence[PathLike]) -> list[bool]: ...
    def highlight_targets(self, targets: Sequence[PathLike]) -> list[int]: ...  # elements, in plan order
    def selection_from_blender(
        self, selected: Sequence[int], active: int | None = None, level: str | None = None
    ) -> SourceSelection: ...
