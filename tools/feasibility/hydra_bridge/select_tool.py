"""A source selection tool in the 3D viewport, to try the extension's own selection in a window (M4 Phase F, Q4).

The contract leaves open whether Blender selection reaches the source through Blender's own tools or a tool the
extension provides ([Blender Selection](../../../docs/spec/interaction-contract.md#blender-selection)). This
tool is the second, over Phase D's batched display (batched_display.py), so one instance in a batch can be picked:

- **Click** picks what a ray cast under the cursor hits (batch_selection.pick_element), shift-click toggles its
  target, ctrl-click removes it, and a click on nothing clears the selection.
- **Drag** selects a box: each viewport element whose bounds' center, in world space, projects inside it, with
  the same modifiers. A mesh's origin won't do, as many scenes hold placement in their points.
- **The level** (the sidebar's Proscenium tab) is the prim level or a registered model kind, as select_targets
  takes it; the latest target picked is the active entry.
- **Following Blender's own tools** (the sidebar's toggle): after any depsgraph update, Blender's selected and
  active managed objects become a source selection (selection_from_blender), mirrored back at once. A batch's
  carrier then stands for every instance in its state.
- **Only Source Select selects:** while another tool is active, and Blender's own tools aren't followed, managed
  objects are unselectable, by their collection's `hide_select` (a flag per object took about 0.9 s to switch on
  ALab, against about 40 ms), so Blender's tools can't select them. Blender deselects an object it makes
  unselectable, so the source selection is kept and mirrored back once Source Select is active again.
  Message-bus subscriptions to the workspaces' tools and the windows' workspaces say when the active tool
  changes. It lives here for the prototype only: later tools may need managed content selectable too, so the
  product may decide it elsewhere.

`Session` holds the selection and does everything but read the window, so it runs headless; select_tool_demo.py
installs the tool over a scene in a windowed Blender.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, override

import batched_display_selection
import bpy
import gpu
import numpy
from batched_display import TRANSFORM
from bpy_extras import view3d_utils
from gpu_extras.batch import batch_for_shader
from pxr import Kind

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from batched_display import BatchedDisplay
    from bpy.stub_internal.rna_enums import OperatorReturnItems  # stub-only alias

PRIM_LEVEL = "PRIM"
MODES = (("SET", "Set", ""), ("TOGGLE", "Toggle", ""), ("EXTEND", "Extend", ""), ("SUBTRACT", "Subtract", ""))


@dataclass
class Session:
    """A source selection over one batched display, and its mirror in Blender's selection."""

    interaction: Any  # the bridge's SourceSelectionResolver over the display's plan
    display: BatchedDisplay
    view_layer: bpy.types.ViewLayer
    collection: bpy.types.Collection  # the display's, which holds every managed object
    model_kind: str | None = None  # a model kind, or None for the prim level
    selected_source_paths: list[str] = field(default_factory=list)  # in the order picked
    active_source_path: str | None = None
    follow_blender_selection: bool = False  # whether Blender's own selection changes become source selections
    selectable: bool = True  # whether managed objects are selectable, and mirror the source selection
    retained_source_objects: tuple[Any, ...] = ()  # what the interaction needs alive: the stage, its bridge, the plan
    stage: Any = None  # the live stage, which callers read values from, as the contract says
    time_code: float | None = None  # the time code the display shows; None for the default
    listeners: list[Callable[[], None]] = field(default_factory=list)  # told when the source selection changes
    _applying: bool = False
    _world_centers_by_element: dict[int, numpy.ndarray] | None = None  # the display's, which stays as it is built

    def pick(self, obj: bpy.types.Object | None, matrix: Any, mode: str) -> None:
        """Select the target of what a ray cast hit, its object and world matrix; None for nothing hit."""
        element = None if obj is None else batched_display_selection.pick_element(self.display, obj, matrix)
        self.select([] if element is None else [element], mode)

    def box(self, elements: Iterable[int], mode: str) -> None:
        self.select(list(elements), mode)

    def select(self, elements: list[int], mode: str) -> None:
        """Change the selection by the targets of `elements`, as `mode` says, and mirror it into Blender."""
        entities = []
        for element in elements:
            resolved = self.interaction.resolve_pick(element)
            if resolved is not None:
                entities.append((resolved["source"], tuple(resolved["instance_context"])))
        picked = list(dict.fromkeys(self.interaction.select_targets(entities, self.model_kind))) if entities else []
        if mode == "SET":
            self.selected_source_paths = picked
        elif mode == "EXTEND":
            self.selected_source_paths += [t for t in picked if t not in self.selected_source_paths]
        elif mode == "SUBTRACT":
            self.selected_source_paths = [t for t in self.selected_source_paths if t not in picked]
        else:  # TOGGLE
            kept = [t for t in self.selected_source_paths if t not in picked]
            self.selected_source_paths = kept + [t for t in picked if t not in self.selected_source_paths]
        if picked and mode != "SUBTRACT" and picked[-1] in self.selected_source_paths:
            self.active_source_path = picked[-1]
        elif self.active_source_path not in self.selected_source_paths:
            self.active_source_path = None
        self.apply()

    def apply(self) -> None:
        """Tell the listeners, and mirror the source selection into Blender's, while managed objects are selectable."""
        for listener in self.listeners:
            listener()
        if not self.selectable:
            return
        shown = (
            set(self.interaction.highlight_targets(self.selected_source_paths)) if self.selected_source_paths else set()
        )
        active = (
            set(self.interaction.highlight_targets([self.active_source_path])) if self.active_source_path else set()
        )
        self._applying = True
        try:
            batched_display_selection.apply_selection(self.view_layer, self.display, shown, active)
        finally:
            self._applying = False

    def set_selectable(self, selectable: bool) -> None:
        """Make managed objects selectable, mirroring the source selection, or not, which deselects them."""
        if selectable == self.selectable:
            return
        self.selectable = selectable
        self.collection.hide_select = not selectable
        self.apply()

    def follow_blender(self) -> None:
        """Take Blender's selection of managed objects as the source selection, if it changed, and mirror it."""
        if self._applying:
            return
        blender = batched_display_selection.read_blender_selection(self.view_layer, self.display)
        found = self.interaction.selection_from_blender(
            blender.selected_element_indices, blender.active_element_index, self.model_kind
        )
        if (list(found["targets"]), found["active"]) != (self.selected_source_paths, self.active_source_path):
            self.selected_source_paths, self.active_source_path = list(found["targets"]), found["active"]
            self.apply()

    def centers(self) -> dict[int, numpy.ndarray]:
        """Each viewport element's bounds' center in world space, which a box selects by.

        Computed once: Phase D's display holds still until it is built again, with a session of its own.
        """
        if self._world_centers_by_element is not None:
            return self._world_centers_by_element
        found = {}
        for element, obj in self.display.objects.items():
            if not obj.hide_viewport:
                found[element] = numpy.array(obj.matrix_world) @ _center(obj)
        for batch in self.display.batches:
            transforms = numpy.empty((len(batch.elements), 4, 4), dtype=numpy.float32)
            held: Any = batch.points.attributes[TRANSFORM]  # a FLOAT4X4 attribute
            held.data.foreach_get("value", transforms.ravel())
            shown = [c for c in batch.carriers.values() if not c.hide_viewport]
            if not shown:
                continue
            # A point's transform is USD's row-vector matrix, under its carriers' shared parent.
            world = numpy.array(shown[0].matrix_world) @ transforms.transpose(0, 2, 1)
            centers = world @ _center(batch.prototype)
            for point, element in enumerate(batch.elements):
                found[element] = centers[point]
        self._world_centers_by_element = found
        return found


SESSION: Session | None = None  # the one session a demo installs
_TOOL_OWNER = object()  # owns the message-bus subscription to tool changes
OUTLINES: Any = None  # the session's origins, and its own outlines when drawn (select_outline.Outlines)


def _center(obj: bpy.types.Object) -> numpy.ndarray:
    """An object's local bounds' center, as homogeneous coordinates."""
    corners = numpy.array([tuple(corner) for corner in obj.bound_box])
    return numpy.append(corners.mean(axis=0), 1.0)


def levels() -> list[tuple[str, str, str]]:
    """The selection levels: the prim level, and each registered model kind."""
    kinds = sorted(str(k) for k in Kind.Registry.GetAllKinds() if k)
    return [(PRIM_LEVEL, "Prim", "Each pick's floor"), *((k, k.title(), f"The nearest {k}") for k in kinds)]


def _on_level(self: Any, _context: Any) -> None:
    if SESSION is not None:
        SESSION.model_kind = None if self.proscenium_level == PRIM_LEVEL else self.proscenium_level


def _on_outlines(self: Any, _context: Any) -> None:
    """Draw the extension's own outlines of the source selection (select_outline.py) besides its origins, or not."""
    if OUTLINES is not None:
        OUTLINES.draw_outlines = self.proscenium_outlines
        OUTLINES.rebuild()
        _watch_tool()


def _on_follow(self: Any, _context: Any) -> None:
    if SESSION is not None:
        SESSION.follow_blender_selection = self.proscenium_follow
        _watch_tool()


def _tool_active() -> bool:
    """Whether Source Select is the active object-mode tool of a 3D view in any window."""
    manager: Any = bpy.context.window_manager  # never None in a windowed Blender
    for window in manager.windows if manager is not None else ():
        tool = window.workspace.tools.from_space_view3d_mode("OBJECT", create=False)
        if tool is not None and tool.idname == PROSCENIUM_TT_source_select.bl_idname:
            return True
    return False


def _watch_tool(*_args: Any) -> None:
    """Keep managed objects selectable exactly while Source Select is active, or Blender's tools are followed.

    While the extension draws its own outlines, Blender's selection outlines and origins are hidden exactly while
    Source Select is active, so Blender outlines what its own tools select.
    """
    if SESSION is not None:
        active = _tool_active()
        SESSION.set_selectable(SESSION.follow_blender_selection or active)
        if OUTLINES is not None:
            OUTLINES.hide_blender_overlays(active)


def _on_update(_scene: Any, _depsgraph: Any = None) -> None:
    if SESSION is not None and SESSION.follow_blender_selection:
        SESSION.follow_blender()


class PROSCENIUM_OT_source_pick(bpy.types.Operator):  # noqa: N801 - Blender's operator naming
    """Select the source target under the cursor."""

    bl_idname = "proscenium.source_pick"
    bl_label = "Source Pick"
    bl_options = {"REGISTER", "UNDO"}  # noqa: RUF012 - Blender's operator field
    mode: bpy.props.EnumProperty(items=MODES, default="SET")  # ty: ignore[invalid-type-form]

    @override
    def invoke(self, context: Any, event: Any) -> set[OperatorReturnItems]:
        if SESSION is None:
            return {"CANCELLED"}
        coord = (event.mouse_region_x, event.mouse_region_y)
        origin = view3d_utils.region_2d_to_origin_3d(context.region, context.region_data, coord)
        direction = view3d_utils.region_2d_to_vector_3d(context.region, context.region_data, coord)
        hit, _, _, _, obj, matrix = context.scene.ray_cast(context.evaluated_depsgraph_get(), origin, direction)
        SESSION.pick(obj.original if hit else None, matrix if hit else None, self.mode)
        return {"FINISHED"}


class PROSCENIUM_OT_source_box(bpy.types.Operator):  # noqa: N801 - Blender's operator naming
    """Select the source targets of the elements inside a dragged box."""

    bl_idname = "proscenium.source_box"
    bl_label = "Source Box"
    bl_options = {"REGISTER", "UNDO"}  # noqa: RUF012 - Blender's operator field
    mode: bpy.props.EnumProperty(items=MODES, default="SET")  # ty: ignore[invalid-type-form]
    _start: tuple[int, int]
    _end: tuple[int, int]
    _handle: Any

    @override
    def invoke(self, context: Any, event: Any) -> set[OperatorReturnItems]:
        if SESSION is None:
            return {"CANCELLED"}
        # The drag starts where the button went down, which the event gives in window coordinates.
        self._start = (event.mouse_prev_press_x - context.region.x, event.mouse_prev_press_y - context.region.y)
        self._end = (event.mouse_region_x, event.mouse_region_y)
        self._handle = bpy.types.SpaceView3D.draw_handler_add(self._draw, (), "WINDOW", "POST_PIXEL")
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    @override
    def modal(self, context: Any, event: Any) -> set[OperatorReturnItems]:
        context.area.tag_redraw()
        if event.type == "MOUSEMOVE":
            self._end = (event.mouse_region_x, event.mouse_region_y)
            return {"RUNNING_MODAL"}
        if event.type in ("RIGHTMOUSE", "ESC"):
            self._finish()
            return {"CANCELLED"}
        if event.type == "LEFTMOUSE" and event.value == "RELEASE":
            self._finish()
            (x0, y0), (x1, y1) = self._start, self._end
            inside = []
            assert SESSION is not None  # noqa: S101 - checked at invoke
            for element, center in SESSION.centers().items():
                at = view3d_utils.location_3d_to_region_2d(context.region, context.region_data, center[:3].tolist())
                if at is not None and min(x0, x1) <= at.x <= max(x0, x1) and min(y0, y1) <= at.y <= max(y0, y1):
                    inside.append(element)
            SESSION.box(inside, self.mode)
            return {"FINISHED"}
        return {"RUNNING_MODAL"}

    def _finish(self) -> None:
        bpy.types.SpaceView3D.draw_handler_remove(self._handle, "WINDOW")

    def _draw(self) -> None:
        (x0, y0), (x1, y1) = self._start, self._end
        shader = gpu.shader.from_builtin("UNIFORM_COLOR")
        lines = batch_for_shader(shader, "LINE_STRIP", {"pos": [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]})
        shader.uniform_float("color", (1.0, 1.0, 1.0, 0.8))
        lines.draw(shader)


class PROSCENIUM_PT_source_selection(bpy.types.Panel):  # noqa: N801 - Blender's panel naming
    """The source selection's level, whether Blender's own tools are followed, and its targets."""

    bl_label = "Source Selection"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Proscenium"

    @override
    def draw(self, context: Any) -> None:
        layout: Any = self.layout  # never None while drawing
        layout.prop(context.scene, "proscenium_level", text="Level")
        layout.prop(context.scene, "proscenium_follow", text="Follow Blender's Tools")
        layout.prop(context.scene, "proscenium_outlines", text="Draw Own Outlines")
        if OUTLINES is not None and OUTLINES.draw_durations_ms:
            recent = OUTLINES.draw_durations_ms[-60:]
            layout.label(text=f"Outlines: {sum(recent) / len(recent):.2f} ms a frame (CPU)")
        if SESSION is None:
            layout.label(text="No display")
            return
        for target in SESSION.selected_source_paths:
            layout.label(text=target, icon="RADIOBUT_ON" if target == SESSION.active_source_path else "DOT")


class PROSCENIUM_TT_source_select(bpy.types.WorkSpaceTool):  # noqa: N801 - Blender's tool naming
    """Click or drag to select source targets."""

    bl_space_type = "VIEW_3D"
    bl_context_mode = "OBJECT"
    bl_idname = "proscenium.source_select"
    bl_label = "Source Select"
    bl_description = "Select USD source targets: click, shift to toggle, ctrl to remove, drag for a box"
    bl_icon = "ops.generic.select_box"
    bl_keymap = (
        ("proscenium.source_pick", {"type": "LEFTMOUSE", "value": "CLICK"}, {"properties": [("mode", "SET")]}),
        (
            "proscenium.source_pick",
            {"type": "LEFTMOUSE", "value": "CLICK", "shift": True},
            {"properties": [("mode", "TOGGLE")]},
        ),
        (
            "proscenium.source_pick",
            {"type": "LEFTMOUSE", "value": "CLICK", "ctrl": True},
            {"properties": [("mode", "SUBTRACT")]},
        ),
        ("proscenium.source_box", {"type": "LEFTMOUSE", "value": "CLICK_DRAG"}, {"properties": [("mode", "SET")]}),
        (
            "proscenium.source_box",
            {"type": "LEFTMOUSE", "value": "CLICK_DRAG", "shift": True},
            {"properties": [("mode", "EXTEND")]},
        ),
        (
            "proscenium.source_box",
            {"type": "LEFTMOUSE", "value": "CLICK_DRAG", "ctrl": True},
            {"properties": [("mode", "SUBTRACT")]},
        ),
    )


CLASSES = (PROSCENIUM_OT_source_pick, PROSCENIUM_OT_source_box, PROSCENIUM_PT_source_selection)


def register(session: Session) -> None:
    """Install the tool, its panel, and the handler that follows Blender's own tools, over `session`."""
    global SESSION, OUTLINES  # noqa: PLW0603 - the demo's one session, and its origins and outlines
    import select_outline

    SESSION = session
    OUTLINES = select_outline.Outlines(session)
    OUTLINES.enable()
    scene_type: Any = bpy.types.Scene
    # A fixed list, read once: a callback's items must stay referenced from Python, or Blender may show garbage.
    scene_type.proscenium_level = bpy.props.EnumProperty(items=levels(), update=_on_level)
    scene_type.proscenium_follow = bpy.props.BoolProperty(default=False, update=_on_follow)
    scene_type.proscenium_outlines = bpy.props.BoolProperty(default=False, update=_on_outlines)
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.utils.register_tool(PROSCENIUM_TT_source_select, separator=True)
    bpy.app.handlers.depsgraph_update_post.append(_on_update)
    # Blender publishes WorkSpace.tools when a tool is set (ad hoc, Blender 5.2); a file load clears subscriptions.
    # Every workspace's tools, and every window's workspace, as a window's tool changes with its workspace too. The
    # stubs take only an instance's key.
    keys: list[Any] = [(bpy.types.WorkSpace, "tools"), (bpy.types.Window, "workspace")]
    for key in keys:
        bpy.msgbus.subscribe_rna(key=key, owner=_TOOL_OWNER, args=(), notify=_watch_tool)
    _watch_tool()


def unregister() -> None:
    global SESSION, OUTLINES  # noqa: PLW0603 - the demo's one session, and its outlines
    if OUTLINES is not None:
        OUTLINES.disable()
    SESSION = OUTLINES = None
    bpy.app.handlers.depsgraph_update_post.remove(_on_update)
    bpy.msgbus.clear_by_owner(_TOOL_OWNER)
    bpy.utils.unregister_tool(PROSCENIUM_TT_source_select)
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
