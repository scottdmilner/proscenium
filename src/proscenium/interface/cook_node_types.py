"""The cook's node tree in Blender: a tree type, its sockets, and a node type per node definition.

The node types are built when the extension registers, from the definitions file the cook reads
(proscenium_cook.NODE_DEFINITIONS_PATH), so they follow it without code of their own (docs/phase3/node-tree.md "Node
definitions"). Each node's inputs and outputs are sockets, identified by their attribute's name without its namespace,
and its properties are node properties named `prop_<name>`. A zone's begin names its end with `zone_end`, the end
node's name. Behavior stays in the cook; these types only hold what the tree layer authors (cook_tree_layer).

A Stage Output also holds front-end state that the tree layer doesn't write, so the cook never sees it: `scene`, the
scene its binding displays in, which a new node takes from the context; and `binding_id`, hidden, its binding's
identifier. A copied Stage Output's identifier is cleared, so the copy makes a binding of its own on its next cook.

A link the cook would reject (proscenium_cook.link_problem), such as a Layer into a Prim input, is drawn red, as
Blender draws an invalid link in its own editors, and kept: the tree layer still writes it, and the cook reports it as
incompatible-link. A link through reroutes is checked from the output it starts at. Blender marks every link valid
again after each update of a tree, so the tree's update asks for its links to be marked once Blender's own pass is done,
on a timer, and loading a file or an undo step marks every cook tree's links.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, ClassVar, override

import bpy
from pxr import Sdf

import proscenium_cook

if TYPE_CHECKING:
    from collections.abc import Iterator

TREE_IDNAME = "ProsceniumCookTree"
ZONE_END_PROPERTY = "zone_end"
PRINT_TREE_LAYER_PROPERTY = "print_tree_layer"
VIEWER_PROPERTY = "viewer"
STAGE_OUTPUT_TYPE = "StageOutput"
SCENE_PROPERTY = "scene"
BINDING_ID_PROPERTY = "binding_id"

# Socket colors by socket kind, and for the value sockets Blender draws itself.
_KIND_COLORS = {
    "Layer": (0.33, 0.62, 0.93, 1.0),
    "EditableLayer": (0.93, 0.55, 0.22, 1.0),
    "File": (0.75, 0.75, 0.75, 1.0),
    "Prim": (0.42, 0.8, 0.5, 1.0),
    "Prims": (0.2, 0.6, 0.35, 1.0),
}
_UNSUPPORTED_COLOR = (1.0, 0.0, 0.0, 1.0)

# Blender's own socket for a value input or output of each USD value type the editor can hold.
_VALUE_SOCKETS = {
    "bool": "NodeSocketBool",
    "int": "NodeSocketInt",
    "float": "NodeSocketFloat",
    "double": "NodeSocketFloat",
    "string": "NodeSocketString",
    "token": "NodeSocketString",
    "float3": "NodeSocketVector",
    "double3": "NodeSocketVector",
    "vector3f": "NodeSocketVector",
    "vector3d": "NodeSocketVector",
    "point3f": "NodeSocketVector",
    "point3d": "NodeSocketVector",
}
_VECTOR_TYPES = frozenset(name for name, socket in _VALUE_SOCKETS.items() if socket == "NodeSocketVector")


@dataclass(frozen=True, slots=True)
class CookAttribute:
    """One attribute of a node definition: an input, an output, or a property."""

    attribute_name: str  # as the tree authors it, such as inputs:editableLayer
    namespace: str  # inputs, outputs, or props
    base_name: str  # without its namespace: the socket's identifier, or the property's after prop_
    value_type: Sdf.ValueTypeName
    default: Any  # None for an opaque attribute or an output
    socket_kind: str | None  # Layer, EditableLayer, File, Prim, Prims, or None for a value
    allowed_tokens: tuple[str, ...]
    is_multi_input: bool
    doc: str

    @property
    def type_name(self) -> str:
        """The attribute's USD value type, such as opaque or float3."""
        return str(self.value_type)

    @property
    def label(self) -> str:
        """The name the editor shows, such as Default Prim for defaultPrim."""
        return _label(self.base_name)

    @property
    def property_name(self) -> str:
        """The node property that holds a props: attribute's value."""
        return f"prop_{self.base_name}"


@dataclass(frozen=True, slots=True)
class CookNodeDefinition:
    """One node type's definition, as the definitions file holds it."""

    type_name: str  # the definition's prim name, which is the type name of the node's prim in a tree
    node_version: int
    doc: str
    zone_role: str | None  # "begin", "end", or None outside a zone
    zone_partner: str | None  # the other half's type name
    attributes: tuple[CookAttribute, ...]


class CookNode:
    """What every node type of the cook's tree shares; each type adds its definition."""

    cook_definition: ClassVar[CookNodeDefinition]

    @classmethod
    def poll(cls, ntree: bpy.types.NodeTree) -> bool:
        """Only the cook's tree holds the cook's nodes."""
        return ntree.bl_idname == TREE_IDNAME

    def init(self, context: Any) -> None:
        """Add a socket per input and output, in the definition's order; the tree's only Viewer becomes its Viewer.

        A Stage Output's scene is the context's.
        """
        node: Any = self
        for attribute in self.cook_definition.attributes:
            if attribute.namespace == "inputs":
                socket = node.inputs.new(
                    socket_idname(attribute),
                    attribute.label,
                    identifier=attribute.base_name,
                    use_multi_input=attribute.is_multi_input,
                )
                _set_socket_default(socket, attribute)
            elif attribute.namespace == "outputs":
                node.outputs.new(socket_idname(attribute), attribute.label, identifier=attribute.base_name)
        if self.cook_definition.type_name == "Viewer" and viewer_names(node.id_data) == [node.name]:
            setattr(node.id_data, VIEWER_PROPERTY, node.name)  # a tree with one Viewer cooks it without a choice
        if self.cook_definition.type_name == STAGE_OUTPUT_TYPE:
            # A script's nodes.new passes no context.
            setattr(node, SCENE_PROPERTY, (context if context is not None else bpy.context).scene)

    def copy(self, node: Any) -> None:
        """A copied Stage Output names no binding, so it makes its own on its next cook."""
        del node  # the original
        if self.cook_definition.type_name == STAGE_OUTPUT_TYPE:
            setattr(self, BINDING_ID_PROPERTY, "")

    def draw_buttons(self, context: Any, layout: Any) -> None:
        """Draw the node's properties, a begin's end, and a Stage Output's scene, or why it has no binding."""
        del context
        node: Any = self
        if self.cook_definition.zone_role == "begin":
            layout.prop_search(node, ZONE_END_PROPERTY, node.id_data, "nodes", text="End")
        if self.cook_definition.type_name == STAGE_OUTPUT_TYPE:
            layout.prop(node, SCENE_PROPERTY)
            if getattr(node, SCENE_PROPERTY) is None:
                layout.label(text="No scene, so no binding", icon="ERROR")
        for attribute in self.cook_definition.attributes:
            if attribute.namespace != "props":
                continue
            if hasattr(node, attribute.property_name):
                layout.prop(node, attribute.property_name)
            else:
                layout.label(text=f"{attribute.label}: {attribute.type_name} isn't editable here", icon="ERROR")


def viewer_names(tree: Any) -> list[str]:
    """The names of the tree's Viewer nodes, which the tree's Viewer dropdown offers."""
    return [
        node.name for node in tree.nodes if isinstance(node, CookNode) and node.cook_definition.type_name == "Viewer"
    ]


def _search_viewers(tree: Any, context: Any, edit_text: str) -> list[str]:
    del context, edit_text  # Blender filters the names by what's typed
    return sorted(viewer_names(tree))


class PROSCENIUM_NT_cook_tree(bpy.types.NodeTree):  # noqa: N801 - Blender's class naming
    """A node tree the cook evaluates into USD stages."""

    bl_idname = TREE_IDNAME
    bl_label = "Proscenium"  # the editor's name in the editor type menu
    bl_icon = "NODETREE"

    # The Cook panel's checkbox, kept on the tree so each tree keeps its own.
    print_tree_layer: bpy.props.BoolProperty(  # ty: ignore[invalid-type-form]
        name="Print Tree Layer", description="Also print the tree's layer, as the cook reads it", default=False
    )
    # The Viewer the cook runs, by its node's name, which a rename doesn't follow, as a begin's end doesn't.
    viewer: bpy.props.StringProperty(  # ty: ignore[invalid-type-form]
        name="Viewer", description="The Viewer node the cook runs and prints", search=_search_viewers
    )

    @override
    def update(self) -> None:
        """Mark the links the cook would reject, once Blender has validated the edited tree's links."""
        schedule_link_marking(self)


class _KindSocket:
    """A socket of one of the cook's socket kinds; File, Prim, and Prims sockets hold a string."""

    socket_kind: ClassVar[str]
    has_value: ClassVar[bool]

    def draw(self, context: Any, layout: Any, node: Any, text: str) -> None:
        """A value field while an unlinked input has a value, else the socket's name."""
        del context, node
        socket: Any = self
        if self.has_value and not socket.is_output and not socket.is_linked:
            layout.prop(socket, "default_value", text=text)
        else:
            layout.label(text=text)

    def draw_color(self, context: Any, node: Any) -> tuple[float, float, float, float]:
        """The kind's color."""
        del context, node
        return _KIND_COLORS[self.socket_kind]


class PROSCENIUM_S_unsupported(bpy.types.NodeSocket):  # noqa: N801 - Blender's class naming
    """A value socket of a USD type the editor can't hold; the tree authors only its links."""

    bl_idname = "ProsceniumUnsupportedSocket"
    bl_label = "Unsupported Value"

    @override
    def draw(self, context: Any, layout: Any, node: Any, text: str) -> None:
        """The socket's name, marked."""
        del context, node
        layout.label(text=f"{text} (not editable)", icon="ERROR")

    @override
    def draw_color(self, context: Any, node: Any) -> tuple[float, float, float, float]:
        """Red."""
        del context, node
        return _UNSUPPORTED_COLOR


def _string_property(*, file_path: bool, **options: Any) -> Any:
    """A string property; a file path's takes `//`, which the cook reads against the .blend's directory."""
    if not file_path:
        return bpy.props.StringProperty(**options)
    return bpy.props.StringProperty(subtype="FILE_PATH", options={"PATH_SUPPORTS_BLEND_RELATIVE"}, **options)


def _kind_socket(kind: str, *, has_value: bool, file_path: bool = False) -> Any:
    annotations: dict[str, Any] = {}
    if has_value:
        annotations["default_value"] = _string_property(file_path=file_path)
    return type(
        f"PROSCENIUM_S_{kind}",
        (_KindSocket, bpy.types.NodeSocket),
        {
            "bl_idname": f"Proscenium{kind}Socket",
            "bl_label": _label(kind),
            "socket_kind": kind,
            "has_value": has_value,
            "__annotations__": annotations,
            "__doc__": f"A {_label(kind)} socket of the cook's tree.",
        },
    )


def _label(name: str) -> str:
    """CamelCase or camelCase as words: NewLayerZoneBegin is New Layer Zone Begin."""
    words = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", name)
    return words[:1].upper() + words[1:]


_KIND_SOCKETS = (
    _kind_socket("Layer", has_value=False),
    _kind_socket("EditableLayer", has_value=False),
    _kind_socket("File", has_value=True, file_path=True),
    _kind_socket("Prim", has_value=True),
    _kind_socket("Prims", has_value=True),
)

# Built by register(), kept so their enum items stay referenced from Python, as Blender requires.
_node_types: list[Any] = []
# Session UIDs of the trees whose links the timer marks, so the timer holds no datablock.
_trees_to_mark: set[int] = set()
_enum_items: list[list[tuple[str, str, str]]] = []


def socket_idname(attribute: CookAttribute) -> str:
    """The Blender socket type that holds one input or output."""
    if attribute.socket_kind is not None:
        return f"Proscenium{attribute.socket_kind}Socket"
    return _VALUE_SOCKETS.get(attribute.type_name, PROSCENIUM_S_unsupported.bl_idname)


def is_editable_value(attribute: CookAttribute) -> bool:
    """Whether the editor holds a value for the attribute, which the tree layer authors when it isn't the default."""
    if attribute.namespace == "outputs" or attribute.type_name == "opaque":
        return False
    if attribute.namespace == "props":
        return attribute.type_name in _VALUE_SOCKETS
    return attribute.socket_kind is not None or attribute.type_name in _VALUE_SOCKETS


def is_vector(attribute: CookAttribute) -> bool:
    """Whether the attribute's value is a three-component vector."""
    return attribute.type_name in _VECTOR_TYPES


def incompatible_links(tree: Any) -> list[tuple[Any, str]]:
    """Each link between the cook's nodes that the cook would reject, with why."""
    rejected = []
    for link in tree.links:
        to_node = link.to_node
        if not isinstance(to_node, CookNode):
            continue
        for from_node, output in link_origins(link):
            if not isinstance(from_node, CookNode):
                continue  # not a node of the cook's, which the cook reports as an unresolved connection
            try:
                problem = proscenium_cook.link_problem(
                    from_node.cook_definition.type_name,
                    f"outputs:{output.identifier}",
                    to_node.cook_definition.type_name,
                    f"inputs:{link.to_socket.identifier}",
                )
            except ValueError:
                continue  # a socket its definition no longer has, which the cook reports
            if problem is not None:
                rejected.append((link, problem))
                break
    return rejected


def mark_incompatible_links(tree: Any) -> int:
    """Mark the links the cook would reject as invalid, so Blender draws them red; returns how many it marked.

    Marking sets no other link valid: Blender's own pass has, and may have marked a link invalid for its own reasons.
    """
    rejected = incompatible_links(tree)
    for link, _problem in rejected:
        link.is_valid = False
    return len(rejected)


def schedule_link_marking(tree: Any) -> None:
    """Mark tree's incompatible links on a timer, after Blender's update of the tree, which marks every link valid.

    Background Blender runs no timers, so there a caller marks a tree's links itself.
    """
    if bpy.app.background:
        return
    if not bpy.app.timers.is_registered(_mark_scheduled_trees):
        bpy.app.timers.register(_mark_scheduled_trees, first_interval=0.0)
    _trees_to_mark.add(tree.session_uid)


def schedule_all_link_marking() -> None:
    """Mark every cook tree's incompatible links, as after loading a file or an undo step."""
    for tree in bpy.data.node_groups:
        if tree.bl_idname == TREE_IDNAME:
            schedule_link_marking(tree)


def link_origins(link: Any) -> Iterator[tuple[Any, Any]]:
    """(node, output socket) where a link starts, past any reroutes; a muted link before a reroute brings nothing."""
    yield from _through_reroutes(link.from_node, link.from_socket, set())


def node_types() -> tuple[Any, ...]:
    """The registered node types, one per definition."""
    return tuple(_node_types)


def read_definitions(path: str) -> tuple[CookNodeDefinition, ...]:
    """Every node definition in a definitions file, read through Sdf."""
    layer = Sdf.Layer.FindOrOpen(path)
    if layer is None:
        raise RuntimeError(f"Can't read the cook's node definitions at {path}")
    definitions = []
    for prim in layer.rootPrims:
        version = prim.attributes.get("node:version")
        attributes = tuple(
            _read_attribute(attribute)
            for attribute in prim.attributes
            if attribute.name.split(":", 1)[0] in ("inputs", "outputs", "props")
        )
        custom = dict(prim.customData)
        definitions.append(
            CookNodeDefinition(
                type_name=prim.name,
                node_version=int(version.default) if version is not None else 1,
                doc=prim.documentation,
                zone_role=custom.get("zone"),
                zone_partner=custom.get("zonePartner"),
                attributes=attributes,
            )
        )
    return tuple(definitions)


def register() -> None:
    """Register the tree type, its sockets, a node type per definition, and the add menu's entries."""
    bpy.utils.register_class(PROSCENIUM_NT_cook_tree)
    for socket_type in (*_KIND_SOCKETS, PROSCENIUM_S_unsupported):
        bpy.utils.register_class(socket_type)
    for definition in read_definitions(str(proscenium_cook.NODE_DEFINITIONS_PATH)):
        node_type = _node_type(definition)
        bpy.utils.register_class(node_type)
        _node_types.append(node_type)
    # The stubs give a draw function the context alone; Blender calls it with the menu and the context.
    bpy.types.NODE_MT_add.append(_draw_add_menu)  # ty: ignore[invalid-argument-type]


def unregister() -> None:
    """Remove what register() added."""
    bpy.types.NODE_MT_add.remove(_draw_add_menu)  # ty: ignore[invalid-argument-type]
    if bpy.app.timers.is_registered(_mark_scheduled_trees):
        bpy.app.timers.unregister(_mark_scheduled_trees)
    _trees_to_mark.clear()
    for node_type in reversed(_node_types):
        bpy.utils.unregister_class(node_type)
    _node_types.clear()
    _enum_items.clear()
    for socket_type in reversed((*_KIND_SOCKETS, PROSCENIUM_S_unsupported)):
        bpy.utils.unregister_class(socket_type)
    bpy.utils.unregister_class(PROSCENIUM_NT_cook_tree)


def _read_attribute(attribute: Sdf.AttributeSpec) -> CookAttribute:
    namespace, base_name = attribute.name.split(":", 1)
    custom = dict(attribute.customData)
    return CookAttribute(
        attribute_name=attribute.name,
        namespace=namespace,
        base_name=base_name,
        value_type=attribute.typeName,
        default=attribute.default,
        socket_kind=custom.get("socket"),
        allowed_tokens=tuple(attribute.allowedTokens) if attribute.HasInfo("allowedTokens") else (),
        is_multi_input=bool(custom.get("multiInput", False)),
        doc=attribute.documentation,
    )


def _node_type(definition: CookNodeDefinition) -> Any:
    annotations: dict[str, Any] = {}
    if definition.zone_role == "begin":
        annotations[ZONE_END_PROPERTY] = bpy.props.StringProperty(
            name="Zone End", description=f"The {_label(definition.zone_partner or '')} node that ends this zone"
        )
    if definition.type_name == STAGE_OUTPUT_TYPE:
        annotations |= _binding_properties()
    for attribute in definition.attributes:
        if attribute.namespace == "props":
            node_property = _node_property(attribute)
            if node_property is not None:
                annotations[attribute.property_name] = node_property
    return type(
        f"PROSCENIUM_N_{definition.type_name}",
        (CookNode, bpy.types.Node),
        {
            "bl_idname": f"ProsceniumCook{definition.type_name}",
            "bl_label": _label(definition.type_name),
            "bl_description": definition.doc,
            "cook_definition": definition,
            "__annotations__": annotations,
            "__doc__": definition.doc,
        },
    )


def _binding_properties() -> dict[str, Any]:
    """A Stage Output's front-end state, which the tree layer doesn't write: its binding's scene and identifier."""
    return {
        SCENE_PROPERTY: bpy.props.PointerProperty(
            type=bpy.types.Scene, name="Scene", description="The scene the Stage Output's binding displays in"
        ),
        BINDING_ID_PROPERTY: bpy.props.StringProperty(
            name="Binding", description="The identifier of the Stage Output's binding", options={"HIDDEN"}
        ),
    }


def _node_property(attribute: CookAttribute) -> Any:
    """The bpy property that holds a props: attribute's value, or None for a type the editor can't hold."""
    common: dict[str, Any] = {"name": attribute.label, "description": attribute.doc}
    type_name = attribute.type_name
    default = attribute.default
    if type_name == "token" and attribute.allowed_tokens:
        items = [(token, token, "") for token in attribute.allowed_tokens]
        _enum_items.append(items)  # Blender needs an enum's items kept referenced
        return bpy.props.EnumProperty(items=items, default=str(default), **common)
    if type_name in ("string", "token"):
        # A string property with no socket kind is a Path property (docs/phase3/node-tree.md "The tree as plain data").
        is_path = type_name == "string" and attribute.socket_kind is None
        return _string_property(file_path=is_path, default=str(default or ""), **common)
    if type_name == "bool":
        return bpy.props.BoolProperty(default=bool(default), **common)
    if type_name == "int":
        return bpy.props.IntProperty(default=int(default or 0), **common)
    if type_name in ("float", "double"):
        return bpy.props.FloatProperty(default=float(default or 0.0), **common)
    if type_name in _VECTOR_TYPES:
        vector = tuple(default) if default is not None else (0.0, 0.0, 0.0)
        return bpy.props.FloatVectorProperty(default=vector, size=3, **common)
    return None


def _through_reroutes(node: Any, socket: Any, visited: set[str]) -> Iterator[tuple[Any, Any]]:
    if node.bl_idname != "NodeReroute":
        yield node, socket
        return
    if node.name in visited:  # a cycle of reroutes brings nothing
        return
    visited.add(node.name)
    for link in node.inputs[0].links:
        if not link.is_muted:
            yield from _through_reroutes(link.from_node, link.from_socket, visited)


def _mark_scheduled_trees() -> None:
    uids = set(_trees_to_mark)
    _trees_to_mark.clear()
    marked = sum(
        mark_incompatible_links(tree)
        for tree in bpy.data.node_groups
        if tree.bl_idname == TREE_IDNAME and tree.session_uid in uids
    )
    window_manager = bpy.context.window_manager
    if marked and window_manager is not None:
        for window in window_manager.windows:
            for area in window.screen.areas:
                if area.type == "NODE_EDITOR":
                    area.tag_redraw()


def _set_socket_default(socket: Any, attribute: CookAttribute) -> None:
    if attribute.default is None or not hasattr(socket, "default_value"):
        return
    socket.default_value = tuple(attribute.default) if is_vector(attribute) else attribute.default


def _draw_add_menu(menu: Any, context: Any) -> None:
    space = context.space_data
    if space is None or getattr(space, "tree_type", None) != TREE_IDNAME:
        return
    layout = menu.layout
    layout.separator()
    for node_type in _node_types:
        operator: Any = layout.operator("node.add_node", text=node_type.bl_label)
        operator.type = node_type.bl_idname
        operator.use_transform = True
