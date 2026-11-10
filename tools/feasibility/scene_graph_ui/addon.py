"""Proof of concept: a USD scene graph tree in Blender's 3D View sidebar, as a virtualized UIList.

The UIList's collection holds empty items, one per visible row; each row's content is read from
`tree_model.StageTree` by position, so only the row count crosses into RNA. The tree has a header row, custom badge
icons with tooltips, a search that keeps matches' ancestors, and arrow-key navigation. `native_tree` draws the same
stage with Blender's own tree view, for comparison.

Run with ``blender --python tools/feasibility/scene_graph_ui/addon.py``, then open the sidebar's "USD Tree" tab.
"""

from __future__ import annotations

import pathlib
import sys
import time
from typing import TYPE_CHECKING, Any, override

import bpy
from bpy.app.handlers import persistent
from pxr import Sdf, Usd

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import badge_icons  # noqa: E402 (found through the path inserted above when run as a script)
import native_tree  # noqa: E402
import prim_text  # noqa: E402
import tree_keys  # noqa: E402
import tree_model  # noqa: E402
import tree_search  # noqa: E402

if TYPE_CHECKING:
    from bpy.stub_internal.rna_enums import OperatorReturnItems  # stub-only alias

DEMO_SCENE = pathlib.Path(__file__).with_name("demo_stage.usda")
CATEGORY = "USD Tree"
NAME_COLUMN = 0.72  # the share of a row the name column takes, in the header and in each row
INDENT = 2.0  # separator factor per level
SEARCH_CAP = 10_000  # matches; a search stops at this many
SEARCH_DELAY = 0.25  # seconds after the last keystroke before a search runs

TYPE_ICONS = {
    "Xform": "EMPTY_AXIS",
    "Scope": "OUTLINER_COLLECTION",
    "Mesh": "MESH_DATA",
    "Camera": "CAMERA_DATA",
    "Material": "MATERIAL",
    "Shader": "NODE",
    "PointInstancer": "OUTLINER_OB_POINTCLOUD",
    "BasisCurves": "CURVE_DATA",
}


# The process's one tree, rebuilt from scratch whenever a stage opens (state outside RNA is lost on file load).
class _SceneGraphUiState:
    """The open scene graph, selected prim, and search status."""

    tree: tree_model.StageTree | None = None
    selected: Usd.Prim | None = None
    search_status = ""  # what the last search found, or why it couldn't run
    syncing = False  # set while `_sync_rows` moves the active row, so the move doesn't reselect


def _type_icon(type_name: str) -> str:
    if type_name.endswith("Light"):
        return "LIGHT"
    return TYPE_ICONS.get(type_name, "DOT")


def _sync_rows(wm: Any) -> None:
    """Resize the UIList's collection to the model's row count, and keep the selected prim's row active."""
    tree = _SceneGraphUiState.tree
    rows = wm.poc_sg_rows
    count = len(tree.rows) if tree else 0
    if len(rows) > count:
        rows.clear()  # removing items one by one from the end is quadratic
    for _ in range(count - len(rows)):
        rows.add()
    if tree and _SceneGraphUiState.selected is not None:
        index = tree.position(_SceneGraphUiState.selected)
        # Blender 5 keeps bpy.props apart from dict-style ID properties, so a flag stops the update callback.
        _SceneGraphUiState.syncing = True
        try:
            wm.poc_sg_active = index
        finally:
            _SceneGraphUiState.syncing = False


def _set_stage(context: Any, stage: Usd.Stage) -> None:
    _SceneGraphUiState.tree = tree_model.StageTree(stage)
    _SceneGraphUiState.selected = None
    native_tree.reset()
    _sync_rows(context.window_manager)
    context.window_manager.poc_sg_active = -1
    apply_search(context.window_manager)  # a search typed before the stage opened applies to it


def _on_active_row(wm: Any, _context: Any) -> None:
    if _SceneGraphUiState.syncing:
        return
    tree = _SceneGraphUiState.tree
    index = wm.poc_sg_active
    _SceneGraphUiState.selected = tree.rows[index].prim if tree and 0 <= index < len(tree.rows) else None


def _redraw_sidebars() -> None:
    wm: Any = bpy.context.window_manager  # never None while Blender runs timers
    for window in wm.windows:
        for area in window.screen.areas:
            if area.type == "VIEW_3D":
                area.tag_redraw()


def _is_tree_region(area: Any, region: Any) -> bool:
    """Whether a region is showing the tree: a 3D View sidebar on the tree's tab."""
    return area.type == "VIEW_3D" and region.type == "UI" and region.active_panel_category == CATEGORY


def _flag_property(flag: tree_search.SearchFlag) -> str:
    return f"poc_sg_search_{flag.name.lower()}"


def _query(wm: Any) -> tree_search.SearchQuery:
    return tree_search.SearchQuery(
        text=wm.poc_sg_search,
        mode=tree_search.SearchMode[wm.poc_sg_search_mode],
        case_sensitive=wm.poc_sg_search_case,
        type_name=wm.poc_sg_search_type.strip(),
        flags=frozenset(flag for flag in tree_search.SearchFlag if getattr(wm, _flag_property(flag))),
    )


def apply_search(wm: Any) -> None:
    """Filter the tree by the search fields now; an empty search shows everything, keeping the selection revealed."""
    tree = _SceneGraphUiState.tree
    if tree is None:
        return
    query = _query(wm)
    if query.is_empty():
        tree.set_search(None, keep=_SceneGraphUiState.selected)
        _SceneGraphUiState.search_status = ""
    else:
        start = time.perf_counter()
        try:
            result = tree_search.search(tree.stage, query, SEARCH_CAP)
        except tree_search.SearchError as error:
            _SceneGraphUiState.search_status = f"Search: {error}"
            return
        elapsed = (time.perf_counter() - start) * 1000
        tree.set_search(result)
        first = f"first {SEARCH_CAP:,} " if result.is_truncated else ""
        _SceneGraphUiState.search_status = f"{first}{len(result.matching_prims):,} matches in {elapsed:.0f} ms"
    _sync_rows(wm)


def _run_search() -> None:
    apply_search(bpy.context.window_manager)
    _redraw_sidebars()


def _on_search_changed(_wm: Any, _context: Any) -> None:
    # Typing updates on every keystroke (TEXTEDIT_UPDATE), so the search waits for a pause, as a timer.
    if bpy.app.timers.is_registered(_run_search):
        bpy.app.timers.unregister(_run_search)
    bpy.app.timers.register(_run_search, first_interval=SEARCH_DELAY)


def _row_index(item: Any) -> int:
    # An item knows only its RNA path ("poc_sg_rows[12]"), and its row is the one at that position.
    return int(item.path_from_id().rpartition("[")[2].rstrip("]"))


def _row_tooltip(item: Any) -> str:
    tree = _SceneGraphUiState.tree
    index = _row_index(item)
    return prim_text.row_tooltip(tree.rows[index].prim) if tree and index < len(tree.rows) else ""


class POC_SG_Row(bpy.types.PropertyGroup):  # noqa: N801 - Blender's class naming
    """An item with no stored data: the UIList needs one per visible row, and reads the row from the model."""

    # Computed on hover, for the list's item_dyntip_propname.
    tooltip: bpy.props.StringProperty(get=_row_tooltip)  # ty: ignore[invalid-type-form]


class POC_SG_UL_tree(bpy.types.UIList):  # noqa: N801 - Blender's class naming
    """Draws the model's rows as an indented tree with disclosure triangles, in the header's columns."""

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
        tree = _SceneGraphUiState.tree
        if tree is None or index is None or index >= len(tree.rows):
            return
        tree_row = tree.rows[index]
        row_data = tree.details(tree_row)  # read once, when the row first comes on screen
        split = layout.split(factor=NAME_COLUMN if data.poc_sg_show_type else 0.85)
        row = split.row(align=True)
        # Inactive prims, overs, classes, and rows that only hold search matches draw greyed.
        row.is_active = row_data.is_active and row_data.specifier == Sdf.SpecifierDef and tree.is_match(tree_row)
        # One small separator per level: a separator's spacer is square, so one deep one would make the row taller.
        for _ in range(tree_row.depth):
            row.separator(factor=INDENT)
        if row_data.has_children:
            disclosure = "DISCLOSURE_TRI_DOWN" if tree.is_expanded(tree_row) else "DISCLOSURE_TRI_RIGHT"
            row.operator(POC_SG_OT_toggle.bl_idname, text="", icon=disclosure, emboss=False).row_index = index
        else:
            row.label(text="", icon="BLANK1")
        row.label(text=row_data.name, icon=_type_icon(row_data.type_name))
        columns = split.row(align=True)
        columns.alignment = "RIGHT"
        # Badges are borderless buttons, not labels, so each can have a tooltip of its own.
        shown = (
            ("payload", row_data.has_payload),
            ("references", row_data.has_references),
            ("variants", row_data.has_variants),
            ("instance", row_data.is_instance or row_data.is_instance_proxy),
        )
        for badge, has in shown:
            if has:
                button = columns.operator(
                    POC_SG_OT_badge.bl_idname, text="", icon_value=badge_icons.icon_id(badge), emboss=False
                )
                button.row_index = index
                button.badge = badge
        if data.poc_sg_show_type:
            columns.label(text=row_data.type_name or "-")

    @override
    def draw_filter(self, context: bpy.types.Context | None, layout: Any) -> None:
        # The list's own filter options (under its bottom triangle) hold the search's options instead.
        wm: Any = context.window_manager if context else None
        if wm is None:
            return
        col = layout.column(align=True)
        col.prop(wm, "poc_sg_search_type", text="Type", icon="OUTLINER_DATA_EMPTY")
        # One toggle per flag: an expanded ENUM_FLAG sets one item per click, and can't be cleared with one.
        flags = col.row(align=True)
        for flag in tree_search.SearchFlag:
            flags.prop(wm, _flag_property(flag), toggle=True)


def _draw_header(layout: Any, wm: Any) -> None:
    # A row above the list, split like the rows; the list's own padding offsets its columns by a few pixels.
    split = layout.split(factor=NAME_COLUMN if wm.poc_sg_show_type else 0.85)
    split.label(text="    Prim")
    columns = split.row(align=True)
    columns.alignment = "RIGHT"
    if wm.poc_sg_show_type:
        columns.label(text="Type")
    columns.prop(wm, "poc_sg_show_type", text="", icon="HIDE_OFF" if wm.poc_sg_show_type else "HIDE_ON", emboss=False)


class POC_SG_OT_toggle(bpy.types.Operator):  # noqa: N801 - Blender's class naming
    """Expand or collapse a prim (Shift: its whole subtree)."""

    bl_idname = "poc_sg.toggle"
    bl_label = "Toggle Prim"
    bl_options = {"INTERNAL"}  # expansion is view state, so it pushes no undo step

    row_index: bpy.props.IntProperty()  # ty: ignore[invalid-type-form]
    recursive: bpy.props.BoolProperty()  # ty: ignore[invalid-type-form]

    @override
    @classmethod
    def description(cls, context: Any, properties: Any) -> str:
        # The disclosure triangle's tooltip: what a click does to this row, and the keys that do the same.
        tree = _SceneGraphUiState.tree
        if tree is None or properties.row_index >= len(tree.rows):
            return ""
        row = tree.rows[properties.row_index]
        action = "Collapse" if tree.is_expanded(row) else "Expand"
        return f"{action} {row.prim.GetName()}. Shift-click: the whole subtree.\nKeys: {tree_keys.KEY_HINTS}"

    @override
    def invoke(self, context: Any, event: Any) -> set[OperatorReturnItems]:
        self.recursive = event.shift
        return self.execute(context)

    @override
    def execute(self, context: Any) -> set[OperatorReturnItems]:
        tree = _SceneGraphUiState.tree
        if tree is None or not 0 <= self.row_index < len(tree.rows):
            return {"CANCELLED"}
        tree.toggle(self.row_index, recursive=self.recursive)
        _sync_rows(context.window_manager)
        return {"FINISHED"}


def step(wm: Any, direction: str, recursive: bool) -> None:
    """Move through the tree from the keys: IN expands the active row or steps in, OUT collapses it or steps out."""
    tree = _SceneGraphUiState.tree
    if tree is None or not tree.rows:
        return
    index = min(max(wm.poc_sg_active, 0), len(tree.rows) - 1)
    if recursive:
        tree.set_expanded(index, direction == "IN", recursive=True)
        target = index
    else:
        target = tree.expand_or_enter_row(index) if direction == "IN" else tree.collapse_or_select_parent(index)
    _sync_rows(wm)
    wm.poc_sg_active = target


class POC_SG_OT_badge(bpy.types.Operator):  # noqa: N801 - Blender's class naming
    """Select the badge's row."""

    bl_idname = "poc_sg.badge"
    bl_label = "Badge"
    bl_options = {"INTERNAL"}

    row_index: bpy.props.IntProperty()  # ty: ignore[invalid-type-form]
    badge: bpy.props.StringProperty()  # ty: ignore[invalid-type-form]

    @override
    @classmethod
    def description(cls, context: Any, properties: Any) -> str:
        # The tooltip, asked for each button as it is hovered; properties are the button's own.
        tree = _SceneGraphUiState.tree
        if tree is None or properties.row_index >= len(tree.rows):
            return ""
        return prim_text.badge_tooltip(tree.rows[properties.row_index].prim, properties.badge)

    @override
    def execute(self, context: Any) -> set[OperatorReturnItems]:
        context.window_manager.poc_sg_active = self.row_index
        return {"FINISHED"}


class POC_SG_OT_open_stage(bpy.types.Operator):  # noqa: N801 - Blender's class naming
    """Open a USD file as the tree's stage."""

    bl_idname = "poc_sg.open_stage"
    bl_label = "Open Stage"

    filepath: bpy.props.StringProperty(subtype="FILE_PATH", default=str(DEMO_SCENE))  # ty: ignore[invalid-type-form]
    filter_glob: bpy.props.StringProperty(default="*.usd;*.usda;*.usdc;*.usdz", options={"HIDDEN"})  # ty: ignore[invalid-type-form]

    @override
    def invoke(self, context: Any, event: Any) -> set[OperatorReturnItems]:
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    @override
    def execute(self, context: Any) -> set[OperatorReturnItems]:
        stage = Usd.Stage.Open(self.filepath)
        if stage is None:
            self.report({"ERROR"}, f"Could not open {self.filepath}")
            return {"CANCELLED"}
        _set_stage(context, stage)
        return {"FINISHED"}


class POC_SG_OT_open_demo(bpy.types.Operator):  # noqa: N801 - Blender's class naming
    """Open the PoC's demo stage, which has one prim of each kind the rows mark."""

    bl_idname = "poc_sg.open_demo"
    bl_label = "Open Demo Stage"

    @override
    def execute(self, context: Any) -> set[OperatorReturnItems]:
        _set_stage(context, Usd.Stage.Open(str(DEMO_SCENE)))
        return {"FINISHED"}


class POC_SG_OT_generate(bpy.types.Operator):  # noqa: N801 - Blender's class naming
    """Generate an in-memory stage for trying the tree at scale."""

    bl_idname = "poc_sg.generate"
    bl_label = "Generate Stage"

    fanout: bpy.props.IntProperty(name="Fanout", default=8, min=1, max=64)  # ty: ignore[invalid-type-form]
    depth: bpy.props.IntProperty(name="Depth", default=4, min=1, max=8)  # ty: ignore[invalid-type-form]
    wide: bpy.props.IntProperty(name="Wide Group Leaves", default=50_000, min=0, max=1_000_000)  # ty: ignore[invalid-type-form]

    @override
    def invoke(self, context: Any, event: Any) -> set[OperatorReturnItems]:
        return context.window_manager.invoke_props_dialog(self)

    @override
    def execute(self, context: Any) -> set[OperatorReturnItems]:
        _set_stage(context, tree_model.synthetic_stage(self.fanout, self.depth, self.wide))
        return {"FINISHED"}


class POC_SG_OT_find(bpy.types.Operator):  # noqa: N801 - Blender's class naming
    """Select the first prim whose name contains the text, expanding its ancestors."""

    bl_idname = "poc_sg.find"
    bl_label = "Find Prim"

    text: bpy.props.StringProperty(name="Name")  # ty: ignore[invalid-type-form]

    @override
    def invoke(self, context: Any, event: Any) -> set[OperatorReturnItems]:
        return context.window_manager.invoke_props_dialog(self)

    @override
    def execute(self, context: Any) -> set[OperatorReturnItems]:
        tree = _SceneGraphUiState.tree
        if tree is None:
            return {"CANCELLED"}
        needle = self.text.lower()
        prims = Usd.PrimRange(tree.stage.GetPseudoRoot(), tree_model.CHILD_PREDICATE)
        match = next((p for p in prims if needle in p.GetName().lower()), None)
        if match is None:
            self.report({"WARNING"}, f"No prim named like {self.text!r}")
            return {"CANCELLED"}
        tree.reveal(match)
        _SceneGraphUiState.selected = match
        _sync_rows(context.window_manager)
        return {"FINISHED"}


class TreePanel:
    """Draws the UIList tree, with its search above it; a panel class per editor gives its place."""

    bl_label = "Scene Graph (UIList)"
    list_rows = 16  # the list's starting height; it can be dragged taller
    layout: Any

    def draw(self, context: Any) -> None:
        layout: Any = self.layout  # never None while drawing
        wm = context.window_manager
        row = layout.row(align=True)
        row.operator(POC_SG_OT_open_demo.bl_idname, icon="FILE_3D", text="Demo")
        row.operator(POC_SG_OT_open_stage.bl_idname, icon="FILE_FOLDER", text="Open")
        row.operator(POC_SG_OT_generate.bl_idname, icon="ADD", text="Generate")
        row.operator(POC_SG_OT_find.bl_idname, icon="VIEWZOOM", text="")
        tree = _SceneGraphUiState.tree
        if tree is None:
            layout.label(text="No stage open")
            return
        search = layout.row(align=True)
        search.prop(wm, "poc_sg_search", text="", icon="VIEWZOOM", placeholder="Search prims")
        search.prop(wm, "poc_sg_search_mode", text="")
        search.prop(wm, "poc_sg_search_case", text="Aa", toggle=True)
        status = _SceneGraphUiState.search_status or f"{len(tree.rows):,} visible rows"
        layout.label(text=status, icon="ERROR" if status.startswith("Search:") else "NONE")
        _draw_header(layout, wm)
        layout.template_list(
            POC_SG_UL_tree.__name__,
            "",
            wm,
            "poc_sg_rows",
            wm,
            "poc_sg_active",
            item_dyntip_propname="tooltip",
            rows=self.list_rows,
            maxrows=self.list_rows * 3,
        )


class DetailsPanel:
    """Draws what the selected prim is, from whichever tree selected it last."""

    bl_label = "Prim"
    layout: Any

    def draw(self, context: Any) -> None:
        layout: Any = self.layout  # never None while drawing
        tree = _SceneGraphUiState.tree
        prim = _SceneGraphUiState.selected
        native = native_tree.active_path()
        col = layout.column(align=True)
        if native is not None:
            col.label(text=f"Native tree active: {native}")
        if tree is None or prim is None:
            col.label(text="Select a row")
            return
        for line in prim_text.details_lines(prim):
            col.label(text=line)


class POC_SG_PT_tree(TreePanel, bpy.types.Panel):  # noqa: N801 - Blender's class naming
    """The tree in the 3D View sidebar."""

    bl_idname = "POC_SG_PT_tree"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = CATEGORY


class POC_SG_PT_details(DetailsPanel, bpy.types.Panel):  # noqa: N801 - Blender's class naming
    """The prim details in the 3D View sidebar."""

    bl_idname = "POC_SG_PT_details"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = CATEGORY


@persistent
def _on_load_post(_file: str) -> None:
    _SceneGraphUiState.tree = None
    _SceneGraphUiState.selected = None
    _SceneGraphUiState.search_status = ""
    native_tree.reset()


CLASSES = (
    POC_SG_Row,
    POC_SG_UL_tree,
    POC_SG_OT_toggle,
    POC_SG_OT_badge,
    POC_SG_OT_open_stage,
    POC_SG_OT_open_demo,
    POC_SG_OT_generate,
    POC_SG_OT_find,
    POC_SG_PT_tree,
    POC_SG_PT_details,
)


def register() -> None:
    """Register the PoC's classes, window-manager properties, and keys."""
    badge_icons.register()
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    native_tree.register(lambda: _SceneGraphUiState.tree.stage if _SceneGraphUiState.tree else None)
    wm_type: Any = bpy.types.WindowManager
    wm_type.poc_sg_rows = bpy.props.CollectionProperty(type=POC_SG_Row)
    wm_type.poc_sg_active = bpy.props.IntProperty(default=-1, update=_on_active_row)
    wm_type.poc_sg_show_type = bpy.props.BoolProperty(name="Show Type Column", default=True)
    wm_type.poc_sg_search = bpy.props.StringProperty(
        name="Search", options={"TEXTEDIT_UPDATE"}, update=_on_search_changed
    )
    wm_type.poc_sg_search_mode = bpy.props.EnumProperty(
        name="Match",
        items=[(mode.name, mode.value.capitalize(), "") for mode in tree_search.SearchMode],
        update=_on_search_changed,
    )
    wm_type.poc_sg_search_case = bpy.props.BoolProperty(name="Match Case", update=_on_search_changed)
    wm_type.poc_sg_search_type = bpy.props.StringProperty(
        name="Type", description="A schema type the prim must be, such as Mesh or Gprim", update=_on_search_changed
    )
    for flag in tree_search.SearchFlag:
        setattr(
            wm_type,
            _flag_property(flag),
            bpy.props.BoolProperty(name=flag.value.capitalize(), update=_on_search_changed),
        )
    tree_keys.register(step, _is_tree_region)
    bpy.app.handlers.load_post.append(_on_load_post)


def unregister() -> None:
    """Undo `register`."""
    bpy.app.handlers.load_post.remove(_on_load_post)
    tree_keys.unregister()
    if bpy.app.timers.is_registered(_run_search):
        bpy.app.timers.unregister(_run_search)
    wm_type: Any = bpy.types.WindowManager
    for name in (
        *(_flag_property(flag) for flag in tree_search.SearchFlag),
        "poc_sg_search_type",
        "poc_sg_search_case",
        "poc_sg_search_mode",
        "poc_sg_search",
        "poc_sg_show_type",
        "poc_sg_active",
        "poc_sg_rows",
    ):
        delattr(wm_type, name)
    native_tree.unregister()
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
    badge_icons.unregister()


if __name__ == "__main__":
    register()
