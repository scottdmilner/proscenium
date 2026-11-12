"""Demo of hover text and menus: what a row says when hovered, and what a right-click on it can offer.

    Blender --python tools/feasibility/uilist_options/hover_and_menus_demo.py

Open the 3D View's sidebar (N) and its "UIList Demo" tab. Each row has a name, a type, and three buttons, each with
its own kind of tooltip:
- **The row:** `item_dyntip_propname`, a string property whose getter writes the row's tooltip, in one of three
  lengths, to see how a tooltip lays out text.
- **A badge:** an operator whose `description` classmethod writes each button's tooltip from its properties.
- **An eye:** a boolean property, whose tooltip is its one `description`, the same on every row.
- **A dropdown:** an enum property whose items come from a callback per row, so each row's items can describe
  themselves in terms of its prim.

**Right-click** on any part of a row: this demo adds to `UI_MT_list_item_context_menu`, which Blender draws in a
right-click's menu only over a list row, or to `UI_MT_button_context_menu`, which it draws over any button; either
way after Blender's own items, which come first. Each row sets itself in its layout's
context (`context_pointer_set`), so the menu can name the row's prim and offer actions on it, and it lists what else
the context says about the button clicked.

**Status Bar on Hover** has the row tooltip's getter also write the hovered prim's path to the status bar, since
nothing else tells Python which row is under the mouse.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any, override

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parent))

import demo_prim_rows  # noqa: E402 (found through the path inserted above)

if TYPE_CHECKING:
    from bpy.stub_internal.rna_enums import OperatorReturnItems  # stub-only alias

SETTINGS_PROPERTY = "uilist_demo_hover_and_menus"
ROW_CONTEXT_MEMBER = "uilist_demo_row"  # the row item each row sets in its layout's context
VISIBLE_ROW_COUNT = 14
DRAW_MODES = (
    ("DEFAULT", "Default", "full geometry"),
    ("ORIGIN", "Origin", "an axis at its origin"),
    ("BOUNDS", "Bounds", "its bounding box"),
    ("CARDS", "Cards", "textured cards"),
)


class HoverState:
    """The demo's per-row edits, and each row's enum items, which Blender needs kept alive."""

    edits_by_prim_index: dict[int, dict[str, Any]] = {}  # noqa: RUF012 (class-level state)
    draw_mode_items_by_prim_index: dict[int, list[tuple[str, str, str]]] = {}  # noqa: RUF012


def _settings(context: Any) -> Any:
    return getattr(context.window_manager, SETTINGS_PROPERTY)


def _edits(row_item: Any) -> dict[str, Any]:
    return HoverState.edits_by_prim_index.setdefault(row_item.prim_index, {})


def _row_tooltip(row_item: Any) -> str:
    prim = demo_prim_rows.demo_prim(row_item)
    if prim is None:
        return ""
    settings = _settings(bpy.context)
    if settings.is_status_on_hover:
        # The tooltip's getter is the one sign of which row is hovered; it runs when the tooltip is about to show.
        workspace: Any = bpy.context.workspace
        workspace.status_text_set(f"Hovered: {prim.path}")
    if settings.row_tooltip_length == "SHORT":
        return str(prim.path)
    text = demo_prim_rows.prim_tooltip(prim)
    if settings.row_tooltip_length == "LONG":
        text += (
            "\n\nA long paragraph, to see whether a tooltip wraps it: this prim's row says what it is, where it is, "
            "and every composition fact the demo knows of it, and this sentence runs on well past a sidebar's width."
        )
    return text


def _get_is_visible(row_item: Any) -> bool:
    return _edits(row_item).get("is_visible", True)


def _set_is_visible(row_item: Any, value: bool) -> None:
    _edits(row_item)["is_visible"] = value


def _draw_mode_items(row_item: Any, _context: Any) -> list[tuple[str, str, str]]:
    items = HoverState.draw_mode_items_by_prim_index.get(row_item.prim_index)
    if items is None:
        prim = demo_prim_rows.demo_prim(row_item)
        name = prim.name if prim is not None else "this prim"
        items = [(identifier, label, f"Draw {name} as {what}") for identifier, label, what in DRAW_MODES]
        HoverState.draw_mode_items_by_prim_index[row_item.prim_index] = items
    return items


def _get_draw_mode(row_item: Any) -> int:
    return _edits(row_item).get("draw_mode", 0)


def _set_draw_mode(row_item: Any, value: int) -> None:
    _edits(row_item)["draw_mode"] = value


def _add_row_properties() -> None:
    """Give the shared row item the properties this demo's rows draw, and its own row tooltip."""
    item_type: Any = demo_prim_rows.DemoRowItem
    item_type.hover_tooltip = bpy.props.StringProperty(get=_row_tooltip)
    item_type.is_visible = bpy.props.BoolProperty(
        name="Visible",
        description="Whether the prim shows in the viewport: a property's description, the same on every row",
        get=_get_is_visible,
        set=_set_is_visible,
    )
    item_type.draw_mode = bpy.props.EnumProperty(
        name="Draw Mode",
        description="How the viewport draws the prim",
        items=_draw_mode_items,
        get=_get_draw_mode,
        set=_set_draw_mode,
    )


class HoverSettings(bpy.types.PropertyGroup):
    """The row tooltip's length, the status bar on hover, and the context menu's items."""

    row_tooltip_length: bpy.props.EnumProperty(  # ty: ignore[invalid-type-form]
        name="Row Tooltip",
        items=[
            ("SHORT", "Path", "The prim's path only"),
            ("FULL", "Facts", "The path, type, specifier, and composition facts, a line each"),
            ("LONG", "Long", "The facts and a long paragraph"),
        ],
        default="FULL",
    )
    is_status_on_hover: bpy.props.BoolProperty(name="Status Bar on Hover")  # ty: ignore[invalid-type-form]
    context_menu: bpy.props.EnumProperty(  # ty: ignore[invalid-type-form]
        name="Context Menu Items",
        items=[
            ("LIST_ITEM", "List Item Menu", "UI_MT_list_item_context_menu, drawn only for a click on a list row"),
            ("BUTTON", "Button Menu", "UI_MT_button_context_menu, drawn for a click on any button"),
            ("NONE", "None", "Blender's items only"),
        ],
    )
    show_context_details: bpy.props.BoolProperty(  # ty: ignore[invalid-type-form]
        name="Context Details", description="List what the context says about the clicked button", default=True
    )


def _prim_at(prim_index: int) -> demo_prim_rows.DemoPrim | None:
    prims = demo_prim_rows.DemoRowsState.prims
    return prims[prim_index] if 0 <= prim_index < len(prims) else None


class BadgeButton(bpy.types.Operator):
    """A row's badge: it does nothing, and its tooltip is written for its row."""

    bl_idname = "uilist_demo.badge_button"
    bl_label = "Badge"
    bl_options = {"INTERNAL"}

    prim_index: bpy.props.IntProperty()  # ty: ignore[invalid-type-form]

    @classmethod
    @override
    def description(cls, context: Any, properties: Any) -> str:
        prim = _prim_at(properties.prim_index)
        if prim is None:
            return ""
        state = "loaded" if prim.is_loaded else "unloaded"
        payload = f"Payload ({state})" if prim.has_payload else "No payload"
        return f"An operator's description, per button.\n{payload} on {prim.path}"

    @override
    def execute(self, context: Any) -> set[OperatorReturnItems]:
        return {"FINISHED"}


class CopyPrimPath(bpy.types.Operator):
    """Copy the row's prim path to the clipboard."""

    bl_idname = "uilist_demo.copy_prim_path"
    bl_label = "Copy Prim Path"
    bl_options = {"INTERNAL"}

    prim_index: bpy.props.IntProperty()  # ty: ignore[invalid-type-form]

    @override
    def execute(self, context: Any) -> set[OperatorReturnItems]:
        prim = _prim_at(self.prim_index)
        if prim is not None:
            context.window_manager.clipboard = str(prim.path)
        return {"FINISHED"}


class SelectParentRow(bpy.types.Operator):
    """Make the row's parent the active row."""

    bl_idname = "uilist_demo.select_parent_row"
    bl_label = "Select Parent"
    bl_options = {"INTERNAL"}

    prim_index: bpy.props.IntProperty()  # ty: ignore[invalid-type-form]

    @override
    def execute(self, context: Any) -> set[OperatorReturnItems]:
        prim = _prim_at(self.prim_index)
        if prim is None:
            return {"CANCELLED"}
        properties = demo_prim_rows.rows_properties(context)
        for row_index, row_item in enumerate(properties.rows):
            row_prim = demo_prim_rows.demo_prim(row_item)
            if row_prim is not None and row_prim.path == prim.path.GetParentPath():
                properties.active_row_index = row_index
        return {"FINISHED"}


def _describe(value: Any) -> str:
    if value is None:
        return "None"
    identifier = getattr(value, "identifier", None) or getattr(value, "bl_idname", None)
    return f"{type(value).__name__} {identifier}" if identifier else type(value).__name__


def _draw_row_items(layout: Any, context: Any, settings: Any) -> bool:
    """The right-clicked row's prim and actions, and what the context holds; False if the button has no row."""
    row_item: Any = getattr(context, ROW_CONTEXT_MEMBER, None)
    prim = demo_prim_rows.demo_prim(row_item) if row_item is not None else None
    if prim is None:
        return False
    layout.label(text=str(prim.path), icon="OUTLINER_DATA_EMPTY")
    layout.operator(CopyPrimPath.bl_idname, icon="COPYDOWN").prim_index = row_item.prim_index
    layout.operator(SelectParentRow.bl_idname, icon="FILE_PARENT").prim_index = row_item.prim_index
    if settings.show_context_details:
        details = layout.column()
        details.active = False
        details.label(text=f"button_pointer: {_describe(getattr(context, 'button_pointer', None))}")
        details.label(text=f"button_prop: {_describe(getattr(context, 'button_prop', None))}")
        details.label(text=f"button_operator: {_describe(getattr(context, 'button_operator', None))}")
    return True


def _draw_menu_items(layout: Any, context: Any, settings: Any) -> None:
    column = layout.column()
    column.separator()  # below Blender's own items, which always come first
    if not _draw_row_items(column, context, settings) and settings.show_context_details:
        column.label(text="UIList demo: no row in this button's context")


def append_to_list_item_context_menu(self: Any, context: Any) -> None:
    """Appended to UI_MT_list_item_context_menu, which Blender draws only for a right-click on a list row."""
    settings = _settings(context)
    if settings.context_menu == "LIST_ITEM":
        _draw_menu_items(self.layout, context, settings)


def append_to_button_context_menu(self: Any, context: Any) -> None:
    """Appended to UI_MT_button_context_menu, which Blender draws for a right-click on any button."""
    settings = _settings(context)
    if settings.context_menu == "BUTTON":
        _draw_menu_items(self.layout, context, settings)


class HoverList(bpy.types.UIList):
    """Draws each row with a context member naming it, and a button of each tooltip kind."""

    bl_idname = "UILIST_DEMO_UL_hover_and_menus"

    @override
    def draw_item(
        self,
        context: bpy.types.Context | None,
        layout: Any,
        data: Any,
        item: Any,
        icon: int | None,
        active_data: Any,
        active_property: str | None,
        index: int | None,
        flt_flag: int | None,
    ) -> None:
        prim = demo_prim_rows.demo_prim(item)
        if prim is None:
            return
        layout.context_pointer_set(ROW_CONTEXT_MEMBER, item)  # every button below carries its row to the menu
        split = layout.split(factor=0.5)
        name_row = split.row(align=True)
        demo_prim_rows.indent(name_row, prim)
        name_row.label(text=prim.name, icon="OUTLINER_DATA_EMPTY" if not prim.type_name else "OBJECT_DATA")
        columns = split.row(align=True)
        columns.alignment = "RIGHT"
        type_cell = columns.row(align=True)
        type_cell.ui_units_x = 3.0
        type_cell.alignment = "CENTER"
        type_cell.label(text=prim.type_name or "—")
        badge_icon = "PACKAGE" if prim.has_payload else "DOT"
        badge = columns.operator(BadgeButton.bl_idname, text="", icon=badge_icon, emboss=False)
        badge.prim_index = item.prim_index
        eye = "HIDE_OFF" if item.is_visible else "HIDE_ON"
        columns.prop(item, "is_visible", text="", icon=eye, emboss=False)
        mode_cell = columns.row(align=True)
        mode_cell.ui_units_x = 4.0
        mode_cell.alignment = "EXPAND"  # under the inherited RIGHT, the dropdown shrinks to its arrow
        mode_cell.prop(item, "draw_mode", text="")


class HoverPanel(bpy.types.Panel):
    """The list, then the tooltip and menu settings."""

    bl_idname = "VIEW3D_PT_uilist_demo_hover_and_menus"
    bl_label = "4. Hover Text and Menus"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = demo_prim_rows.CATEGORY

    @override
    def draw(self, context: Any) -> None:
        layout: Any = self.layout
        settings = _settings(context)
        properties = demo_prim_rows.rows_properties(context)
        layout.template_list(
            HoverList.bl_idname,
            "",
            properties,
            "rows",
            properties,
            "active_row_index",
            item_dyntip_propname="hover_tooltip",
            rows=VISIBLE_ROW_COUNT,
            maxrows=VISIBLE_ROW_COUNT,
        )
        box = layout.box().column()
        box.label(text="Hover a row, its badge, eye, or dropdown")
        box.row().prop(settings, "row_tooltip_length", expand=True)
        row = box.row(align=True)
        row.prop(settings, "is_status_on_hover")
        row.operator(ClearStatusText.bl_idname, text="", icon="X")
        box = layout.box().column()
        box.label(text="Right-click any part of a row")
        box.row().prop(settings, "context_menu", expand=True)
        sub = box.row()
        sub.active = settings.context_menu != "NONE"
        sub.prop(settings, "show_context_details")


class ClearStatusText(bpy.types.Operator):
    """Restore the status bar's own text."""

    bl_idname = "uilist_demo.clear_status_text"
    bl_label = "Clear Status Text"
    bl_options = {"INTERNAL"}

    @override
    def execute(self, context: Any) -> set[OperatorReturnItems]:
        context.workspace.status_text_set(None)
        return {"FINISHED"}


CLASSES = (HoverSettings, BadgeButton, CopyPrimPath, SelectParentRow, ClearStatusText, HoverList, HoverPanel)


def main() -> None:
    """Register the demo and its context menu items, and fill its rows."""
    demo_prim_rows.register_rows()
    _add_row_properties()
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    setattr(bpy.types.WindowManager, SETTINGS_PROPERTY, bpy.props.PointerProperty(type=HoverSettings))
    menu_types: Any = bpy.types  # the stubs type a menu's draw functions without self
    menu_types.UI_MT_list_item_context_menu.append(append_to_list_item_context_menu)
    menu_types.UI_MT_button_context_menu.append(append_to_button_context_menu)


if __name__ == "__main__":
    main()
