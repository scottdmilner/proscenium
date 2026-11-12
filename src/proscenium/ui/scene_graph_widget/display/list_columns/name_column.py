"""The name column, the tree itself: each row's indent and guide lines, chevron, icon, name, and badges.

Instancing marks a row here: an instance's icon in the instancing color, its proxies' icons and chevrons fainter, and
the guide lines under an instance dashed in those colors.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pxr import Kind, Sdf

from ...prim_tree import prim_descriptions
from .. import badge_icons, tinted_icons, widget_colors, widget_operators
from .column_layout import fixed_width

if TYPE_CHECKING:
    import bpy
    from bpy.stub_internal.rna_enums import IconItems

    from ...prim_tree import PrimTree, RowDetails
    from ..widget_properties import SceneGraphViewProperties

# Widths in UI units. A level holds its parent's guide line, under the center of that parent's chevron.
LEVEL_UNITS = 0.6
CHEVRON_UNITS = 0.6  # narrower than an icon button's 1.0, which leaves wide margins around the chevron
GUIDE_LINE_UNITS = 0.05
ROW_ICON_UNITS = 0.8  # the cell of the row's icon: its kind's, or else its type's
NAME_GAP_FACTOR = 1.0  # the separator between the icon and the name
BADGE_UNITS = 0.8  # each badge's cell, after the name
BADGE_GAP_UNITS = 0.2  # between the instance badge and the arcs' block of badges
# The name cell's natural width, wider than any row, so each row is too narrow for what it holds. A row with width to
# spare grows every item in proportion to its natural width, which differs from row to row, so the guide lines would
# drift apart; a row short of width keeps each item narrower than a unit at its width and shrinks the rest, here only
# the name.
NAME_CELL_UNITS = 1000.0

TYPE_ICONS: dict[str, IconItems] = {
    "Xform": "EMPTY_AXIS",
    "Scope": "FILE_FOLDER",
    "Mesh": "MESH_DATA",
    "Camera": "CAMERA_DATA",
    "Material": "MATERIAL",
    "Shader": "NODE",
    "PointInstancer": "OUTLINER_OB_POINTCLOUD",
    "BasisCurves": "CURVE_DATA",
}


# Each model kind's icon, most derived first: an assembly is also a group. A kind registered as deriving from one of
# these takes its icon; any other kind takes OTHER_KIND_ICON.
KIND_ICONS: tuple[tuple[str, IconItems], ...] = (
    (Kind.Tokens.assembly, "OUTLINER_OB_GROUP_INSTANCE"),
    (Kind.Tokens.group, "GROUP"),
    (Kind.Tokens.component, "MESH_CUBE"),
    (Kind.Tokens.subcomponent, "MOD_EXPLODE"),
)
OTHER_KIND_ICON: IconItems = "BOOKMARKS"
# The disclosure triangle's icons, collapsed and expanded: chevrons, as the Outliner's.
COLLAPSED_ICON: IconItems = "RIGHTARROW"
EXPANDED_ICON: IconItems = "DOWNARROW_HLT"


def _type_icon(type_name: str) -> IconItems:
    if type_name.endswith("Light"):
        return "LIGHT"
    return TYPE_ICONS.get(type_name, "DOT")


def row_icon_names() -> list[str]:
    """Every icon a row can show: each type's, the lights', the fallback type icon, each kind's, and the chevrons."""
    names = {*TYPE_ICONS.values(), "LIGHT", "DOT", OTHER_KIND_ICON, COLLAPSED_ICON, EXPANDED_ICON}
    names.update(icon for _, icon in KIND_ICONS)
    return sorted(names)


def _row_icon(details: RowDetails) -> IconItems:
    """A row's icon: its prim's kind's where it has a kind, or else its type's."""
    if not details.model_kind:
        return _type_icon(details.type_name)
    return next((icon for kind, icon in KIND_ICONS if Kind.Registry.IsA(details.model_kind, kind)), OTHER_KIND_ICON)


def _draw_guide_level(layout: bpy.types.UILayout) -> None:
    """One indent level, with the vertical line that runs down from its open parent's chevron.

    Every ancestor of a visible row is expanded, so each level of a row's indent holds a line, and the lines join
    from row to row into one under each open chevron. A layout can't draw a vertical line, so it is a disabled button
    squeezed to a hairline: disabled, it draws faint, and a click on it selects the row.
    """
    level = fixed_width(layout, LEVEL_UNITS)
    before_line = (CHEVRON_UNITS - GUIDE_LINE_UNITS) / 2
    fixed_width(level, before_line).label(text="")
    line = fixed_width(level, GUIDE_LINE_UNITS)
    line.enabled = False
    line.operator(widget_operators.SceneGraphGuideLine.bl_idname, text="", icon="BLANK1")
    # The parts have fixed widths that fill the level, so the line keeps its place whatever the row's alignment.
    fixed_width(level, LEVEL_UNITS - before_line - GUIDE_LINE_UNITS).label(text="")


def _find_row_instance(details: RowDetails) -> Sdf.Path | None:
    """Find the instance whose proxies' lines a row's indent draws.

    The outermost instance above an instance proxy, even a proxy that's an instance itself; else the row's own prim,
    if it's an instance.
    """
    return details.outermost_instance_path or (details.path if details.is_instance else None)


def _draw_dashed_guide_level(layout: bpy.types.UILayout, color: tuple[float, float, float]) -> None:
    # A label, so a click on it selects its row, as on the plain line, whose disabled button does nothing.
    icon_value = tinted_icons.dashed_line_icon_id(color)
    fixed_width(layout, LEVEL_UNITS).label(text="", icon_value=icon_value)


def _draw_guide_levels(layout: bpy.types.UILayout, depth: int, details: RowDetails) -> None:
    """A row's indent: a level per ancestor, each holding its guide line."""
    # The levels from an instance's own down hold its proxies' lines, dashed: the instance's own in its color, and
    # those under the proxies below it fainter, as their icons. An instance's own row has none.
    instance_path = _find_row_instance(details)
    instance_depth = depth - (details.path.pathElementCount - instance_path.pathElementCount if instance_path else 0)
    for level_depth in range(depth):
        if instance_path is not None and level_depth >= instance_depth:
            is_instance_level = level_depth == instance_depth
            color = widget_colors.instance_color() if is_instance_level else widget_colors.instance_proxy_color()
            _draw_dashed_guide_level(layout, color)
        else:
            _draw_guide_level(layout)


def _draw_chevron(
    layout: bpy.types.UILayout, view_name: str, row_index: int, details: RowDetails, is_expanded: bool
) -> None:
    """The row's disclosure triangle, or a blank of its width on a leaf."""
    chevron = fixed_width(layout, CHEVRON_UNITS)
    if not details.has_children:
        chevron.label(text="", icon="BLANK1")
        return
    disclosure = EXPANDED_ICON if is_expanded else COLLAPSED_ICON
    # Inside an instance, the chevron is a proxy's, in the color of its icon and the lines beside it.
    proxy_color = widget_colors.instance_proxy_color()
    tinted = tinted_icons.icon_id(disclosure, proxy_color) if details.is_instance_proxy else None
    toggle_idname = widget_operators.SceneGraphToggleRow.bl_idname
    if tinted is None:
        toggle = chevron.operator(toggle_idname, text="", icon=disclosure, emboss=False)
    else:
        toggle = chevron.operator(toggle_idname, text="", icon_value=tinted, emboss=False)
    toggle.view_name = view_name
    toggle.row_index = row_index


def _draw_row_icon(layout: bpy.types.UILayout, details: RowDetails) -> None:
    """The row's icon, an instance's in its color and a proxy's fainter, where it's one of Blender's.

    An invalid model's stays Blender's, so the layout's alert draws it red: the warning comes before the instancing.
    """
    icon = _row_icon(details)
    if (details.is_instance or details.is_instance_proxy) and not details.is_invalid_model:
        if details.is_instance_proxy:
            color = widget_colors.instance_proxy_color()
        else:
            color = widget_colors.instance_color()
        icon_value = tinted_icons.icon_id(icon, color)
        if icon_value is not None:
            layout.label(text="", icon_value=icon_value)
            return
    layout.label(text="", icon=icon)


def _draw_badges(layout: bpy.types.UILayout, details: RowDetails) -> None:
    """A badge for each composition arc on the prim, and for an instance, after its name."""
    # Labels, so a click on one selects the row and the row's tooltip covers them; each icon draws its piece of the
    # block they sit on, so side by side they make one. The instance badge, which marks no arc, stands on its own,
    # and the arcs' badges share a block after a gap.
    row_badges = prim_descriptions.row_badges(details)
    arc_badges = [badge for badge in row_badges if badge is not prim_descriptions.Badge.INSTANCE]
    instance_badges = [badge for badge in row_badges if badge is prim_descriptions.Badge.INSTANCE]
    # Each cell sits in the name's row itself: the row is short of width, so it keeps each cell narrower than a unit
    # at its width, where a row of the cells, wider than a unit, would shrink with the name.
    for block_index, block in enumerate(block for block in (instance_badges, arc_badges) if block):
        if block_index:
            fixed_width(layout, BADGE_GAP_UNITS).label(text="")
        for badge_index, badge in enumerate(block):
            place = badge_icons.BadgePlace.at(badge_index, len(block))
            is_greyed = not prim_descriptions.is_badge_in_effect(details, badge)
            icon_value = badge_icons.icon_id(badge, place, is_greyed)
            fixed_width(layout, BADGE_UNITS).label(text="", icon_value=icon_value)


def draw_name_cell(
    layout: bpy.types.UILayout,
    properties: SceneGraphViewProperties,
    tree: PrimTree,
    row_index: int,
    details: RowDetails,
) -> None:
    """Draw a row's name cell, from its details: its indent and guide lines, chevron, icon, name, and badges."""
    tree_row = tree.rows[row_index]
    row = layout.row(align=True)
    _draw_guide_levels(row, tree_row.depth, details)
    content = row.row(align=True)  # dimmed apart from the guide lines, so each line has one look down its length
    # Inactive prims and rows that only hold search matches draw greyed.
    content.active = details.is_active and tree.is_match(tree_row)
    _draw_chevron(content, properties.name, row_index, details, tree.is_expanded(tree_row))
    # The icon in a cell of its own, and a separator before the name, set a narrower gap than a label's icon has.
    named = content.row(align=True)
    named.alert = details.is_orphaned_over  # red: nothing defines it, as a typo in an over's path leaves it
    icon = fixed_width(named, ROW_ICON_UNITS)
    icon.alert = details.is_invalid_model  # the kind's icon red, as the kind column's text is
    _draw_row_icon(icon, details)
    named.separator(factor=NAME_GAP_FACTOR)
    # The name fills what its badges leave (NAME_CELL_UNITS). Left-aligned, so the badges hugged its text, a name too
    # long for its column would squeeze every cell in the row, indent and icon too.
    name_and_badges = named.row(align=True)
    name_cell = fixed_width(name_and_badges, NAME_CELL_UNITS)
    name_cell.label(text=prim_descriptions.row_name(details, properties.shown_name == "DISPLAY_NAME"))
    _draw_badges(name_and_badges, details)


def draw_name_header(layout: bpy.types.UILayout, properties: SceneGraphViewProperties) -> None:
    """Draw the name column's header: a menu of which name the rows show."""
    name_header = layout.row()
    name_header.alignment = "LEFT"
    # A menu with an arrow after its text, so the header reads as clickable; an unembossed button shows no hover.
    # Under PULLDOWN_MENU the menu draws no arrow of its own, which would be dimmer than the text, so the arrow is a
    # character of the text, in its color.
    name_header.emboss = "PULLDOWN_MENU"
    title = "Display Name" if properties.shown_name == "DISPLAY_NAME" else "Prim"
    name_header.prop_menu_enum(properties, "shown_name", text=f"    {title} ⌄")
