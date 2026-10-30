"""Apply a Hydra bridge plan to Blender. Plan arrays reach foreach_set as flat views of Vt arrays, never as lists.

Every display color shows under one setting, Solid shading's Attribute color (M4 Phase D, D10), which shows a
mesh's active color attribute, a point or corner one only. Vertex and faceVarying values are already color
attributes on points and corners, and the mesh's active color. A uniform value is a face attribute, so the mesh
also holds it on corners (DISPLAY_CORNERS), its active color. A constant value is per copy, so a mesh whose copies
all share one holds it as a point attribute named displayColor (set_mesh_colors). Otherwise a Geometry Nodes
modifier on the copy's object (DISPLAY_COLOR_MODIFIER) changes the attribute on the evaluated mesh: it stores a
copy's own constant value on points, or removes the mesh's from a copy with none. So copies keep sharing their
mesh, and only those a modifier changes are evaluated apart.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum, StrEnum
from typing import TYPE_CHECKING, Any, get_args

import bpy
import numpy
from mathutils import Matrix
from plan_types import PlanDataType, PlanDomain

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

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
# Axes whose cosine is above this are not orthogonal, so an object's location, rotation, and scale can't hold them.
SHEAR_TOLERANCE = 1e-6
# On a parent empty (M4): the USD source of the copy whose shear it carries.
SHEAR_PARENT = "proscenium_shear_of"
# The ID properties that tie Blender data to the binding, which detach removes (M4, B7). Constant primvars keep
# their own names, since an Attribute node reads them, so they aren't among these.
OBJECT_PROPERTIES = (
    "proscenium_source",
    "proscenium_instance_context",
    "proscenium_element",
    "proscenium_placeholder",
    SHEAR_PARENT,
)
MATERIAL_PROPERTIES = ("proscenium_sources",)
MESH_PROPERTIES = ("proscenium_display_color",)
DISPLAY_COLOR = "displayColor"
# A uniform displayColor's values on corners, which Solid shading's Attribute color shows, unlike face values.
DISPLAY_CORNERS = "displayColor_corners"
# The modifier that shows a copy's constant display color where its mesh doesn't, and its node group, which every
# copy shares.
DISPLAY_COLOR_MODIFIER = "Display Color"
DISPLAY_COLOR_GROUP = "proscenium_display_color"
# The node group's inputs: the copy's color and opacity, and which DisplayColorMode it applies.
COLOR_INPUT = "Color"
MODE_INPUT = "Mode"
# On a mesh holding a constant displayColor for all its copies: that color, as Blender stores an object color.
MESH_COLOR = MESH_PROPERTIES[0]


class DisplayColorMode(IntEnum):
    """What a copy's display color modifier does to its mesh's displayColor."""

    POINT = 0  # stores the copy's constant value on points
    REMOVE = 1  # removes the mesh's constant value, which the copy doesn't have


def flat(array: PlanArray, fmt: BufferFormat) -> memoryview:
    """A 1-D view of a Vt array: Blender rejects multi-dimensional buffers. No data is copied."""
    view = memoryview(array)  # ty: ignore[invalid-argument-type] - the pxr stubs omit Vt arrays' buffer protocol
    if view.format != fmt:
        raise TypeError(f"Expected buffer format {fmt!r}, found {view.format!r}")
    if view.nbytes == 0:  # an empty array's (0, 3) shape can't be cast
        return memoryview(b"").cast(fmt)  # ty: ignore[no-matching-overload] - stubs list only literal formats
    return view.cast("B").cast(fmt)  # ty: ignore[no-matching-overload] - stubs list only literal formats


@dataclass(frozen=True)
class Display:
    """What a plan's application holds, each list in plan order."""

    objects: list[bpy.types.Object]
    meshes: list[bpy.types.Mesh]
    materials: list[bpy.types.Material]


def apply(plan: Plan, collection: bpy.types.Collection) -> Display:
    """Create the plan's materials, meshes, and objects."""
    materials = [new_material(data) for data in plan.materials]
    meshes = [new_mesh(data) for data in plan.meshes]
    records = plan.objects
    set_mesh_colors(dict(enumerate(meshes)), records)
    objects = [new_object(index, data, meshes, materials, collection) for index, data in enumerate(records)]
    return Display(objects, meshes, materials)


def new_material(data: MaterialRecord) -> bpy.types.Material:
    """A plan material's viewport stand-in."""
    material = bpy.data.materials.new(data["name"])
    material["proscenium_sources"] = data["sources"]
    # Viewport color only: shader translation is M9's.
    color = data["parameters"].get("diffuseColor")
    if color is not None:
        material.diffuse_color = (*color, 1.0)
    return material


def new_mesh(data: MeshRecord) -> bpy.types.Mesh:
    """A plan mesh, with empty material slots for its objects to fill."""
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
        if attribute["name"] == DISPLAY_COLOR and domain == "FACE":
            _new_corner_colors(mesh, flat(attribute["data"], fmt), face_offsets, len(corner_verts))
    # Solid shading's Attribute color shows the active color: displayColor, whether the mesh holds it or a copy's
    # modifier adds it, or its uniform values on corners.
    shown = DISPLAY_CORNERS if DISPLAY_CORNERS in mesh.attributes else DISPLAY_COLOR
    mesh.color_attributes.active_color_name = shown
    return mesh


def _new_corner_colors(mesh: bpy.types.Mesh, faces: memoryview, face_offsets: memoryview, corners: int) -> None:
    """The mesh's DISPLAY_CORNERS: each face's displayColor on each of its corners."""
    starts = numpy.frombuffer(face_offsets, dtype=numpy.int32)
    counts = numpy.diff(starts, append=corners)
    values = numpy.repeat(numpy.frombuffer(faces, dtype=numpy.float32).reshape(-1, 4), counts, axis=0)
    _data(_new_attribute(mesh, DISPLAY_CORNERS, "FLOAT_COLOR", "CORNER")).foreach_set("color", values.ravel())


def _new_attribute(
    mesh: bpy.types.Mesh, name: str, data_type: AttributeTypeItems, domain: AttributeDomainItems
) -> bpy.types.Attribute:
    return mesh.attributes.new(name, data_type, domain)


def _data(attribute: bpy.types.Attribute) -> bpy.types.bpy_prop_collection:
    return attribute.data  # ty: ignore[unresolved-attribute] - Attribute.data is missing from the stubs


def stored_color(data: ObjectRecord) -> list[float]:
    """A copy's object color as Blender stores it, in single precision."""
    return numpy.array(object_color(data), dtype=numpy.float32).tolist()


def set_mesh_colors(meshes: Mapping[int, bpy.types.Mesh], records: Iterable[ObjectRecord]) -> None:
    """Give each of `meshes`, by plan index, the constant displayColor all its copies in `records` share, if any.

    `records` must hold every copy of those meshes. A copy with a constant displayColor has a mesh with none of its
    own, since the mesh's comes first.
    """
    colors: dict[int, list[float] | None] = {}
    for record in records:
        mesh = record["mesh"]
        if mesh is not None and mesh in meshes:
            color = stored_color(record) if DISPLAY_COLOR in record["properties"] else None
            if colors.setdefault(mesh, color) != color:
                colors[mesh] = None
    for index, color in colors.items():
        mesh = meshes[index]
        if color is None or DISPLAY_COLOR in mesh.attributes:
            continue
        attribute = _new_attribute(mesh, DISPLAY_COLOR, "FLOAT_COLOR", "POINT")
        _data(attribute).foreach_set("color", numpy.tile(numpy.array(color, dtype=numpy.float32), len(mesh.vertices)))
        mesh[MESH_COLOR] = color


def show_display_color(obj: bpy.types.Object, constant: bool) -> None:
    """Give a mesh copy the modifier that shows its display color, or take it away, changing only what differs.

    `constant` says whether the copy has a constant displayColor, which its object color holds with its opacity.
    The plan gives a copy none when its mesh has a displayColor of its own, which comes first and shows without a
    modifier. A copy needs no modifier when its mesh already shows its color, nor does an object that isn't a
    mesh's.
    """
    if obj.type != "MESH":
        return
    mesh: Any = obj.data
    held = mesh.get(MESH_COLOR)
    mode = None
    if constant:
        mode = None if held is not None and list(held) == list(obj.color) else DisplayColorMode.POINT
    elif held is not None:
        mode = DisplayColorMode.REMOVE
    modifier: Any = obj.modifiers.get(DISPLAY_COLOR_MODIFIER)
    if mode is None:
        if modifier is not None:
            obj.modifiers.remove(modifier)
        return
    tree = _display_color_group()
    if modifier is None:
        added: Any = obj.modifiers.new(DISPLAY_COLOR_MODIFIER, "NODES")
        added.node_group = tree
        modifier = added
    sockets = tree.interface.items_tree
    color = getattr(modifier.properties.inputs, sockets[COLOR_INPUT].identifier)
    applied = getattr(modifier.properties.inputs, sockets[MODE_INPUT].identifier)
    if applied.value == mode and list(color.value) == list(obj.color):
        return
    applied.value, color.value = mode, obj.color
    # Setting a modifier's inputs doesn't tag its object for evaluation (Blender 5.2, ad hoc).
    obj.update_tag()


def _display_color_group() -> Any:
    """The node group of every copy's display color modifier, created once.

    It applies its Mode to the mesh's displayColor: stores the Color input on every point, or removes it.
    """
    found = bpy.data.node_groups.get(DISPLAY_COLOR_GROUP)
    if found is not None:
        return found
    tree: Any = bpy.data.node_groups.new(DISPLAY_COLOR_GROUP, "GeometryNodeTree")
    tree.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    tree.interface.new_socket(COLOR_INPUT, in_out="INPUT", socket_type="NodeSocketColor")
    tree.interface.new_socket(MODE_INPUT, in_out="INPUT", socket_type="NodeSocketInt")
    tree.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    nodes, links = tree.nodes, tree.links
    group_in, group_out = nodes.new("NodeGroupInput"), nodes.new("NodeGroupOutput")
    store = nodes.new("GeometryNodeStoreNamedAttribute")
    store.data_type, store.domain = "FLOAT_COLOR", "POINT"
    store.inputs["Name"].default_value = DISPLAY_COLOR
    links.new(group_in.outputs["Geometry"], store.inputs["Geometry"])
    links.new(group_in.outputs[COLOR_INPUT], store.inputs["Value"])
    results = {DisplayColorMode.POINT: store.outputs["Geometry"]}
    remove = nodes.new("GeometryNodeRemoveAttribute")
    remove.inputs["Name"].default_value = DISPLAY_COLOR
    links.new(group_in.outputs["Geometry"], remove.inputs["Geometry"])
    results[DisplayColorMode.REMOVE] = remove.outputs["Geometry"]
    switch = nodes.new("GeometryNodeIndexSwitch")
    switch.data_type = "GEOMETRY"
    while len(switch.index_switch_items) < len(DisplayColorMode):
        switch.index_switch_items.new()
    links.new(group_in.outputs[MODE_INPUT], switch.inputs["Index"])
    for mode in DisplayColorMode:
        links.new(results[mode], switch.inputs[str(mode.value)])
    links.new(switch.outputs["Output"], group_out.inputs["Geometry"])
    return tree


def _bounds_mesh(name: str, bounds: tuple[Sequence[float], Sequence[float]]) -> bpy.types.Mesh:
    """The eight corners of a placeholder's local bounds; the object draws only its bounding box."""
    low, high = bounds
    mesh = bpy.data.meshes.new(name)
    corners = [(x, y, z) for x in (low[0], high[0]) for y in (low[1], high[1]) for z in (low[2], high[2])]
    mesh.from_pydata(corners, [], [])
    return mesh


def _sheared(world: Matrix) -> bool:
    linear = world.to_3x3()
    # mathutils, not numpy: about 20 times faster for one small matrix.
    axes = [linear.col[i] for i in range(3)]  # ty: ignore[not-subscriptable] - the stubs omit MatrixAccess indexing
    return any(
        abs(axes[i].dot(axes[j])) > SHEAR_TOLERANCE * axes[i].length * axes[j].length
        for i, j in ((0, 1), (0, 2), (1, 2))
    )


def _shear_parent(obj: bpy.types.Object, source: str, world: Matrix, collection: bpy.types.Collection) -> None:
    """Give `obj` the sheared `world` through a parent empty, which Blender composes back to float precision.

    The linear part splits by SVD into rotation x scale x rotation: the parent takes the first rotation, the
    scale, and the translation, and the object the second rotation, so neither holds shear. A reflection in
    either rotation moves into a negative scale. The parent can't be selected, so a pick lands on the object.
    """
    u, scale, vt = numpy.linalg.svd(numpy.array(world.to_3x3()))
    if numpy.linalg.det(u) < 0:
        u[:, -1] *= -1
        scale[-1] *= -1
    if numpy.linalg.det(vt) < 0:
        vt[-1, :] *= -1
        scale[-1] *= -1
    parent = bpy.data.objects.new(f"{obj.name} shear", None)
    collection.objects.link(parent)
    parent_world = Matrix((u * scale).tolist()).to_4x4()
    parent_world.translation = world.translation
    parent.matrix_world = parent_world
    parent.hide_select = True
    parent[SHEAR_PARENT] = source
    obj.parent = parent
    obj.matrix_basis = Matrix(vt.tolist()).to_4x4()


def object_color(data: ObjectRecord) -> tuple[float, float, float, float]:
    """A copy's object color: its constant displayColor and displayOpacity of one value each, or opaque white."""
    # From the converted properties, where a one-value array is its value: indexing the Vt array in `primvars`
    # from Python costs about 50 us (ad hoc, ALab).
    color = data["properties"].get("displayColor")
    opacity = data["properties"].get("displayOpacity")
    channels = color if isinstance(color, list) else []
    rgb = [c for c in channels if isinstance(c, float)]
    r, g, b = rgb if len(rgb) == 3 == len(channels) else (1.0, 1.0, 1.0)
    return (r, g, b, opacity if isinstance(opacity, float) else 1.0)


def new_object(
    index: int,
    data: ObjectRecord,
    meshes: list[bpy.types.Mesh],
    materials: list[bpy.types.Material],
    collection: bpy.types.Collection,
) -> bpy.types.Object:
    """Plan object `index` in `collection`, on `meshes` and `materials`, with a shear parent if it needs one."""
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
    world = Matrix([[matrix[row, col] for col in range(4)] for row in range(4)]).transposed()
    if _sheared(world):
        _shear_parent(obj, data["source"], world, collection)
    else:
        obj.matrix_world = world
    # Each destination shows its own prim purposes; an object can be in one, both, or neither.
    obj.hide_viewport = not data["viewport"]
    obj.hide_render = not data["render"]
    for slot, material in zip(obj.material_slots, data["material_slots"], strict=True):
        slot.link = "OBJECT"
        slot.material = None if material is None else materials[material]
    # The object color shows a constant displayColor and displayOpacity, in Solid shading's Object color, and
    # the display color modifier in its Attribute color.
    obj.color = object_color(data)
    if data["mesh"] is not None:  # a placeholder's bounds show no color
        show_display_color(obj, DISPLAY_COLOR in data["properties"])
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
