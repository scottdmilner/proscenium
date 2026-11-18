"""The Source Select tool: the extension's own selection of USD source targets in the 3D viewport (M7 plan, F2).

Ported from the bridge's select_tool.py, over proscenium_sync's API only (DECISIONS.md "Headless interaction
functions"):

- **Click** picks what a ray under the cursor hits; shift toggles its target, ctrl removes it, and a click on nothing
  clears the selection. M7's display draws each copy as its bounds, a mesh of corners without faces, or an empty
  marker, which Blender's ray cast can't hit, so the tool casts its own ray against what the display draws: each
  visible, selectable object's bounds box, and an empty within a few pixels of its origin. The nearest hit gives what a
  ray cast would, the object and its world matrix (interaction-contract.md#picking).
- **Drag** selects a box: the viewport elements whose world bounds' centers project inside it (ICON-40).
- **The level**, in the sidebar's Proscenium tab, is the prim level or a registered model kind; the tab lists the
  scene's source selection.
- **Only Source Select selects managed content** (ICON-41): a scene's managed content is selectable exactly while a
  window showing it has Source Select active. Message-bus subscriptions to every workspace's tools and every window's
  workspace say when that changes, and after a file loads, an undo, or a redo it is recomputed from the active tool,
  whatever the file or the undo step stored: activating the tool is no undo step, so undoing past a pick made since
  restores selectability as it was before the activation. In background mode, where no tool is used, selectability is
  left as it is.

The operators declare UNDO, as Blender's selection operators do; the API's selection functions push no undo step.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, override

import bpy
from bpy_extras import view3d_utils
from mathutils import Vector
from pxr import Kind

import proscenium_sync

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from bpy.stub_internal.rna_enums import OperatorReturnItems  # stub-only alias
    from mathutils import Matrix

PRIM_LEVEL = "PRIM"
LEVEL_PROPERTY = "proscenium_selection_level"  # on each scene
MARKER_PICK_PIXELS = 6.0  # how near its origin a click picks an empty marker
_MODES = (("SET", "Set", ""), ("TOGGLE", "Toggle", ""), ("EXTEND", "Extend", ""), ("SUBTRACT", "Subtract", ""))
_TOOL_SUBSCRIBER = object()  # owns the message-bus subscriptions to tool changes


def levels() -> list[tuple[str, str, str]]:
    """The selection levels, as enum items: the prim level, and each registered model kind."""
    kinds = sorted(str(k) for k in Kind.Registry.GetAllKinds() if k)
    return [(PRIM_LEVEL, "Prim", "Each pick's floor"), *((k, k.title(), f"The nearest {k}") for k in kinds)]


def selection_level(scene: bpy.types.Scene) -> str | None:
    """The scene's selection level: None for the prim level, or a model kind's name."""
    level = getattr(scene, LEVEL_PROPERTY, PRIM_LEVEL)
    return None if level == PRIM_LEVEL else level


def _box_hit(obj: bpy.types.Object, origin: Vector, direction: Vector) -> float | None:
    """The ray parameter at which origin + t * direction enters obj's bounds box, or None for a miss or behind it."""
    to_local = obj.matrix_world.inverted_safe()
    local_origin, local_direction = to_local @ origin, to_local.to_3x3() @ direction
    corners = [Vector(corner) for corner in obj.bound_box]
    near, far = 0.0, float("inf")
    for axis in range(3):
        low, high = min(c[axis] for c in corners), max(c[axis] for c in corners)
        if abs(local_direction[axis]) < 1e-12:
            if not low <= local_origin[axis] <= high:
                return None
            continue
        t0, t1 = sorted(
            ((low - local_origin[axis]) / local_direction[axis], (high - local_origin[axis]) / local_direction[axis])
        )
        near, far = max(near, t0), min(far, t1)
        if near > far:
            return None
    return near


def bounds_ray_cast(
    objects: Iterable[bpy.types.Object],
    origin: Vector,
    direction: Vector,
    near_marker: Callable[[bpy.types.Object], bool],
) -> tuple[bpy.types.Object, Matrix] | None:
    """The nearest object the ray hits as the display draws it, and its world matrix, as a ray cast gives them.

    A mesh is hit within its bounds box; an empty, a marker, where near_marker says the ray passes near its origin.
    """
    nearest: tuple[float, bpy.types.Object] | None = None
    for obj in objects:
        if obj.type == "EMPTY":
            if not near_marker(obj):
                continue
            hit = (obj.matrix_world.translation - origin).dot(direction) / direction.length_squared
            hit = hit if hit >= 0 else None
        else:
            hit = _box_hit(obj, origin, direction)
        if hit is not None and (nearest is None or hit < nearest[0]):
            nearest = (hit, obj)
    return None if nearest is None else (nearest[1], nearest[1].matrix_world.copy())


def pickable(view_layer: bpy.types.ViewLayer) -> list[bpy.types.Object]:
    """The objects a click may hit: those the view layer shows that can be selected."""
    return [obj for obj in view_layer.objects if obj.visible_get(view_layer=view_layer) and not obj.hide_select]


def pick(scene: bpy.types.Scene, hit: tuple[bpy.types.Object, Matrix] | None, mode: str) -> None:
    """Change the scene's source selection by the target, at its level, of what a click hit; None for nothing."""
    obj, matrix = hit if hit is not None else (None, None)
    proscenium_sync.BINDINGS.select_by_pick(
        scene, obj, matrix, selection_level(scene), proscenium_sync.SelectionMode[mode]
    )


def box(
    scene: bpy.types.Scene,
    project: Callable[[Vector], Vector | None],
    corners: tuple[tuple[float, float], tuple[float, float]],
    mode: str,
) -> None:
    """Change the scene's source selection by the elements whose world bounds' centers project inside a region box."""
    (x0, y0), (x1, y1) = corners

    def inside(point: Vector) -> bool:
        at = project(point)
        return at is not None and min(x0, x1) <= at.x <= max(x0, x1) and min(y0, y1) <= at.y <= max(y0, y1)

    proscenium_sync.BINDINGS.select_by_box(scene, inside, selection_level(scene), proscenium_sync.SelectionMode[mode])


def _tool_active(window: bpy.types.Window) -> bool:
    """Whether Source Select is the window's active object-mode tool in the 3D view."""
    tool = window.workspace.tools.from_space_view3d_mode("OBJECT", create=False)
    return tool is not None and tool.idname == PROSCENIUM_TT_source_select.bl_idname


def apply_selectability(selectable_scenes: set[bpy.types.Scene]) -> None:
    """Make each scene with bindings selectable exactly when it is one of selectable_scenes, mirroring once it is."""
    for scene in bpy.data.scenes:
        selectable = scene in selectable_scenes
        if (
            proscenium_sync.BINDINGS.in_scene(scene)
            and proscenium_sync.BINDINGS.managed_selectable(scene) != selectable
        ):
            proscenium_sync.BINDINGS.set_managed_selectable(scene, selectable)


def update_selectability(*_args: object) -> None:
    """Make each scene's managed content selectable exactly while a window showing it has Source Select active.

    Nothing in background mode, where no tool is used, though the file may hold windows.
    """
    window_manager = bpy.context.window_manager
    if bpy.app.background or window_manager is None:
        return
    apply_selectability({w.scene for w in window_manager.windows if _tool_active(w)})


def subscribe_to_tools() -> None:
    """Call update_selectability when a workspace's tool or a window's workspace changes; a file load clears these."""
    bpy.msgbus.clear_by_owner(_TOOL_SUBSCRIBER)
    for key in ((bpy.types.WorkSpace, "tools"), (bpy.types.Window, "workspace")):
        bpy.msgbus.subscribe_rna(
            key=key,  # ty: ignore[invalid-argument-type]  # Blender's documented (type, property) key
            owner=_TOOL_SUBSCRIBER,
            args=(),
            notify=update_selectability,
        )


def unsubscribe_from_tools() -> None:
    """Stop following tool changes."""
    bpy.msgbus.clear_by_owner(_TOOL_SUBSCRIBER)


class PROSCENIUM_OT_source_pick(bpy.types.Operator):  # noqa: N801 - Blender's operator naming
    """Select the source target under the cursor."""

    bl_idname = "proscenium.source_pick"
    bl_label = "Source Pick"
    bl_options = {"REGISTER", "UNDO"}  # noqa: RUF012 - Blender's operator field
    mode: bpy.props.EnumProperty(items=_MODES, default="SET")  # ty: ignore[invalid-type-form]

    @override
    def invoke(self, context: Any, event: Any) -> set[OperatorReturnItems]:
        region, view = context.region, context.region_data
        cursor = Vector((event.mouse_region_x, event.mouse_region_y))
        origin = view3d_utils.region_2d_to_origin_3d(region, view, (cursor.x, cursor.y))
        direction = view3d_utils.region_2d_to_vector_3d(region, view, (cursor.x, cursor.y))

        def near_marker(obj: bpy.types.Object) -> bool:
            at = view3d_utils.location_3d_to_region_2d(region, view, obj.matrix_world.translation)
            return at is not None and (at - cursor).length <= MARKER_PICK_PIXELS

        hit = bounds_ray_cast(pickable(context.view_layer), origin, direction, near_marker)
        pick(context.scene, hit, self.mode)
        return {"FINISHED"}


class PROSCENIUM_OT_source_box(bpy.types.Operator):  # noqa: N801 - Blender's operator naming
    """Select the source targets of the elements inside a dragged box."""

    bl_idname = "proscenium.source_box"
    bl_label = "Source Box"
    bl_options = {"REGISTER", "UNDO"}  # noqa: RUF012 - Blender's operator field
    mode: bpy.props.EnumProperty(items=_MODES, default="SET")  # ty: ignore[invalid-type-form]
    _start: tuple[float, float]
    _end: tuple[float, float]
    _handle: Any

    @override
    def invoke(self, context: Any, event: Any) -> set[OperatorReturnItems]:
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
        if event.type in {"RIGHTMOUSE", "ESC"}:
            bpy.types.SpaceView3D.draw_handler_remove(self._handle, "WINDOW")
            return {"CANCELLED"}
        if event.type == "LEFTMOUSE" and event.value == "RELEASE":
            bpy.types.SpaceView3D.draw_handler_remove(self._handle, "WINDOW")
            region, view = context.region, context.region_data
            box(
                context.scene,
                lambda p: view3d_utils.location_3d_to_region_2d(region, view, p),
                (self._start, self._end),
                self.mode,
            )
            return {"FINISHED"}
        return {"RUNNING_MODAL"}

    def _draw(self) -> None:
        import gpu
        from gpu_extras.batch import batch_for_shader

        (x0, y0), (x1, y1) = self._start, self._end
        shader = gpu.shader.from_builtin("UNIFORM_COLOR")
        lines = batch_for_shader(shader, "LINE_STRIP", {"pos": [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]})
        shader.uniform_float("color", (1.0, 1.0, 1.0, 0.8))
        lines.draw(shader)


class PROSCENIUM_PT_source_selection(bpy.types.Panel):  # noqa: N801 - Blender's panel naming
    """The source selection's level, and the scene's targets."""

    bl_label = "Source Selection"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Proscenium"

    @override
    def draw(self, context: Any) -> None:
        draw_source_selection(self.layout, context.scene)


def draw_source_selection(layout: Any, scene: bpy.types.Scene) -> None:
    """The level and each of the scene's targets, the active one marked and the unresolved ones dimmed."""
    layout.prop(scene, LEVEL_PROPERTY, text="Level")
    selection = proscenium_sync.BINDINGS.source_selection(scene)
    if not selection.entries:
        layout.label(text="Nothing selected")
        return
    unresolved = set(proscenium_sync.BINDINGS.resolve_source_selection(scene).unresolved)
    for entry in selection.entries:
        row = layout.row()
        row.enabled = entry not in unresolved
        row.label(text=entry.path, icon="RADIOBUT_ON" if entry == selection.active else "DOT")


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
