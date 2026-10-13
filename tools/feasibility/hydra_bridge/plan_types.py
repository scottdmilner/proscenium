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

    from pxr import Gf, Vt

# The subsets of bpy's AttributeDomainItems and AttributeTypeItems the planner produces (plan.h).
PlanDomain = Literal["POINT", "FACE", "CORNER"]
PlanDataType = Literal["FLOAT", "FLOAT2", "FLOAT_VECTOR", "FLOAT_COLOR", "INT"]
Severity = Literal["info", "warning", "error"]

# The Vt array types plan arrays arrive as, one value per element. Lazy aliases, so this module loads without pxr.
type AttributeArray = Vt.FloatArray | Vt.Vec2fArray | Vt.Vec3fArray | Vt.Vec4fArray | Vt.IntArray
type PlanArray = AttributeArray
type PropertyScalar = bool | int | float | str
type PropertyValue = PropertyScalar | list[PropertyScalar] | list[list[PropertyScalar]]


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
    def diagnostics(self) -> list[DiagnosticRecord]: ...
