"""Demo of the widget's right-click: its own menu for the row under the mouse, or its items in Blender's menu.

    Blender --python tools/feasibility/uilist_options/right_click_demo.py

Open the 3D View's sidebar (N) and its "UIList Demo" tab, and right-click the rows, which are labels:
- **On a verified build,** a watcher in each window takes a right-click over this demo's list, which `context.ui_list`
  names in the region under the mouse, and leaves every other right-click to Blender. It finds the row under the
  mouse with Blender's own list hit-testing, among the rows `draw_item` last drew, and opens this demo's menu for it,
  so Blender's menu doesn't open. The hit-testing calls private C++ functions of the executable through `ctypes`, so
  it runs only on a build checked by platform, version, and build hash.
- **On any other build,** or with **Native Hit Test** off, Blender's menu opens, and this demo adds its items to
  `UI_MT_list_item_context_menu`, after Blender's own, for the row its layout's context names.

The menu names the row's prim and offers Copy Prim Path and Select Parent. The panel shows what the last right-click
found.
"""

from __future__ import annotations

import ctypes
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any, override

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parent))

import demo_prim_rows  # noqa: E402 (found through the path inserted above)

if TYPE_CHECKING:
    from bpy.stub_internal.rna_enums import OperatorReturnItems  # stub-only alias

SETTINGS_PROPERTY = "uilist_demo_right_click"
ROW_CONTEXT_MEMBER = "uilist_demo_row"  # the row item each row sets in its layout's context
VISIBLE_ROW_COUNT = 14
WATCHER_START_DELAY_SECONDS = 0.5


class NativeListHitTest:
    """Blender's own list hit-testing, called through ctypes: private C++ functions of a verified executable.

    They only read the region's buttons (interface_query.cc), but nothing promises their names or signatures, and a
    mismatch would crash Blender, so this refuses any build not on the allowlist. PyDLL keeps the GIL held, and every
    call is on Blender's UI thread.
    """

    VERIFIED_BUILDS = {("darwin", (5, 2, 2), b"d13f752e3b9c")}  # platform, Blender version, build hash
    SYMBOLS = {
        "listbox_under": "_ZN7blender2ui26listbox_find_mouse_over_exEPKNS_7ARegionEPKi",
        "listrow_under": "_ZN7blender2ui23listrow_find_mouse_overEPKNS_7ARegionEPKi",
        "listrow_at_index": "_ZN7blender2ui18listrow_find_indexEPKNS_7ARegionEiPNS0_6ButtonE",
    }

    functions: dict[str, Any]

    def __init__(self) -> None:
        build = (sys.platform, bpy.app.version, bpy.app.build_hash)
        if build not in self.VERIFIED_BUILDS:
            raise RuntimeError(f"native list hit-testing isn't verified on {build}")
        library = ctypes.PyDLL(None)
        pointer, position = ctypes.c_void_p, ctypes.POINTER(ctypes.c_int)
        argument_types = {
            "listbox_under": [pointer, position],
            "listrow_under": [pointer, position],
            "listrow_at_index": [pointer, ctypes.c_int, pointer],
        }
        self.functions = {}
        for name, symbol in self.SYMBOLS.items():
            function = getattr(library, symbol)
            function.argtypes = argument_types[name]
            function.restype = ctypes.c_void_p
            self.functions[name] = function

    def row_index_under(self, region: Any, x: int, y: int, candidate_row_indices: list[int]) -> int | None:
        """The row index under a window position, among the candidates: the list's row button there, by pointer."""
        position = (ctypes.c_int * 2)(x, y)
        region_address = region.as_pointer()
        listbox = self.functions["listbox_under"](region_address, position)
        listrow = self.functions["listrow_under"](region_address, position)
        if not listbox or not listrow:
            return None
        listrow_at_index = self.functions["listrow_at_index"]
        return next((i for i in candidate_row_indices if listrow_at_index(region_address, i, listbox) == listrow), None)


class RightClickState:
    """The hit test, the watchers by window, the rows last drawn, the menu's row, and the last right-click's report."""

    hit_test: NativeListHitTest | None = None
    hit_test_error = ""
    watched_window_pointers: set[int] = set()  # noqa: RUF012 (class-level state)
    drawn_row_indices: list[int] = []  # noqa: RUF012 (the rows draw_item drew in the list's last draw)
    menu_prim_index = -1
    last_report = "No right-click yet"


def _create_hit_test() -> None:
    try:
        RightClickState.hit_test = NativeListHitTest()
    except (RuntimeError, AttributeError) as error:  # not a verified build, or a symbol is missing
        RightClickState.hit_test_error = str(error)


def _settings(context: Any) -> Any:
    return getattr(context.window_manager, SETTINGS_PROPERTY)


def _uses_native_hit_test(context: Any) -> bool:
    return RightClickState.hit_test is not None and _settings(context).use_native_hit_test


def _prim_at(prim_index: int) -> demo_prim_rows.DemoPrim | None:
    prims = demo_prim_rows.DemoRowsState.prims
    return prims[prim_index] if 0 <= prim_index < len(prims) else None


def _report(context: Any, text: str) -> None:
    RightClickState.last_report = text
    for window in context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == "VIEW_3D":
                area.tag_redraw()


class RightClickSettings(bpy.types.PropertyGroup):
    """Whether the watcher uses the native hit test, on a build where it can."""

    use_native_hit_test: bpy.props.BoolProperty(  # ty: ignore[invalid-type-form]
        name="Native Hit Test",
        description="Take right-clicks over the list for this demo's menu; off, Blender's menu opens with its items",
        default=True,
    )


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


def _draw_row_items(layout: Any, prim_index: int) -> bool:
    """The row's prim and actions; False if there's no such prim."""
    prim = _prim_at(prim_index)
    if prim is None:
        return False
    layout.label(text=str(prim.path), icon="OUTLINER_DATA_EMPTY")
    layout.operator(CopyPrimPath.bl_idname, icon="COPYDOWN").prim_index = prim_index
    layout.operator(SelectParentRow.bl_idname, icon="FILE_PARENT").prim_index = prim_index
    return True


class RowMenu(bpy.types.Menu):
    """This demo's own menu, for the row the watcher found."""

    bl_idname = "UILIST_DEMO_MT_right_click_row"
    bl_label = "Prim"

    @override
    def draw(self, context: Any) -> None:
        layout: Any = self.layout
        if not _draw_row_items(layout, RightClickState.menu_prim_index):
            layout.label(text="No row")


def append_to_list_item_context_menu(self: Any, context: Any) -> None:
    """Appended to UI_MT_list_item_context_menu: this demo's items, after Blender's, when the watcher let it open."""
    row_item: Any = getattr(context, ROW_CONTEXT_MEMBER, None)
    if row_item is None or _uses_native_hit_test(context):
        return
    column = self.layout.column()
    column.separator()
    _draw_row_items(column, row_item.prim_index)


def _sidebar_under(window: Any, x: int, y: int) -> tuple[Any, Any] | None:
    """The 3D View and its sidebar region under a window position, if a sidebar is there."""
    for area in window.screen.areas:
        if area.type != "VIEW_3D":
            continue
        for region in area.regions:
            is_inside = region.x <= x < region.x + region.width and region.y <= y < region.y + region.height
            if region.type == "UI" and is_inside:
                return area, region
    return None


class WatchRightClick(bpy.types.Operator):
    """Takes each right-click over this demo's list before Blender's UI does, and opens a menu for its row."""

    bl_idname = "uilist_demo.watch_right_click"
    bl_label = "Watch Right Click"
    bl_options = {"INTERNAL"}

    @override
    def invoke(self, context: Any, event: Any) -> set[OperatorReturnItems]:
        window_pointer = context.window.as_pointer()
        if window_pointer in RightClickState.watched_window_pointers:
            return {"CANCELLED"}
        RightClickState.watched_window_pointers.add(window_pointer)
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    @override
    def modal(self, context: Any, event: Any) -> set[OperatorReturnItems]:
        if event.type != "RIGHTMOUSE" or event.value != "PRESS" or not _uses_native_hit_test(context):
            return {"PASS_THROUGH"}
        sidebar = _sidebar_under(context.window, event.mouse_x, event.mouse_y)
        if sidebar is None:
            return {"PASS_THROUGH"}
        area, region = sidebar
        with context.temp_override(area=area, region=region):
            ui_list = getattr(bpy.context, "ui_list", None)
        if ui_list is None or ui_list.bl_idname != RightClickList.bl_idname:
            return {"PASS_THROUGH"}  # another list, or none: Blender's menu
        hit_test = RightClickState.hit_test
        assert hit_test is not None
        candidates = sorted(set(RightClickState.drawn_row_indices))
        row_index = hit_test.row_index_under(region, event.mouse_x, event.mouse_y, candidates)
        properties = demo_prim_rows.rows_properties(context)
        if row_index is None or row_index >= len(properties.rows):
            _report(context, f"Native hit test: no row among {len(candidates)} on screen; Blender's menu")
            return {"PASS_THROUGH"}
        RightClickState.menu_prim_index = properties.rows[row_index].prim_index
        prim = _prim_at(RightClickState.menu_prim_index)
        _report(
            context, f"Native hit test: row {row_index} of {len(candidates)} on screen, {prim.path if prim else None}"
        )
        bpy.ops.wm.call_menu(name=RowMenu.bl_idname)
        return {"RUNNING_MODAL"}  # the press is the watcher's: Blender's menu doesn't open


def _start_watchers() -> None:
    wm: Any = bpy.context.window_manager
    for window in wm.windows:
        override: Any = bpy.context.temp_override(window=window)  # the stubs miss its context manager methods
        with override:
            bpy.ops.uilist_demo.watch_right_click("INVOKE_DEFAULT")  # ty: ignore[unresolved-attribute]


class RightClickList(bpy.types.UIList):
    """Draws each row as labels, with a context member naming its item, and notes which rows it drew."""

    bl_idname = "UILIST_DEMO_UL_right_click"

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
        if index is not None:
            RightClickState.drawn_row_indices.append(index)  # only rows on screen are drawn, and have row buttons
        layout.context_pointer_set(ROW_CONTEXT_MEMBER, item)  # for Blender's list item menu
        split = layout.split(factor=0.6)
        name_row = split.row(align=True)
        demo_prim_rows.indent(name_row, prim)
        name_row.label(text=prim.name, icon="OUTLINER_DATA_EMPTY" if not prim.type_name else "OBJECT_DATA")
        type_cell = split.row(align=True)
        type_cell.alignment = "RIGHT"
        type_cell.label(text=prim.type_name or "—")


class RightClickPanel(bpy.types.Panel):
    """The list, the native hit test's setting or why it's unavailable, and the last right-click's report."""

    bl_idname = "VIEW3D_PT_uilist_demo_right_click"
    bl_label = "4. Right-Click"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = demo_prim_rows.CATEGORY

    @override
    def draw(self, context: Any) -> None:
        layout: Any = self.layout
        properties = demo_prim_rows.rows_properties(context)
        RightClickState.drawn_row_indices = []
        layout.template_list(
            RightClickList.bl_idname,
            "",
            properties,
            "rows",
            properties,
            "active_row_index",
            item_dyntip_propname="tooltip",
            rows=VISIBLE_ROW_COUNT,
            maxrows=VISIBLE_ROW_COUNT,
        )
        box = layout.box().column()
        if RightClickState.hit_test is None:
            box.label(text="Native hit test unavailable: Blender's menu", icon="INFO")
            box.label(text=RightClickState.hit_test_error)
        else:
            box.prop(_settings(context), "use_native_hit_test")
        report = box.row()
        report.active = False
        report.label(text=RightClickState.last_report)


CLASSES = (RightClickSettings, CopyPrimPath, SelectParentRow, RowMenu, WatchRightClick, RightClickList, RightClickPanel)


def main() -> None:
    """Register the demo, its menu items, and its watchers, and make the hit test if this build is verified."""
    demo_prim_rows.register_rows()
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    setattr(bpy.types.WindowManager, SETTINGS_PROPERTY, bpy.props.PointerProperty(type=RightClickSettings))
    menu_types: Any = bpy.types  # the stubs type a menu's draw functions without self
    menu_types.UI_MT_list_item_context_menu.append(append_to_list_item_context_menu)
    _create_hit_test()
    bpy.app.timers.register(_start_watchers, first_interval=WATCHER_START_DELAY_SECONDS)


if __name__ == "__main__":
    main()
