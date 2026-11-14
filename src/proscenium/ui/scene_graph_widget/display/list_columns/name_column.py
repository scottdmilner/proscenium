"""The name column, the tree itself: each row's indent and guide lines, chevron, icon, name, and badges.

Instancing marks a row here: an instance's icon in the instancing color, its proxies' icons and chevrons fainter, and
the guide lines under an instance dashed in those colors.
"""

from __future__ import annotations

import functools
from typing import TYPE_CHECKING

import numpy as np
from pxr import Kind, Sdf

from ....columned_list.column_layout import fixed_width
from ....widget_model import prim_detail_text
from ....widget_resources import badge_icons, tinted_icons, tree_rows
from ...prim_tree import prim_descriptions
from .. import instancing_colors, scene_graph_operators

if TYPE_CHECKING:
    import bpy
    from bpy.stub_internal.rna_enums import IconItems

    from ....widget_model.prim_details import RowDetails
    from ...prim_tree import PrimTree
    from ..scene_graph_properties import SceneGraphViewProperties

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
# The dashed guide line's mask, drawn as a tinted icon. A label draws its icon 16 points tall in a 20-point row,
# whatever the icon's pixels, so a line drawn into an icon can't reach its row's edges. The line is dashed, and the
# dashes are timed so the gap a row leaves at its edges is one of the gaps between them: down a column of rows, the
# dashes run evenly.
DASHED_LINE_SIZE_PIXELS = 32
# The line's pixel columns, left of the icon's center: a label in a guide level draws its icon from the level's left,
# so these put the line where the level's own line is, under the center of the parent's chevron.
DASHED_LINE_COLUMNS = (8, 9)
# The rows left blank, bottom first: dashes of a quarter of the row's 20 points, and gaps as long, two to an icon,
# with the 2 points the icon leaves at each edge of its row making up the gap there.
DASHED_LINE_GAP_ROWS = (*range(2), *range(12, 22))


def _type_icon(type_name: str) -> IconItems:
    if type_name.endswith("Light"):
        return "LIGHT"
    return TYPE_ICONS.get(type_name, "DOT")


def row_icon_names() -> list[str]:
    """Every icon a row can show: each type's, the lights', the fallback type icon, each kind's, and the chevrons."""
    names = {*TYPE_ICONS.values(), "LIGHT", "DOT", OTHER_KIND_ICON, tree_rows.COLLAPSED_ICON, tree_rows.EXPANDED_ICON}
    names.update(icon for _, icon in KIND_ICONS)
    return sorted(names)


def _row_icon(details: RowDetails) -> IconItems:
    """A row's icon: its prim's kind's where it has a kind, or else its type's."""
    if not details.model_kind:
        return _type_icon(details.type_name)
    return next((icon for kind, icon in KIND_ICONS if Kind.Registry.IsA(details.model_kind, kind)), OTHER_KIND_ICON)


def _find_row_instance(details: RowDetails) -> Sdf.Path | None:
    """Find the instance whose proxies' lines a row's indent draws.

    The outermost instance above an instance proxy, even a proxy that's an instance itself; else the row's own prim,
    if it's an instance.
    """
    return details.outermost_instance_path or (details.path if details.is_instance else None)


@functools.cache
def _dashed_line_mask() -> np.ndarray:
    """The dashed guide line's mask, as Blender's icons' are."""
    coverages = np.zeros((DASHED_LINE_SIZE_PIXELS, DASHED_LINE_SIZE_PIXELS), dtype=np.uint8)
    coverages[:, list(DASHED_LINE_COLUMNS)] = 255
    coverages[list(DASHED_LINE_GAP_ROWS), :] = 0
    return coverages


def _draw_dashed_guide_level(layout: bpy.types.UILayout, color: tuple[float, float, float]) -> None:
    # A label, so a click on it selects its row, as on the plain line, whose disabled button does nothing.
    icon_value = tinted_icons.mask_icon_id("dashed", _dashed_line_mask(), color)
    fixed_width(layout, tree_rows.LEVEL_UNITS).label(text="", icon_value=icon_value)


def _draw_guide_levels(layout: bpy.types.UILayout, depth: int, details: RowDetails) -> None:
    """A row's indent: a level per ancestor, each holding its guide line."""
    # The levels from an instance's own down hold its proxies' lines, dashed: the instance's own in its color, and
    # those under the proxies below it fainter, as their icons. An instance's own row has none.
    instance_path = _find_row_instance(details)
    instance_depth = depth - (details.path.pathElementCount - instance_path.pathElementCount if instance_path else 0)
    for level_depth in range(depth):
        if instance_path is not None and level_depth >= instance_depth:
            is_instance_level = level_depth == instance_depth
            color = (
                instancing_colors.instance_color() if is_instance_level else instancing_colors.instance_proxy_color()
            )
            _draw_dashed_guide_level(layout, color)
        else:
            tree_rows.draw_guide_level(layout)


def _draw_chevron(
    layout: bpy.types.UILayout, view_name: str, row_index: int, details: RowDetails, is_expanded: bool
) -> None:
    """The row's disclosure triangle, or a blank of its width on a leaf."""
    chevron = fixed_width(layout, tree_rows.CHEVRON_UNITS)
    if not details.has_children:
        chevron.label(text="", icon="BLANK1")
        return
    disclosure = tree_rows.EXPANDED_ICON if is_expanded else tree_rows.COLLAPSED_ICON
    # Inside an instance, the chevron is a proxy's, in the color of its icon and the lines beside it.
    proxy_color = instancing_colors.instance_proxy_color()
    tinted = tinted_icons.icon_id(disclosure, proxy_color) if details.is_instance_proxy else None
    toggle_idname = scene_graph_operators.SceneGraphToggleRow.bl_idname
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
            color = instancing_colors.instance_proxy_color()
        else:
            color = instancing_colors.instance_color()
        icon_value = tinted_icons.icon_id(icon, color)
        if icon_value is not None:
            layout.label(text="", icon_value=icon_value)
            return
    layout.label(text="", icon=icon)


def _draw_badges(layout: bpy.types.UILayout, details: RowDetails) -> None:
    """A badge for each composition arc on the prim, and for an instance, after its name."""
    # The instance badge, which marks no arc, stands on its own, and the arcs' badges share a block after a gap.
    instance_badges: list[tree_rows.Badge] = (
        [(badge_icons.INSTANCE_BADGE_LOOK, prim_detail_text.is_instance_badge_in_effect(details))]
        if prim_detail_text.has_instance_badge(details)
        else []
    )
    arc_badges: list[tree_rows.Badge] = [
        (badge_icons.ARC_LOOKS[arc], prim_detail_text.is_arc_in_effect(details, arc))
        for arc in prim_detail_text.row_arcs(details)
    ]
    tree_rows.draw_badge_blocks(layout, (instance_badges, arc_badges))


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
    icon = fixed_width(named, tree_rows.ROW_ICON_UNITS)
    icon.alert = details.is_invalid_model  # the kind's icon red, as the kind column's text is
    _draw_row_icon(icon, details)
    named.separator(factor=tree_rows.NAME_GAP_FACTOR)
    # The name fills what its badges leave (tree_rows.NAME_CELL_UNITS). Left-aligned, so the badges hugged its text, a
    # name too long for its column would squeeze every cell in the row, indent and icon too.
    name_and_badges = named.row(align=True)
    name_cell = fixed_width(name_and_badges, tree_rows.NAME_CELL_UNITS)
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
