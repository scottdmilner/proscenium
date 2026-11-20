"""The source inspector: a binding's live stage in the scene graph widget, synced with the source selection.

M7 plan, Phase F item 4 (F3), hosting proscenium_ui's scene graph widget in the sidebar's Proscenium tab. The panel
shows the live stage of the binding chosen in its dropdown, and whether the prim selected in the tree is displayed.
The view never holds the stage, nor does the inspector: each draw compares the binding's live stage with the one
shown, and a timer shows another, since a draw may write no data.

With syncing on, which the panel's toggle sets per scene, the tree's selected prim and the scene's source selection
mirror each other: selecting a row sets the source selection to that prim's floor, its outermost instance root when it
is inside instance contents, since no target is; and a change of the source selection selects its active entry's row
when the entry is the inspected binding's. The widget's select_prim doesn't report back, so neither direction starts the
other. With syncing off, the tree only browses. A row that changes the source selection pushes an undo step, as the
viewport's selection operators do; the widget makes the selection from a list's update or a key watcher, neither of
which pushes one. Undo doesn't restore the tree, whose state the window manager holds, so after an undo or a redo the
tree takes up the restored source selection (interface_registration).

Below the tree, as in tools/scene_graph_demo.py, the property viewer widget shows the selected prim's properties,
synced or not, at the time code the display shows, and a summary of the selected property. A target's jump button
selects its prim in the tree as a row click would, and its property in the property viewer.
"""

from __future__ import annotations

from typing import Any, override

import bpy
from pxr import Sdf, Usd

import proscenium_sync
from proscenium_ui import widget_updates
from proscenium_ui.property_viewer_widget import display as property_display
from proscenium_ui.scene_graph_widget import display

VIEW_NAME = "proscenium_source_inspector"
PROPERTY_VIEW_NAME = "proscenium_source_properties"
CATEGORY = "Proscenium"
BINDING_PROPERTY = "proscenium_inspected_binding"  # on each scene: the inspected binding's identifier
SYNCED_PROPERTY = "proscenium_inspector_synced"  # on each scene: whether the tree and the source selection mirror
NO_BINDING = "NONE"
UNDO_MESSAGE = "Source Selection"  # the undo step a synced row's selection pushes

_binding_items: list[tuple[str, str, str]] = []  # an enum's items must stay referenced from Python while shown


class _Shown:
    """Which binding's stage the view shows, by the stage's session layer, unique to it; the stage isn't held."""

    key: tuple[str, str] | None = None


def binding_items(_self: object, context: Any) -> list[tuple[str, str, str]]:
    """The scene's bindings as the dropdown's items, by destination name; one item saying there are none."""
    statuses = proscenium_sync.BINDINGS.binding_statuses(context.scene) if context is not None else []
    _binding_items[:] = [(s.binding_id, s.name or s.binding_id, "") for s in statuses if s.refusal is None] or [
        (NO_BINDING, "No bindings", "")
    ]
    return _binding_items


def inspected_handle(scene: bpy.types.Scene) -> proscenium_sync.BindingHandle | None:
    """The handle of the binding the scene's inspector shows, or None when it shows none of the scene's."""
    binding_id = getattr(scene, BINDING_PROPERTY, NO_BINDING)
    if binding_id in {"", NO_BINDING}:
        return None
    handle = proscenium_sync.BindingHandle(binding_id)
    return handle if handle in proscenium_sync.BINDINGS.in_scene(scene) else None


def _live_stage(scene: bpy.types.Scene) -> Usd.Stage | None:
    handle = inspected_handle(scene)
    return None if handle is None else handle.live_stage()


def _key(scene: bpy.types.Scene) -> tuple[str, str] | None:
    handle, stage = inspected_handle(scene), _live_stage(scene)
    return None if handle is None or stage is None else (handle.binding_id, stage.GetSessionLayer().identifier)


def show_inspected_stage(scene: bpy.types.Scene) -> None:
    """Show the inspected binding's live stage in the view, or none, and sync the tree if syncing is on."""
    _Shown.key = _key(scene)
    property_display.set_stage(PROPERTY_VIEW_NAME, _live_stage(scene))
    display.set_stage(VIEW_NAME, _live_stage(scene))  # selects nothing, which shows no prim's properties
    if getattr(scene, SYNCED_PROPERTY, False):
        source_selection_changed(scene)


def _show_current_stage() -> None:
    scene = bpy.context.scene
    if scene is not None:
        show_inspected_stage(scene)


def tree_selection_changed(path: Sdf.Path | None) -> None:
    """The view's callback: show the prim's properties; synced, make its floor the source selection, as an undo step."""
    property_display.show_prim(PROPERTY_VIEW_NAME, path)
    scene = bpy.context.scene
    if scene is None or path is None or not getattr(scene, SYNCED_PROPERTY, False):
        return
    handle = inspected_handle(scene)
    if handle is None or handle.live_stage() is None:
        return
    [target] = handle.select_targets([str(path)], None)
    entry = proscenium_sync.SelectionEntry(handle.binding_id, target)
    selection = proscenium_sync.PersistentSelection((entry,), entry)
    if selection != proscenium_sync.BINDINGS.source_selection(scene):
        proscenium_sync.BINDINGS.set_source_selection(scene, selection)
        bpy.ops.ed.undo_push(message=UNDO_MESSAGE)


def source_selection_changed(scene: bpy.types.Scene) -> None:
    """The source selection's listener: with syncing on, select its active entry's row, if the inspected binding's."""
    if not getattr(scene, SYNCED_PROPERTY, False) or (handle := inspected_handle(scene)) is None:
        return
    active = proscenium_sync.BINDINGS.source_selection(scene).active
    display.select_prim(VIEW_NAME, Sdf.Path(active.path) if active and active.binding_id == handle.binding_id else None)
    property_display.show_prim(PROPERTY_VIEW_NAME, display.selected_path(VIEW_NAME))  # select_prim doesn't report


def jump_to_target(target_path: Sdf.Path) -> None:
    """The property viewer's callback: select a target's prim in the tree as a row click would, and its property."""
    display.select_prim(VIEW_NAME, target_path.GetPrimPath())  # not reported back, so told here
    tree_selection_changed(target_path.GetPrimPath())
    if target_path.IsPropertyPath():
        property_display.select_property(PROPERTY_VIEW_NAME, target_path.name)


def _synced_changed(_self: object, context: Any) -> None:
    if context.scene is not None and getattr(context.scene, SYNCED_PROPERTY, False):
        source_selection_changed(context.scene)  # turned on: the tree takes up the source selection


def _binding_changed(_self: object, context: Any) -> None:
    if context.scene is not None:
        show_inspected_stage(context.scene)


def shows_in_region(area: Any, region: Any) -> bool:
    """Whether a region draws the view now: a 3D View's sidebar on the Proscenium tab."""
    return area.type == "VIEW_3D" and region.type == "UI" and region.active_panel_category == CATEGORY


def draw_inspector_header(layout: Any, scene: bpy.types.Scene) -> bool:
    """The binding dropdown and the sync toggle, or why there is nothing to show; whether to draw the tree."""
    row = layout.row()
    row.prop(scene, BINDING_PROPERTY, text="")
    row.prop(scene, SYNCED_PROPERTY, text="", icon="LINKED" if getattr(scene, SYNCED_PROPERTY, False) else "UNLINKED")
    handle = inspected_handle(scene)
    if handle is None:
        layout.label(text="No binding to inspect")
        return False
    if handle.live_stage() is None:
        layout.label(text="No stage attached")
        return False
    if _key(scene) != _Shown.key:
        widget_updates.schedule(_show_current_stage, 0.0)  # a draw may write no data
    # Values at the time code the display shows; the widget's model only, which a draw may change.
    property_display.set_time_code(PROPERTY_VIEW_NAME, handle.shown_time_code() or Usd.TimeCode.Default())
    return True


def shows_properties(scene: bpy.types.Scene) -> bool:
    """Whether the inspector shows a stage, whose selected prim's properties the property viewer shows."""
    handle = inspected_handle(scene)
    return handle is not None and handle.live_stage() is not None


def draw_selected_prim(layout: Any, scene: bpy.types.Scene) -> None:
    """Whether the prim selected in the tree is displayed, in the browsing universe of the generation shown."""
    handle, path = inspected_handle(scene), display.selected_path(VIEW_NAME)
    if handle is None or path is None or handle.live_stage() is None:
        return
    [shown] = handle.displayed([str(path)])
    layout.label(text="Displayed" if shown else "Not displayed", icon="HIDE_OFF" if shown else "HIDE_ON")


class PROSCENIUM_PT_source_inspector(bpy.types.Panel):  # noqa: N801 - Blender's panel naming
    """The inspected binding's live stage, synced with the source selection or not."""

    bl_label = "Source Inspector"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = CATEGORY

    @override
    def draw(self, context: Any) -> None:
        layout: Any = self.layout  # never None while drawing
        if draw_inspector_header(layout, context.scene):
            display.draw_tree(layout, context, VIEW_NAME)
            draw_selected_prim(layout, context.scene)


class PROSCENIUM_PT_source_properties(bpy.types.Panel):  # noqa: N801 - Blender's panel naming
    """The properties of the prim the source inspector's tree selects."""

    bl_label = "Property Viewer"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = CATEGORY

    @override
    def draw(self, context: Any) -> None:
        layout: Any = self.layout  # never None while drawing
        if shows_properties(context.scene):
            property_display.draw_properties(layout, context, PROPERTY_VIEW_NAME)


class PROSCENIUM_PT_source_property_metadata(bpy.types.Panel):  # noqa: N801 - Blender's panel naming
    """A summary of the property the source inspector's property viewer selects."""

    bl_label = "Property Metadata"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = CATEGORY
    bl_options = {"DEFAULT_CLOSED"}  # noqa: RUF012 - Blender's panel field

    @override
    def draw(self, context: Any) -> None:
        layout: Any = self.layout  # never None while drawing
        if shows_properties(context.scene):
            property_display.draw_metadata(layout, context, PROPERTY_VIEW_NAME)


# In the order they show.
CLASSES = (PROSCENIUM_PT_source_inspector, PROSCENIUM_PT_source_properties, PROSCENIUM_PT_source_property_metadata)


def register() -> None:
    """Register the scene properties and the views, and follow the source selection; the widgets are registered."""
    scene_type: Any = bpy.types.Scene
    setattr(scene_type, BINDING_PROPERTY, bpy.props.EnumProperty(items=binding_items, update=_binding_changed))
    setattr(scene_type, SYNCED_PROPERTY, bpy.props.BoolProperty(default=False, update=_synced_changed))
    display.create_view(VIEW_NAME, shows_in_region, tree_selection_changed)
    property_display.create_view(PROPERTY_VIEW_NAME, shows_in_region, on_jump_to_target=jump_to_target)
    proscenium_sync.BINDINGS.add_selection_listener(source_selection_changed)


def unregister() -> None:
    """Remove what register() added."""
    if source_selection_changed in proscenium_sync.BINDINGS.selection_listeners:
        proscenium_sync.BINDINGS.remove_selection_listener(source_selection_changed)
    widget_updates.unschedule(_show_current_stage)
    property_display.remove_view(PROPERTY_VIEW_NAME)
    display.remove_view(VIEW_NAME)
    _Shown.key = None
    for name in (SYNCED_PROPERTY, BINDING_PROPERTY):
        delattr(bpy.types.Scene, name)
