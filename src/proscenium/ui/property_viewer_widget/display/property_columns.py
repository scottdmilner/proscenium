"""The property list's columns: the name column, and the Value, Type, and Copy Path columns after it.

The name column draws a row as a tree's: a target's row is indented under its property's, with the guide line from
its chevron; then a chevron on a property with targets, the row's icon, its name, and its keyframe icon. An unauthored
property, which shows its schema's fallback, draws dimmed, and a target the stage has nothing at draws red.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple

from ...columned_list import column_layout
from ...columned_list.column_layout import fixed_width
from ...widget_resources import clipboard_operators, keyframe_icons, tree_rows
from ..property_list import property_descriptions
from . import property_viewer_operators, property_viewer_views

if TYPE_CHECKING:
    import bpy
    from bpy.stub_internal.rna_enums import IconItems

    from ..property_list import PropertyDetails, PropertyList, PropertyRow
    from .property_viewer_properties import PropertyViewerViewProperties


class PropertyCell(NamedTuple):
    """What a column's cell draws from: the row, its property's details, and where the row is, for its buttons."""

    row: PropertyRow
    details: PropertyDetails
    view_name: str
    row_index: int


# The keyframe icon's fill for each mark of an animated value: Blender's keyed color for a key at the time code, and
# its animated color between keys.
KEYFRAME_FILLS = {
    property_descriptions.AnimationMark.KEY: keyframe_icons.KeyframeFill.KEYED,
    property_descriptions.AnimationMark.BETWEEN_KEYS: keyframe_icons.KeyframeFill.ANIMATED,
}
TARGET_ICON: IconItems = "FORWARD"
RELATIONSHIP_ICON: IconItems = "LINKED"
CONNECTED_ICON: IconItems = "NODETREE"  # an attribute with connections, as a shader's inputs and outputs have
PRIMVAR_ICON: IconItems = "GROUP_VCOL"
XFORM_OP_ICON: IconItems = "ORIENTATION_LOCAL"
ATTRIBUTE_ICON: IconItems = "DOT"
XFORM_OP_PREFIX = "xformOp"  # xformOp:<op> and xformOpOrder
JUMP_ICON: IconItems = "RESTRICT_SELECT_OFF"  # the arrow cursor, as the Outliner's selectable toggle draws it
JUMP_BUTTON_UNITS = 1.0  # an icon button's width
COPY_BUTTON_WIDTH_SCALE = 1.3  # wider than its icon, so the icon's sides stay clear of the button's edges


def row_icon(row: PropertyRow, details: PropertyDetails) -> IconItems:
    """A row's icon: a target's, or its property's: a relationship, a connected attribute, a primvar, or an op."""
    if row.is_target:
        return TARGET_ICON
    if details.is_relationship:
        return RELATIONSHIP_ICON
    if details.has_targets:
        return CONNECTED_ICON
    if details.interpolation:
        return PRIMVAR_ICON
    return XFORM_OP_ICON if details.name.startswith(XFORM_OP_PREFIX) else ATTRIBUTE_ICON


def row_keyframe_fill(row: PropertyRow, details: PropertyDetails) -> keyframe_icons.KeyframeFill | None:
    """A property row's keyframe icon's fill, for a value that's animated; a target's row has none."""
    mark = property_descriptions.animation_mark(details)
    return None if row.is_target or mark is None else KEYFRAME_FILLS[mark]


def _draw_keyframe(layout: bpy.types.UILayout, row: PropertyRow, details: PropertyDetails) -> None:
    """The row's keyframe icon after its name, in a badge's cell, for a value that's animated."""
    fill = row_keyframe_fill(row, details)
    if fill is not None:
        fixed_width(layout, tree_rows.BADGE_UNITS).label(text="", icon_value=keyframe_icons.icon_id(fill))


def _draw_chevron(
    layout: bpy.types.UILayout,
    view_name: str,
    property_list: PropertyList,
    row_index: int,
    details: PropertyDetails,
) -> None:
    """A property's disclosure triangle, or a blank of its width on a target's row or a property with no targets."""
    row = property_list.rows[row_index]
    chevron = fixed_width(layout, tree_rows.CHEVRON_UNITS)
    if row.is_target or not details.has_targets:
        chevron.label(text="", icon="BLANK1")
        return
    disclosure = tree_rows.EXPANDED_ICON if property_list.is_expanded(row.name) else tree_rows.COLLAPSED_ICON
    toggle_idname = property_viewer_operators.PropertyViewerToggleRow.bl_idname
    toggle = chevron.operator(toggle_idname, text="", icon=disclosure, emboss=False)
    toggle.view_name = view_name
    toggle.row_index = row_index


def draw_name_cell(
    layout: bpy.types.UILayout, properties: PropertyViewerViewProperties, property_list: PropertyList, row_index: int
) -> None:
    """Draw a row's name cell: a target's indent, the chevron, the icon, the name or target path, keyframe, and jump."""
    view_name = properties.name
    row = property_list.rows[row_index]
    details = property_list.row_details(row)
    if details is None:
        return
    cell = layout.row(align=True)
    if row.is_target:
        tree_rows.draw_guide_level(cell)
    content = cell.row(align=True)  # dimmed apart from the guide line, so the line has one look down its length
    content.active = row.is_target or details.is_authored  # an unauthored property shows its schema's fallback
    _draw_chevron(content, view_name, property_list, row_index, details)
    named = content.row(align=True)
    named.alert = property_descriptions.is_target_missing(details, row)
    fixed_width(named, tree_rows.ROW_ICON_UNITS).label(text="", icon=row_icon(row, details))
    named.separator(factor=tree_rows.NAME_GAP_FACTOR)
    # The name fills what its keyframe icon leaves (tree_rows.NAME_CELL_UNITS), so the icon ends at the column's edge.
    name_and_marks = named.row(align=True)
    # A target's row shows its path and jump button in the Value column, which has the room, and its name here; with
    # that column hidden, they're here.
    shows_value_column = properties.show_value_column
    row_name = property_descriptions.row_name(row, shows_target_path=not shows_value_column)
    fixed_width(name_and_marks, tree_rows.NAME_CELL_UNITS).label(text=row_name)
    _draw_keyframe(name_and_marks, row, details)
    if row.is_target and not shows_value_column:
        _draw_jump_button(name_and_marks, PropertyCell(row, details, view_name, row_index))


def _draw_jump_button(layout: bpy.types.UILayout, cell: PropertyCell) -> None:
    """A target's jump button, if the host takes jumps; disabled for a target the stage has nothing at."""
    view = property_viewer_views.find_view(cell.view_name)
    if view is None or view.on_jump_to_target is None:
        return
    # Embossed, so it reads as a button, in a fixed cell, so a narrow row squeezes the text beside it, not it.
    button = fixed_width(layout, JUMP_BUTTON_UNITS)
    button.alert = False  # the row's red marks the missing target, not the button
    button.enabled = not property_descriptions.is_target_missing(cell.details, cell.row)
    jump = button.operator(property_viewer_operators.PropertyViewerJumpToTarget.bl_idname, text="", icon=JUMP_ICON)
    jump.view_name = cell.view_name
    jump.row_index = cell.row_index


def draw_name_header(layout: bpy.types.UILayout) -> None:
    """Draw the name column's header, its title over the rows' names: past a chevron's and an icon's widths."""
    header = layout.row(align=True)
    fixed_width(header, tree_rows.CHEVRON_UNITS).label(text="")
    fixed_width(header, tree_rows.ROW_ICON_UNITS).label(text="")
    header.separator(factor=tree_rows.NAME_GAP_FACTOR)
    header.label(text="Property")


def _draw_value_cell(layout: bpy.types.UILayout, cell: PropertyCell) -> None:
    if not cell.row.is_target:
        layout.label(text=property_descriptions.row_value_text(cell.details))
        return
    # A target's row: its jump button, then its path, in red for one the stage has nothing at.
    _draw_jump_button(layout, cell)
    path = layout.row(align=True)
    path.alert = property_descriptions.is_target_missing(cell.details, cell.row)
    path.label(text=str(cell.row.target_path))


def _draw_type_cell(layout: bpy.types.UILayout, cell: PropertyCell) -> None:
    layout.label(text="" if cell.row.is_target else property_descriptions.declaration_text(cell.details))


def _draw_copy_path_cell(layout: bpy.types.UILayout, cell: PropertyCell) -> None:
    # Embossed, so it reads as a button; scaled, since a scale is what gives an icon-only button's icon room inside.
    button = layout.row(align=True)
    button.scale_x = COPY_BUTTON_WIDTH_SCALE
    copy = button.operator(clipboard_operators.CopyUsdPath.bl_idname, text="", icon="DUPLICATE")
    copy.usd_path = str(cell.row.target_path or cell.details.path)


# A share of what Type and Copy Path leave, so it stays wider than the name, which takes the rest; 7 units without a
# region's width.
VALUE_COLUMN: column_layout.Column[PropertyCell] = column_layout.Column(
    "Value", "show_value_column", _draw_value_cell, fixed_units=7.0, share_property="value_column_share"
)
TYPE_COLUMN: column_layout.Column[PropertyCell] = column_layout.Column(
    "Type", "show_type_column", _draw_type_cell, "type_column_units"
)
# Its header blank, as each row's button shows what the column holds; a button's width, so not resizable.
COPY_PATH_COLUMN: column_layout.Column[PropertyCell] = column_layout.Column(
    "Copy Path",
    "show_copy_path_column",
    _draw_copy_path_cell,
    fixed_units=COPY_BUTTON_WIDTH_SCALE,
    header_icon="BLANK1",
    alignment="CENTER",
)
# The columns after the name, in order.
COLUMNS = (VALUE_COLUMN, TYPE_COLUMN, COPY_PATH_COLUMN)
