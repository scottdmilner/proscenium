"""Apply a Hydra bridge plan to Blender. Plan arrays reach foreach_set as flat views of Vt arrays, never as lists."""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING, Any

import bpy
from mathutils import Matrix

if TYPE_CHECKING:
    # bpy's attribute enums exist only as Literal aliases in the stubs; at run time they are RNA enum strings.
    from bpy.stub_internal.rna_enums import AttributeDomainItems, AttributeTypeItems


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
ATTRIBUTE_FORMATS: dict[AttributeTypeItems, tuple[BufferFormat, ForeachProperty]] = {
    "FLOAT": (BufferFormat.FLOAT, ForeachProperty.VALUE),
    "FLOAT2": (BufferFormat.FLOAT, ForeachProperty.VECTOR),
    "FLOAT_VECTOR": (BufferFormat.FLOAT, ForeachProperty.VECTOR),
    "FLOAT_COLOR": (BufferFormat.FLOAT, ForeachProperty.COLOR),
    "INT": (BufferFormat.INT, ForeachProperty.VALUE),
}
# The domains the plan produces.
PLAN_DOMAINS: frozenset[AttributeDomainItems] = frozenset({"POINT", "FACE", "CORNER"})


def flat(array: Any, fmt: BufferFormat) -> memoryview:
    """A 1-D view of a Vt array: Blender rejects multi-dimensional buffers. No data is copied."""
    view = memoryview(array)
    if view.format != fmt:
        raise TypeError(f"Expected buffer format {fmt!r}, found {view.format!r}")
    return view.cast("B").cast(fmt)  # ty: ignore[no-matching-overload] - stubs list only literal formats


def apply(plan: Any, collection: bpy.types.Collection) -> list[bpy.types.Object]:
    """Create the plan's materials, meshes, and objects; returns the objects in plan order."""
    materials = [_material(data) for data in plan.materials]
    meshes = [_mesh(data, materials) for data in plan.meshes]
    return [_object(data, meshes, collection) for data in plan.objects]


def _material(data: dict[str, Any]) -> bpy.types.Material:
    material = bpy.data.materials.new(data["name"])
    material["proscenium_sources"] = data["sources"]
    # Viewport color only: shader translation is M9's.
    color = data["parameters"].get("diffuseColor")
    if color is not None:
        material.diffuse_color = (*color, 1.0)
    return material


def _mesh(data: dict[str, Any], materials: list[bpy.types.Material]) -> bpy.types.Mesh:
    mesh = bpy.data.meshes.new(data["name"])
    positions = flat(data["positions"], BufferFormat.FLOAT)
    corner_verts = flat(data["corner_verts"], BufferFormat.INT)
    face_offsets = flat(data["face_offsets"], BufferFormat.INT)
    mesh.vertices.add(len(positions) // 3)
    mesh.loops.add(len(corner_verts))
    mesh.polygons.add(len(face_offsets))
    _data(mesh.attributes["position"]).foreach_set(ForeachProperty.VECTOR, positions)
    _data(mesh.attributes[".corner_vert"]).foreach_set(ForeachProperty.VALUE, corner_verts)
    mesh.polygons.foreach_set("loop_start", face_offsets)
    mesh.update(calc_edges=True)
    for slot in data["material_slots"]:
        mesh.materials.append(None if slot is None else materials[slot])
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


def _object(data: dict[str, Any], meshes: list[bpy.types.Mesh], collection: bpy.types.Collection) -> bpy.types.Object:
    name = data["source"].rsplit("/", 1)[-1]
    obj = bpy.data.objects.new(name, None if data["mesh"] is None else meshes[data["mesh"]])
    collection.objects.link(obj)
    matrix = data["matrix"]
    # USD multiplies row vectors (translation in the last row); Blender multiplies column vectors.
    obj.matrix_world = Matrix([[matrix[row][col] for col in range(4)] for row in range(4)]).transposed()
    obj.hide_viewport = obj.hide_render = not data["visible"]
    color = data["primvars"].get("displayColor")
    if color is not None and len(color) == 1:
        obj.color = (*color[0], 1.0)
    obj["proscenium_source"] = data["source"]
    obj["proscenium_instance_context"] = list(data["instance_context"])
    if data["placeholder_type"] is not None:
        obj.empty_display_type = "PLAIN_AXES"
        obj["proscenium_placeholder"] = data["placeholder_type"]
    return obj
