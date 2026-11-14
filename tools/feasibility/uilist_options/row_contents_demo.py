"""Demo of a row's contents: the items a row can hold, each showing a prim fact, in columns that can be turned on.

    Blender --python tools/feasibility/uilist_options/row_contents_demo.py

Open the 3D View's sidebar (N) and its "UIList Demo" tab. Each prim has one state, the first that holds of: class,
over, inactive, unloaded payload, instance proxy, instance, and has arcs. Four columns show that state in four ways:
- **Glyph:** a text character before the name.
- **Dot:** `template_node_socket`, a dot in any color.
- **Icon:** one of Blender's fixed-color icons (`STRIP_COLOR_01`-`09`).
- **Shape:** a preview icon drawn from pixels here, any shape and color.

The legend under the list shows every state in all four. The other columns are what a row can hold besides:
- **Name icon:** the prim's type icon, its model kind's icon, or a larger `template_icon`, which overflows its row.
- **Column dividers:** a `│` or `|` character, or a `LINE` separator, in a narrow cell before each column, or
  each cell in a `box()`, or a disabled button squeezed narrow, as Collection Manager draws its separators; in the
  header too.
- **Row dividers:** a full-width button squeezed to a hairline's height, or a `LINE` separator, under each row's
  contents, which shrink by as much so the row keeps its height.
- **Disclosure triangles:** as the widget's, which collapse and expand a prim by remaking the rows.
- **Indentation:** separators, as the widget indents; `LINE` separators, which draw horizontal lines; or guide
  glyphs worked out from the model.
- **Eye** and **Active:** a boolean property per row, drawn as an icon toggle and as a checkbox.
- **Draw:** an enum property per row, as a dropdown; **Variant:** one whose items come from the prim's variant set.
- **Share:** `progress`, as a bar or a ring, for the share of the stage's prims under the prim.
- **Swatch:** a color property drawn without text.
- **Menu:** a menu button per row, which reads its row from `context_pointer_set`.

The per-row properties edit only the demo's own state, never the stage. **Unload Payloads** opens the stage with
its payloads unloaded, so that state has rows.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any, override

import bpy
import bpy.utils.previews
from pxr import Sdf

sys.path.insert(0, str(Path(__file__).resolve().parent))

import demo_prim_rows  # noqa: E402 (found through the path inserted above)

if TYPE_CHECKING:
    from bpy.stub_internal.rna_enums import OperatorReturnItems  # stub-only alias

SETTINGS_PROPERTY = "uilist_demo_row_contents"
ROW_CONTEXT_MEMBER = "uilist_demo_row"  # the row item a row's menu button reads from its context
VISIBLE_ROW_COUNT = 14
ICON_SIZE_PIXELS = 32
# Each state, in the order it's tested: label, glyph, dot color, fixed-color icon, and preview icon shape.
PRIM_STATES = {
    "CLASS": ("Class", "◇", (0.65, 0.45, 0.95, 1.0), "STRIP_COLOR_06", "diamond"),
    "OVER": ("Over", "○", (0.6, 0.6, 0.6, 1.0), "STRIP_COLOR_09", "ring"),
    "INACTIVE": ("Inactive", "×", (0.9, 0.25, 0.25, 1.0), "STRIP_COLOR_01", "cross"),
    "UNLOADED": ("Unloaded payload", "◌", (0.95, 0.55, 0.15, 1.0), "STRIP_COLOR_02", "dashed ring"),
    "INSTANCE_PROXY": ("Instance proxy", "▫", (0.35, 0.8, 0.45, 1.0), "STRIP_COLOR_04", "small square"),
    "INSTANCE": ("Instance", "◆", (0.35, 0.6, 0.95, 1.0), "STRIP_COLOR_05", "circle"),
    "HAS_ARCS": ("Has arcs", "•", (0.95, 0.85, 0.25, 1.0), "STRIP_COLOR_03", "square"),
}
MODEL_KIND_ICONS = {"assembly": "ASSET_MANAGER", "group": "OUTLINER_COLLECTION", "component": "MESH_CUBE"}
DRAW_MODES = [
    ("DEFAULT", "Default", "Full geometry"),
    ("ORIGIN", "Origin", "An axis at the origin"),
    ("BOUNDS", "Bounds", "The bounding box"),
    ("CARDS", "Cards", "Textured cards"),
]
# Each optional column: its setting, header text, and width in UI units.
COLUMNS = (
    ("show_glyph_column", "", 1.0),
    ("show_dot_column", "", 1.0),
    ("show_icon_column", "", 1.0),
    ("show_shape_column", "", 1.0),
    ("show_eye_column", "", 1.0),
    ("show_active_column", "", 1.0),
    ("show_draw_column", "Draw", 4.0),
    ("show_variant_column", "Variant", 4.0),
    ("show_share_column", "Share", 3.0),
    ("show_swatch_column", "", 1.2),
    ("show_menu_column", "", 1.0),
)
COLUMN_HEADER_ICONS = {
    "show_glyph_column": "FONT_DATA",
    "show_dot_column": "NODE_SOCKET_SHADER",
    "show_icon_column": "COLOR",
    "show_shape_column": "MOD_HUE_SATURATION",
    "show_eye_column": "HIDE_OFF",
    "show_active_column": "CHECKBOX_HLT",
    "show_swatch_column": "COLORSET_13_VEC",
    "show_menu_column": "DOWNARROW_HLT",
}


class RowContentsState:
    """The preview icons, the demo's per-row edits, and what's cached per stage."""

    previews: Any = None
    edits_by_prim_index: dict[int, dict[str, Any]] = {}  # noqa: RUF012 (class-level state)
    variant_items_by_prim_index: dict[int, list[tuple[str, str, str]]] = {}  # noqa: RUF012
    descendant_counts: dict[Sdf.Path, int] = {}  # noqa: RUF012
    guide_glyphs_by_path: dict[Sdf.Path, list[str]] = {}  # noqa: RUF012 (one glyph per indent level)
    parent_paths: set[Sdf.Path] = set()  # noqa: RUF012 (the prims with children)
    collapsed_paths: set[Sdf.Path] = set()  # noqa: RUF012


def prim_state(prim: demo_prim_rows.DemoPrim) -> str | None:
    """The first state that holds of the prim, or None for a plain def."""
    holds = (
        ("CLASS", prim.specifier == Sdf.SpecifierClass),
        ("OVER", prim.specifier == Sdf.SpecifierOver),
        ("INACTIVE", not prim.is_active),
        ("UNLOADED", prim.has_payload and not prim.is_loaded),
        ("INSTANCE_PROXY", prim.is_instance_proxy),
        ("INSTANCE", prim.is_instance),
        ("HAS_ARCS", prim.has_arcs),
    )
    return next((state for state, is_held in holds if is_held), None)


def _inside(shape: str, x: float, y: float) -> bool:
    # x and y run from -1 to 1 across the icon.
    radius = (x * x + y * y) ** 0.5
    if shape == "circle":
        return radius < 0.7
    if shape == "ring":
        return 0.42 < radius < 0.72
    if shape == "dashed ring":
        return 0.42 < radius < 0.72 and (int((x + 1) * 4) + int((y + 1) * 4)) % 2 == 0
    if shape == "diamond":
        return abs(x) + abs(y) < 0.8
    if shape == "cross":
        return (abs(x - y) < 0.22 or abs(x + y) < 0.22) and max(abs(x), abs(y)) < 0.7
    if shape == "small square":
        return max(abs(x), abs(y)) < 0.35
    return max(abs(x), abs(y)) < 0.58  # square


def _create_previews() -> None:
    previews: Any = bpy.utils.previews.new()
    for state, (_label, _glyph, color, _icon, shape) in PRIM_STATES.items():
        pixels: list[float] = []
        for pixel_row in range(ICON_SIZE_PIXELS):
            for pixel_column in range(ICON_SIZE_PIXELS):
                x = (pixel_column + 0.5) / ICON_SIZE_PIXELS * 2 - 1
                y = (pixel_row + 0.5) / ICON_SIZE_PIXELS * 2 - 1
                pixels.extend(color if _inside(shape, x, y) else (0.0, 0.0, 0.0, 0.0))
        preview = previews.new(state)
        preview.icon_size = (ICON_SIZE_PIXELS, ICON_SIZE_PIXELS)
        preview.icon_pixels_float = pixels
        # template_icon draws a preview's image, not its icon.
        preview.image_size = (ICON_SIZE_PIXELS, ICON_SIZE_PIXELS)
        preview.image_pixels_float = pixels
    RowContentsState.previews = previews


def _shape_icon_id(state: str) -> int:
    return RowContentsState.previews[state].icon_id


def _forget_stage_caches() -> None:
    RowContentsState.edits_by_prim_index.clear()
    RowContentsState.variant_items_by_prim_index.clear()
    counts: dict[Sdf.Path, int] = {}
    for prim in demo_prim_rows.DemoRowsState.prims:
        for ancestor_path in prim.path.GetPrefixes()[:-1]:
            counts[ancestor_path] = counts.get(ancestor_path, 0) + 1
    RowContentsState.descendant_counts = counts
    RowContentsState.guide_glyphs_by_path = _guide_glyphs(demo_prim_rows.DemoRowsState.prims)
    RowContentsState.parent_paths = {prim.path.GetParentPath() for prim in demo_prim_rows.DemoRowsState.prims}
    RowContentsState.collapsed_paths = set()


def _fill_visible_rows(context: Any) -> None:
    """Make a row item for each prim under no collapsed ancestor, keeping the active row's prim active."""
    properties = demo_prim_rows.rows_properties(context)
    row_index = properties.active_row_index
    active_prim = (
        demo_prim_rows.demo_prim(properties.rows[row_index]) if 0 <= row_index < len(properties.rows) else None
    )
    collapsed_paths = RowContentsState.collapsed_paths
    properties.rows.clear()
    properties.active_row_index = -1
    for prim_index, prim in enumerate(demo_prim_rows.DemoRowsState.prims):
        if any(path in collapsed_paths for path in prim.path.GetPrefixes()[:-1]):
            continue
        row_item = properties.rows.add()
        row_item.name = prim.name
        row_item.prim_index = prim_index
        if active_prim is not None and prim.path == active_prim.path:
            properties.active_row_index = len(properties.rows) - 1


def _guide_glyphs(prims: list[demo_prim_rows.DemoPrim]) -> dict[Sdf.Path, list[str]]:
    """Each prim's guide glyphs: a line for each ancestor with a later sibling, then its own connector."""
    last_child_path_by_parent = {prim.path.GetParentPath(): prim.path for prim in prims}  # the last one listed wins
    has_later_sibling = {prim.path: last_child_path_by_parent[prim.path.GetParentPath()] != prim.path for prim in prims}
    glyphs_by_path = {}
    for prim in prims:
        if prim.depth == 0:
            glyphs_by_path[prim.path] = []
            continue
        ancestor_paths = prim.path.GetPrefixes()[1:-1]  # below the top level, above the prim
        glyphs = ["│" if has_later_sibling.get(path, False) else "" for path in ancestor_paths]
        glyphs.append("├" if has_later_sibling[prim.path] else "└")
        glyphs_by_path[prim.path] = glyphs
    return glyphs_by_path


def _edits(row_item: Any) -> dict[str, Any]:
    return RowContentsState.edits_by_prim_index.setdefault(row_item.prim_index, {})


def _get_is_visible(row_item: Any) -> bool:
    return _edits(row_item).get("is_visible", True)


def _set_is_visible(row_item: Any, value: bool) -> None:
    _edits(row_item)["is_visible"] = value


def _get_is_active(row_item: Any) -> bool:
    prim = demo_prim_rows.demo_prim(row_item)
    return _edits(row_item).get("is_active", prim.is_active if prim is not None else True)


def _set_is_active(row_item: Any, value: bool) -> None:
    _edits(row_item)["is_active"] = value


def _get_draw_mode(row_item: Any) -> int:
    return _edits(row_item).get("draw_mode", 0)


def _set_draw_mode(row_item: Any, value: int) -> None:
    _edits(row_item)["draw_mode"] = value


def _variant_items(row_item: Any, _context: Any) -> list[tuple[str, str, str]]:
    # Blender keeps no reference to an items callback's strings, so the lists are kept here.
    items = RowContentsState.variant_items_by_prim_index.get(row_item.prim_index)
    if items is None:
        prim = demo_prim_rows.demo_prim(row_item)
        stage = demo_prim_rows.DemoRowsState.stage
        usd_prim = stage.GetPrimAtPath(prim.path) if stage is not None and prim is not None else None
        items = []
        if usd_prim is not None and usd_prim.IsValid():
            variant_sets = usd_prim.GetVariantSets()
            for set_name in variant_sets.GetNames():
                for variant_name in variant_sets.GetVariantSet(set_name).GetVariantNames():
                    items.append((f"{set_name}={variant_name}", variant_name, f"Variant set {set_name}"))
        items = items or [("NONE", "—", "No variant sets")]
        RowContentsState.variant_items_by_prim_index[row_item.prim_index] = items
    return items


def _get_variant(row_item: Any) -> int:
    return _edits(row_item).get("variant", 0)


def _set_variant(row_item: Any, value: int) -> None:
    _edits(row_item)["variant"] = value


def _get_state_color(row_item: Any) -> tuple[float, float, float, float]:
    prim = demo_prim_rows.demo_prim(row_item)
    state = prim_state(prim) if prim is not None else None
    return PRIM_STATES[state][2] if state is not None else (0.0, 0.0, 0.0, 0.0)


def _add_row_properties() -> None:
    """Give the shared row item the properties this demo's columns draw."""
    item_type: Any = demo_prim_rows.DemoRowItem
    item_type.is_visible = bpy.props.BoolProperty(name="Visible", get=_get_is_visible, set=_set_is_visible)
    item_type.is_active_toggle = bpy.props.BoolProperty(name="Active", get=_get_is_active, set=_set_is_active)
    item_type.draw_mode = bpy.props.EnumProperty(
        name="Draw Mode", items=DRAW_MODES, get=_get_draw_mode, set=_set_draw_mode
    )
    item_type.variant = bpy.props.EnumProperty(name="Variant", items=_variant_items, get=_get_variant, set=_set_variant)
    item_type.state_color = bpy.props.FloatVectorProperty(
        name="State Color", subtype="COLOR", size=4, min=0.0, max=1.0, get=_get_state_color
    )


def _reopen_stage(settings: Any, _context: Any) -> None:
    demo_prim_rows.open_demo_stage(load_payloads=not settings.unload_payloads)
    _forget_stage_caches()


def _column_property(name: str, default: bool) -> Any:
    return bpy.props.BoolProperty(name=name, default=default)


class RowContentsSettings(bpy.types.PropertyGroup):
    """Which columns show, and how the name and the share draw."""

    name_icon: bpy.props.EnumProperty(  # ty: ignore[invalid-type-form]
        name="Name Icon",
        items=[
            ("TYPE", "Type", "Blender's icon for the prim's type"),
            ("KIND", "Kind", "An icon for the prim's model kind, or its type's if it has none"),
            ("LARGE", "Large", "The state's preview icon through template_icon, at 1.5 times"),
            ("NONE", "None", "No icon"),
        ],
    )
    indentation: bpy.props.EnumProperty(  # ty: ignore[invalid-type-form]
        name="Indentation",
        items=[
            ("SPACE", "Space", "One separator(factor=2.0) per level, as the widget indents"),
            ("LINE", "LINE", "separator(type='LINE'), which draws a short horizontal line"),
            (
                "GLYPHS",
                "Guide Glyphs",
                "Box-drawing characters from the model: │ for an ancestor with a later sibling, ├ or └",
            ),
        ],
    )
    show_glyph_column: _column_property("Glyph", True)  # ty: ignore[invalid-type-form]
    show_dot_column: _column_property("Dot", True)  # ty: ignore[invalid-type-form]
    show_icon_column: _column_property("Icon", True)  # ty: ignore[invalid-type-form]
    show_shape_column: _column_property("Shape", True)  # ty: ignore[invalid-type-form]
    show_eye_column: _column_property("Eye", False)  # ty: ignore[invalid-type-form]
    show_active_column: _column_property("Active", False)  # ty: ignore[invalid-type-form]
    show_draw_column: _column_property("Draw Mode", False)  # ty: ignore[invalid-type-form]
    show_variant_column: _column_property("Variant", False)  # ty: ignore[invalid-type-form]
    show_share_column: _column_property("Share", False)  # ty: ignore[invalid-type-form]
    share_type: bpy.props.EnumProperty(name="Share", items=[("BAR", "Bar", ""), ("RING", "Ring", "")])  # ty: ignore[invalid-type-form]
    show_swatch_column: _column_property("Swatch", False)  # ty: ignore[invalid-type-form]
    show_menu_column: _column_property("Menu", False)  # ty: ignore[invalid-type-form]
    show_disclosure: bpy.props.BoolProperty(name="Disclosure Triangles", default=True)  # ty: ignore[invalid-type-form]
    column_divider: bpy.props.EnumProperty(  # ty: ignore[invalid-type-form]
        name="Column Dividers",
        items=[
            ("NONE", "None", "No divider"),
            ("GLYPH", "│", "A box-drawing line character in a narrow cell"),
            ("PIPE", "|", "A plain vertical bar character in a narrow cell"),
            ("LINE", "LINE", "separator(type='LINE') in a narrow cell"),
            ("BOX", "Box", "Each cell inside a box()"),
            (
                "BUTTON",
                "Button",
                "A disabled button squeezed to scale_x 0.2, as Collection Manager draws its separators",
            ),
            ("THIN_BUTTON", "Thin Button", "A button of a fixed width (Divider Width), whose frame shows as a bar"),
        ],
        default="THIN_BUTTON",
    )
    is_divider_bright: bpy.props.BoolProperty(  # ty: ignore[invalid-type-form]
        name="Enabled",
        description="Draw the thin button enabled, so its frame is brighter; a click on it does nothing",
        default=True,
    )
    row_divider: bpy.props.EnumProperty(  # ty: ignore[invalid-type-form]
        name="Row Dividers",
        items=[
            ("NONE", "None", "No divider"),
            ("THIN_BUTTON", "Thin Button", "A full-width button squeezed to Row Divider Height under the contents"),
            ("LINE", "LINE", "separator(type='LINE') under the contents"),
        ],
        default="THIN_BUTTON",
    )
    row_divider_position: bpy.props.EnumProperty(  # ty: ignore[invalid-type-form]
        name="Position",
        items=[
            ("BOTTOM", "Bottom", "A line at the bottom of each row"),
            ("TOP", "Top", "A line at the top of each row"),
            ("BOTH", "Both", "A line at the top and the bottom of each row, each half the height"),
        ],
        default="TOP",
    )
    row_divider_height: bpy.props.FloatProperty(name="Row Divider Height", default=0.075, min=0.02, max=0.5)  # ty: ignore[invalid-type-form]
    divider_width_units: bpy.props.FloatProperty(name="Divider Width", default=0.05, min=0.05, max=1.5)  # ty: ignore[invalid-type-form]
    name_factor: bpy.props.FloatProperty(name="Name Column", default=0.5, min=0.2, max=0.9)  # ty: ignore[invalid-type-form]
    unload_payloads: bpy.props.BoolProperty(name="Unload Payloads", update=_reopen_stage)  # ty: ignore[invalid-type-form]


def _settings(context: Any) -> Any:
    return getattr(context.window_manager, SETTINGS_PROPERTY)


class ColumnDivider(bpy.types.Operator):
    """A column divider: a button that's never enabled."""

    bl_idname = "uilist_demo.column_divider"
    bl_label = ""
    bl_options = {"INTERNAL"}

    @override
    def execute(self, context: Any) -> set[OperatorReturnItems]:
        return {"CANCELLED"}


class ToggleRow(bpy.types.Operator):
    """Expand or collapse the row's prim."""

    bl_idname = "uilist_demo.toggle_row"
    bl_label = "Toggle Row"
    bl_options = {"INTERNAL"}

    prim_index: bpy.props.IntProperty()  # ty: ignore[invalid-type-form]

    @override
    def execute(self, context: Any) -> set[OperatorReturnItems]:
        prims = demo_prim_rows.DemoRowsState.prims
        if not 0 <= self.prim_index < len(prims):
            return {"CANCELLED"}
        path = prims[self.prim_index].path
        RowContentsState.collapsed_paths.symmetric_difference_update({path})
        _fill_visible_rows(context)
        return {"FINISHED"}


class CopyPrimPath(bpy.types.Operator):
    """Copy the row's prim path to the clipboard."""

    bl_idname = "uilist_demo.copy_prim_path"
    bl_label = "Copy Prim Path"
    bl_options = {"INTERNAL"}

    prim_index: bpy.props.IntProperty()  # ty: ignore[invalid-type-form]

    @override
    def execute(self, context: Any) -> set[OperatorReturnItems]:
        prims = demo_prim_rows.DemoRowsState.prims
        if 0 <= self.prim_index < len(prims):
            context.window_manager.clipboard = str(prims[self.prim_index].path)
        return {"FINISHED"}


class SelectParentRow(bpy.types.Operator):
    """Make the row's parent the active row."""

    bl_idname = "uilist_demo.select_parent_row"
    bl_label = "Select Parent"
    bl_options = {"INTERNAL"}

    prim_index: bpy.props.IntProperty()  # ty: ignore[invalid-type-form]

    @override
    def execute(self, context: Any) -> set[OperatorReturnItems]:
        prims = demo_prim_rows.DemoRowsState.prims
        if not 0 <= self.prim_index < len(prims):
            return {"CANCELLED"}
        parent_path = prims[self.prim_index].path.GetParentPath()
        properties = demo_prim_rows.rows_properties(context)
        for row_index, row_item in enumerate(properties.rows):
            prim = demo_prim_rows.demo_prim(row_item)
            if prim is not None and prim.path == parent_path:
                properties.active_row_index = row_index
        return {"FINISHED"}


class RowMenu(bpy.types.Menu):
    """A row's menu: the row comes from the context its button set."""

    bl_idname = "UILIST_DEMO_MT_row"
    bl_label = "Prim"

    @override
    def draw(self, context: Any) -> None:
        layout: Any = self.layout
        row_item: Any = getattr(context, ROW_CONTEXT_MEMBER, None)
        prim = demo_prim_rows.demo_prim(row_item) if row_item is not None else None
        if prim is None:
            layout.label(text="No row in the context")
            return
        layout.label(text=str(prim.path))
        layout.operator(CopyPrimPath.bl_idname, icon="COPYDOWN").prim_index = row_item.prim_index
        layout.operator(SelectParentRow.bl_idname, icon="FILE_PARENT").prim_index = row_item.prim_index


def _name_icon(settings: Any, prim: demo_prim_rows.DemoPrim) -> str:
    if settings.name_icon == "KIND" and prim.model_kind in MODEL_KIND_ICONS:
        return MODEL_KIND_ICONS[prim.model_kind]
    if settings.name_icon in {"TYPE", "KIND"}:
        if not prim.type_name:
            return "OUTLINER_DATA_EMPTY"
        return (
            "LIGHT"
            if prim.type_name.endswith("Light")
            else "OUTLINER_OB_MESH"
            if prim.type_name == "Mesh"
            else "OBJECT_DATA"
        )
    return "NONE"


def _fixed_width(layout: Any, width_units: float) -> Any:
    cell = layout.row(align=True)
    cell.ui_units_x = width_units
    cell.alignment = "CENTER"  # a cell inherits RIGHT, under which a label shrinks to its text
    return cell


def _draw_divider(layout: Any, settings: Any) -> None:
    """The divider before a column, in a narrow cell of its own."""
    divider = settings.column_divider
    if divider in {"NONE", "BOX"}:
        return
    if divider == "BUTTON":
        # Collection Manager's add_vertical_separator_line: only a squeezed button's frame shows, as a thin bar.
        holder = layout.row()  # not aligned, so the bar's button doesn't join the buttons beside it
        for scale_x in (0.1, 0.2, 0.1):
            part = holder.row()
            part.scale_x = scale_x
            if scale_x == 0.2:
                part.enabled = False
                part.operator(ColumnDivider.bl_idname, text="", icon="BLANK1")
            else:
                part.label()  # padding on each side
        return
    if divider == "THIN_BUTTON":
        cell = layout.row()
        cell.ui_units_x = settings.divider_width_units
        cell.enabled = settings.is_divider_bright  # a disabled button's frame is fainter
        cell.operator(ColumnDivider.bl_idname, text="", icon="BLANK1")
        return
    cell = _fixed_width(layout, settings.divider_width_units)
    if divider == "LINE":
        cell.separator(type="LINE")
    else:
        cell.label(text="│" if divider == "GLYPH" else "|")


def _cell(layout: Any, width_units: float, settings: Any) -> Any:
    """A column's cell, of a fixed width, inside a box when the dividers are boxes."""
    cell = _fixed_width(layout, width_units)
    return cell.box().row(align=True) if settings.column_divider == "BOX" else cell


def _draw_cell(layout: Any, column: str, settings: Any, item: Any, prim: demo_prim_rows.DemoPrim) -> None:
    state = prim_state(prim)
    if column == "show_glyph_column":
        layout.label(text=PRIM_STATES[state][1] if state else "")
    elif column == "show_dot_column":
        if state:
            layout.template_node_socket(color=PRIM_STATES[state][2])
        else:
            layout.label(text="", icon="BLANK1")
    elif column == "show_icon_column":
        layout.label(text="", icon=PRIM_STATES[state][3] if state else "BLANK1")
    elif column == "show_shape_column":
        if state:
            layout.label(text="", icon_value=_shape_icon_id(state))
        else:
            layout.label(text="", icon="BLANK1")
    elif column == "show_eye_column":
        eye = "HIDE_OFF" if item.is_visible else "HIDE_ON"
        layout.prop(item, "is_visible", text="", icon=eye, emboss=False)
    elif column == "show_active_column":
        layout.prop(item, "is_active_toggle", text="")
    elif column == "show_draw_column":
        layout.prop(item, "draw_mode", text="")
    elif column == "show_variant_column":
        if prim.has_variants:
            layout.prop(item, "variant", text="")
        else:
            layout.active = False
            layout.label(text="—")  # an empty label would collapse, and shift the columns after it
    elif column == "show_share_column":
        prim_count = max(len(demo_prim_rows.DemoRowsState.prims), 1)
        share = RowContentsState.descendant_counts.get(prim.path, 0) / prim_count
        layout.progress(factor=share, type=settings.share_type, text=f"{share:.0%}")
    elif column == "show_swatch_column":
        layout.prop(item, "state_color", text="")
    elif column == "show_menu_column":
        layout.context_pointer_set(ROW_CONTEXT_MEMBER, item)
        layout.menu(RowMenu.bl_idname, text="", icon="DOWNARROW_HLT")


class RowContentsList(bpy.types.UIList):
    """Draws the name, then each column that's on, each of a fixed width."""

    bl_idname = "UILIST_DEMO_UL_row_contents"

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
        settings = _settings(context)
        split = _row_contents(layout, settings).split(factor=settings.name_factor)
        name_row = split.row(align=True)
        if settings.indentation == "GLYPHS":
            for glyph in RowContentsState.guide_glyphs_by_path.get(prim.path, []):
                cell = _fixed_width(name_row, 1.0)
                if glyph:
                    cell.label(text=glyph)
                else:
                    cell.label(text="", icon="BLANK1")  # an empty label would collapse
        else:
            for _ in range(prim.depth):
                name_row.separator(factor=2.0, type="LINE" if settings.indentation == "LINE" else "AUTO")
        if settings.show_disclosure:
            if prim.path in RowContentsState.parent_paths:
                is_collapsed = prim.path in RowContentsState.collapsed_paths
                triangle = "DISCLOSURE_TRI_RIGHT" if is_collapsed else "DISCLOSURE_TRI_DOWN"
                name_row.operator(
                    ToggleRow.bl_idname, text="", icon=triangle, emboss=False
                ).prim_index = item.prim_index
            else:
                name_row.label(text="", icon="BLANK1")
        state = prim_state(prim)
        if settings.name_icon == "LARGE" and state:
            name_row.template_icon(icon_value=_shape_icon_id(state), scale=1.5)
            name_row.label(text=prim.name)
        else:
            name_row.label(text=prim.name, icon=_name_icon(settings, prim))
        columns = split.row(align=True)
        columns.alignment = "RIGHT"
        for column, _header, width_units in COLUMNS:
            if getattr(settings, column):
                _draw_divider(columns, settings)
                _draw_cell(_cell(columns, width_units, settings), column, settings, item, prim)


def _row_contents(layout: Any, settings: Any) -> Any:
    """The layout a row's contents go in: the row itself, or the top of it, above a divider line."""
    divider = settings.row_divider
    if divider == "NONE":
        return layout
    positions = {"BOTTOM": ("BOTTOM",), "TOP": ("TOP",), "BOTH": ("TOP", "BOTTOM")}[settings.row_divider_position]
    line_height = settings.row_divider_height / len(positions)
    rows = layout.column(align=True)
    if "TOP" in positions:
        _draw_row_line(rows, divider, line_height, settings)
    contents = rows.row(align=True)
    contents.scale_y = 1.0 - settings.row_divider_height  # so the contents and the lines keep one row's height
    if "BOTTOM" in positions:
        _draw_row_line(rows, divider, line_height, settings)
    return contents


def _draw_row_line(layout: Any, divider: str, line_height: float, settings: Any) -> None:
    if divider == "THIN_BUTTON":
        line = layout.row()
        line.scale_y = line_height
        line.enabled = settings.is_divider_bright
        line.operator(ColumnDivider.bl_idname, text="", icon="NONE")
    else:
        layout.separator(factor=line_height, type="LINE")


def _draw_header(layout: Any, settings: Any) -> None:
    # A row above the list, split as each row is, so its labels sit over the columns.
    split = layout.split(factor=settings.name_factor)
    split.label(text="Name")
    columns = split.row(align=True)
    columns.alignment = "RIGHT"
    for column, header, width_units in COLUMNS:
        if getattr(settings, column):
            _draw_divider(columns, settings)
            cell = _cell(columns, width_units, settings)
            cell.label(text=header, icon=COLUMN_HEADER_ICONS.get(column, "NONE"))


def _draw_legend(layout: Any) -> None:
    legend = layout.box().column(align=True)
    legend.label(text="States: glyph, dot, icon, shape")
    for state, (label, glyph, color, fixed_icon, _shape) in PRIM_STATES.items():
        row = legend.row(align=True)
        _fixed_width(row, 1.0).label(text=glyph)
        _fixed_width(row, 1.0).template_node_socket(color=color)
        _fixed_width(row, 1.0).label(text="", icon=fixed_icon)
        _fixed_width(row, 1.0).label(text="", icon_value=_shape_icon_id(state))
        row.label(text=label)


class RowContentsPanel(bpy.types.Panel):
    """The header and list, the legend, then the column toggles."""

    bl_idname = "VIEW3D_PT_uilist_demo_row_contents"
    bl_label = "3. A Row's Contents"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = demo_prim_rows.CATEGORY

    @override
    def draw(self, context: Any) -> None:
        layout: Any = self.layout
        settings = _settings(context)
        properties = demo_prim_rows.rows_properties(context)
        _draw_header(layout, settings)
        layout.template_list(
            RowContentsList.bl_idname,
            "",
            properties,
            "rows",
            properties,
            "active_row_index",
            item_dyntip_propname="tooltip",
            rows=VISIBLE_ROW_COUNT,
            maxrows=VISIBLE_ROW_COUNT,
        )
        layout.prop(settings, "unload_payloads")
        _draw_legend(layout)
        options = layout.box().column()
        options.label(text="Name")
        options.row().prop(settings, "name_icon", expand=True)
        options.row().prop(settings, "indentation", expand=True)
        options.prop(settings, "show_disclosure")
        options.label(text="Column dividers")
        options.row().prop(settings, "column_divider", expand=True)
        row = options.row()
        row.active = settings.column_divider not in {"NONE", "BOX", "BUTTON"}
        row.prop(settings, "divider_width_units", slider=True)
        row = options.row()
        row.active = settings.column_divider == "THIN_BUTTON"
        row.prop(settings, "is_divider_bright")
        options.label(text="Row dividers (contents shrink by the line's height)")
        options.row().prop(settings, "row_divider", expand=True)
        row = options.row()
        row.active = settings.row_divider != "NONE"
        row.prop(settings, "row_divider_height", slider=True)
        row = options.row()
        row.active = settings.row_divider != "NONE"
        row.prop(settings, "row_divider_position", expand=True)
        options.prop(settings, "name_factor", slider=True)
        options.label(text="Columns")
        grid = options.grid_flow(columns=2, even_columns=True, align=True)
        for column, _header, _width_units in COLUMNS:
            grid.prop(settings, column, toggle=True)
        row = options.row()
        row.active = settings.show_share_column
        row.prop(settings, "share_type", expand=True)


CLASSES = (
    RowContentsSettings,
    ColumnDivider,
    ToggleRow,
    CopyPrimPath,
    SelectParentRow,
    RowMenu,
    RowContentsList,
    RowContentsPanel,
)


def main() -> None:
    """Register the demo, its icons, and its rows' properties, and fill its rows."""
    demo_prim_rows.register_rows()
    _add_row_properties()
    _forget_stage_caches()
    _create_previews()
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    setattr(bpy.types.WindowManager, SETTINGS_PROPERTY, bpy.props.PointerProperty(type=RowContentsSettings))


if __name__ == "__main__":
    main()
