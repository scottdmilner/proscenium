"""Apply a Hydra bridge plan to Blender. Plan arrays reach foreach_set as flat views of Vt arrays, never as lists."""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING, get_args

import bpy
from mathutils import Matrix
from plan_types import PlanDataType, PlanDomain

if TYPE_CHECKING:
    from collections.abc import Sequence

    # bpy's attribute enums exist only as Literal aliases in the stubs; at run time they are RNA enum strings.
    from bpy.stub_internal.rna_enums import AttributeDomainItems, AttributeTypeItems
    from plan_types import MaterialRecord, MeshRecord, ObjectRecord, Plan, PlanArray


class BufferFormat(StrEnum):
    """struct format characters of Blender's raw element types."""

    FLOAT = "f"
    INT = "i"


class ForeachProperty(StrEnum):
    """The property foreach_set writes on attribute data, by data type."""

    VALUE = "value"
    VECTOR = "vector"
    COLOR = "color"


# The format must match Blender's raw type exactly, or foreach_set silently falls back to reading items one by one.
ATTRIBUTE_FORMATS: dict[PlanDataType, tuple[BufferFormat, ForeachProperty]] = {
    "FLOAT": (BufferFormat.FLOAT, ForeachProperty.VALUE),
    "FLOAT2": (BufferFormat.FLOAT, ForeachProperty.VECTOR),
    "FLOAT_VECTOR": (BufferFormat.FLOAT, ForeachProperty.VECTOR),
    "FLOAT_COLOR": (BufferFormat.FLOAT, ForeachProperty.COLOR),
    "INT": (BufferFormat.INT, ForeachProperty.VALUE),
}
PLAN_DOMAINS: frozenset[PlanDomain] = frozenset(get_args(PlanDomain))


def flat(array: PlanArray, fmt: BufferFormat) -> memoryview:
    """A 1-D view of a Vt array: Blender rejects multi-dimensional buffers. No data is copied."""
    view = memoryview(array)  # ty: ignore[invalid-argument-type] - the pxr stubs omit Vt arrays' buffer protocol
    if view.format != fmt:
        raise TypeError(f"Expected buffer format {fmt!r}, found {view.format!r}")
    if view.nbytes == 0:  # an empty array's (0, 3) shape can't be cast
        return memoryview(b"").cast(fmt)  # ty: ignore[no-matching-overload] - stubs list only literal formats
    return view.cast("B").cast(fmt)  # ty: ignore[no-matching-overload] - stubs list only literal formats


def apply(plan: Plan, collection: bpy.types.Collection) -> list[bpy.types.Object]:
    """Create the plan's materials, meshes, and objects; returns the objects in plan order."""
    materials = [_material(data) for data in plan.materials]
    meshes = [_mesh(data) for data in plan.meshes]
    return [_object(index, data, meshes, materials, collection) for index, data in enumerate(plan.objects)]


def _material(data: MaterialRecord) -> bpy.types.Material:
    material = bpy.data.materials.new(data["name"])
    material["proscenium_sources"] = data["sources"]
    # Viewport color only: shader translation is M9's.
    color = data["parameters"].get("diffuseColor")
    if color is not None:
        material.diffuse_color = (*color, 1.0)
    return material


def _mesh(data: MeshRecord) -> bpy.types.Mesh:
    mesh = bpy.data.meshes.new(data["name"])
    positions = flat(data["positions"], BufferFormat.FLOAT)
    corner_verts = flat(data["corner_verts"], BufferFormat.INT)
    face_offsets = flat(data["face_offsets"], BufferFormat.INT)
    mesh.vertices.add(len(positions) // 3)
    mesh.loops.add(len(corner_verts))
    mesh.polygons.add(len(face_offsets))
    # A mesh with no points has no position layer, and one with no faces no corner layer.
    if len(positions):
        _data(mesh.attributes["position"]).foreach_set(ForeachProperty.VECTOR, positions)
    if len(corner_verts):
        _data(mesh.attributes[".corner_vert"]).foreach_set(ForeachProperty.VALUE, corner_verts)
    # Unlike the attribute transfers, Blender copies this buffer into a temporary, 4 bytes per face.
    mesh.polygons.foreach_set("loop_start", face_offsets)
    mesh.update(calc_edges=True)
    # Empty slots: each object links its own materials, so one mesh serves the viewport and the render.
    for _ in range(data["slot_count"]):
        mesh.materials.append(None)
    material_index = _new_attribute(mesh, "material_index", "INT", "FACE")
    _data(material_index).foreach_set(ForeachProperty.VALUE, flat(data["material_indices"], BufferFormat.INT))
    for attribute in data["attributes"]:
        data_type, domain = attribute["data_type"], attribute["domain"]
        # A name the plan shouldn't produce raises here rather than reaching Blender.
        if data_type not in ATTRIBUTE_FORMATS or domain not in PLAN_DOMAINS:
            raise ValueError(f"Unexpected attribute kind in the plan: {data_type} on {domain}")
        fmt, prop = ATTRIBUTE_FORMATS[data_type]
        created = _new_attribute(mesh, attribute["name"], data_type, domain)
        _data(created).foreach_set(prop, flat(attribute["data"], fmt))
    return mesh


def _new_attribute(
    mesh: bpy.types.Mesh, name: str, data_type: AttributeTypeItems, domain: AttributeDomainItems
) -> bpy.types.Attribute:
    return mesh.attributes.new(name, data_type, domain)


def _data(attribute: bpy.types.Attribute) -> bpy.types.bpy_prop_collection:
    return attribute.data  # ty: ignore[unresolved-attribute] - Attribute.data is missing from the stubs


def _bounds_mesh(name: str, bounds: tuple[Sequence[float], Sequence[float]]) -> bpy.types.Mesh:
    """The eight corners of a placeholder's local bounds; the object draws only its bounding box."""
    low, high = bounds
    mesh = bpy.data.meshes.new(name)
    corners = [(x, y, z) for x in (low[0], high[0]) for y in (low[1], high[1]) for z in (low[2], high[2])]
    mesh.from_pydata(corners, [], [])
    return mesh


def _object(
    index: int,
    data: ObjectRecord,
    meshes: list[bpy.types.Mesh],
    materials: list[bpy.types.Material],
    collection: bpy.types.Collection,
) -> bpy.types.Object:
    name = data["source"].rsplit("/", 1)[-1]
    bounds = data["bounds"]
    if data["mesh"] is not None:
        obj_data = meshes[data["mesh"]]
    elif bounds is not None:
        obj_data = _bounds_mesh(name, bounds)
    else:
        obj_data = None
    obj = bpy.data.objects.new(name, obj_data)
    collection.objects.link(obj)
    matrix = data["matrix"]
    # USD multiplies row vectors (translation in the last row); Blender multiplies column vectors.
    obj.matrix_world = Matrix([[matrix[row, col] for col in range(4)] for row in range(4)]).transposed()
    # Each destination shows its own prim purposes; an object can be in one, both, or neither.
    obj.hide_viewport = not data["viewport"]
    obj.hide_render = not data["render"]
    for slot, material in zip(obj.material_slots, data["material_slots"], strict=True):
        slot.link = "OBJECT"
        slot.material = None if material is None else materials[material]
    color = data["primvars"].get("displayColor")
    if color is not None and len(color) == 1:
        obj.color = (*color[0], 1.0)
    # Constant primvars by name, which an Attribute node of type Object reads; the plan converted them.
    for name, value in data["properties"].items():
        obj[name] = value
    obj["proscenium_source"] = data["source"]
    obj["proscenium_instance_context"] = list(data["instance_context"])
    # The display element it realizes (M4): its plan index, which the interaction functions take and return.
    obj["proscenium_element"] = index
    if data["placeholder_type"] is not None:
        # A bounding box when the plan has bounds, otherwise an empty marker.
        if bounds is not None:
            obj.display_type = "BOUNDS"
        else:
            obj.empty_display_type = "PLAIN_AXES"
        obj["proscenium_placeholder"] = data["placeholder_type"]
    return obj
