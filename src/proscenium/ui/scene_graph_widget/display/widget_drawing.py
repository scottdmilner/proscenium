"""Drawing a scene graph view into a host's layout: the tree as a virtualized UIList, and the selected prim's details.

A host's panel calls `draw_tree` or `draw_details` from its own `draw`, so the view draws wherever the host puts
it. The UIList's collection holds empty items, one per visible row; each row's content is read from the view's tree
by its index, so only the row count crosses into RNA.
"""

from __future__ import annotations

import colorsys
from typing import Any, NamedTuple, override

import bpy
from pxr import Kind, Sdf

from ..prim_tree import prim_descriptions
from . import (
    badge_icons,
    guide_line_icons,
    tinted_icons,
    widget_keys,
    widget_operators,
    widget_properties,
    widget_views,
)


class Column(NamedTuple):
    """A column after the name: its title, and the view properties that show it and set its width."""

    title: str
    show_property: str
    units_property: str
    header_icon: str = ""  # in place of the title in the header, for a column too narrow for it
    alignment: str = "LEFT"  # its cells', in the header and the rows: RIGHT for numbers


# The columns after the name, in order.
CHILDREN_COLUMN = Column(
    "Children", "show_children_column", "children_column_units", header_icon="CON_CHILDOF", alignment="RIGHT"
)
KIND_COLUMN = Column("Kind", "show_kind_column", "kind_column_units")
TYPE_COLUMN = Column("Type", "show_type_column", "type_column_units")
COLUMNS = (CHILDREN_COLUMN, KIND_COLUMN, TYPE_COLUMN)
# The least share of a row the name column takes, in the header and in each row, by how many columns show after it:
# its share in a narrow region, where the columns are narrower than their widths.
NAME_COLUMN_FACTOR_BY_COLUMN_COUNT = {0: 0.85, 1: 0.72, 2: 0.56, 3: 0.45}
REGION_MARGIN_UNITS = 2.0  # what a region's width leaves out of a list row's: the panel's margins and the list's
# Widths in UI units. A level holds its parent's guide line, under the center of that parent's chevron.
LEVEL_UNITS = 0.6
CHEVRON_UNITS = 0.6  # narrower than an icon button's 1.0, which leaves wide margins around the chevron
GUIDE_LINE_UNITS = 0.05
ROW_ICON_UNITS = 0.8  # the cell of the row's icon: its kind's, or else its type's
NAME_GAP_FACTOR = 1.0  # the separator between the icon and the name
BADGE_UNITS = 0.8  # each badge's cell, after the name
BADGE_GAP_UNITS = 0.2  # between the instance badge and the arcs' block of badges
# How much of a row mark's color is the list's text color, the rest the instance badge's: the collection colors
# don't read on a light theme's grey rows, and the text color does in any theme, so a mix with it reads in both.
# An instance proxy's is closer to the text, fainter than its instance's, since it's shared from the prototype. An
# instance's then takes the badge's saturation back at the mix's luminance, so it reads as green as it contrasts.
INSTANCE_TEXT_WEIGHT = 0.6
INSTANCE_PROXY_TEXT_WEIGHT = 0.75
LUMINANCE_SEARCH_STEPS = 30  # bisections finding an instance's color, far finer than a color channel's 1/255
# The name cell's natural width, wider than any row, so each row is too narrow for what it holds. A row with width to
# spare grows every item in proportion to its natural width, which differs from row to row, so the guide lines would
# drift apart; a row short of width keeps each item narrower than a unit at its width and shrinks the rest, here only
# the name.
NAME_CELL_UNITS = 1000.0
# Each view's rows drawn in the current draw of its list: the list draws only the rows on screen, so fewer than the
# tree's means it scrolls, which Python can't otherwise read.
_drawn_row_counts: dict[str, int] = {}
LIST_ROWS = 16  # the list's starting height; it can be dragged taller
# What a scrolling list's scrollbar takes from its rows' width, the gap before it included: the header leaves it
# blank, so its columns stay over the rows'.
SCROLLBAR_UNITS = 0.5
SEARCH_MODE_UNITS = 6.0  # the search's match dropdown, wide enough for its longest mode, "Path contains"
SEARCH_TOGGLE_UNITS = 1.0  # each toggle after it, an icon button's width
SEARCH_TEXT_LEAST_FACTOR = 0.4  # the text field's share of the search row in a region too narrow for the rest
SETTINGS_CONTEXT_MEMBER = "proscenium_scene_graph_view"  # the view's properties, for the settings popover

TYPE_ICONS = {
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
KIND_ICONS = (
    (Kind.Tokens.assembly, "OUTLINER_OB_GROUP_INSTANCE"),
    (Kind.Tokens.group, "GROUP"),
    (Kind.Tokens.component, "MESH_CUBE"),
    (Kind.Tokens.subcomponent, "MOD_EXPLODE"),
)
OTHER_KIND_ICON = "BOOKMARKS"
# The disclosure triangle's icons, collapsed and expanded: chevrons, as the Outliner's.
COLLAPSED_ICON = "RIGHTARROW"
EXPANDED_ICON = "DOWNARROW_HLT"


def _type_icon(type_name: str) -> str:
    if type_name.endswith("Light"):
        return "LIGHT"
    return TYPE_ICONS.get(type_name, "DOT")


def row_icon_names() -> list[str]:
    """Every icon a row can show: each type's, the lights', the fallback type icon, each kind's, and the chevrons."""
    names = {*TYPE_ICONS.values(), "LIGHT", "DOT", OTHER_KIND_ICON, COLLAPSED_ICON, EXPANDED_ICON}
    names.update(icon for _, icon in KIND_ICONS)
    return sorted(names)


def _row_icon(details: Any) -> str:
    """A row's icon: its prim's kind's where it has a kind, or else its type's."""
    if not details.model_kind:
        return _type_icon(details.type_name)
    return next((icon for kind, icon in KIND_ICONS if Kind.Registry.IsA(details.model_kind, kind)), OTHER_KIND_ICON)


def _shown_columns(properties: Any) -> list[Column]:
    return [column for column in COLUMNS if getattr(properties, column.show_property)]


def _unit_pixels(context: Any) -> float:
    # Blender's widget unit: 18 pixels at a scale of 1, and a pixel's line on each side.
    system = context.preferences.system
    return round(18 * system.ui_scale) + 2 * system.pixel_size


def _name_column_factor(context: Any, properties: Any) -> float:
    """The name column's share of a row: all but the shown columns' widths, or its least share if more."""
    shown = _shown_columns(properties)
    columns_units = sum(getattr(properties, column.units_property) for column in shown)
    return _split_factor_leaving(context, columns_units, NAME_COLUMN_FACTOR_BY_COLUMN_COUNT[len(shown)])


def _split_factor_leaving(context: Any, right_units: float, least_factor: float) -> float:
    """A split's factor that leaves its right side right_units wide, or least_factor where the region is too narrow.

    A split takes a share of its width, not a width, so the share is worked out from the region's.
    """
    region = getattr(context, "region", None)
    if region is None or right_units == 0:
        return least_factor
    unit_pixels = _unit_pixels(context)
    row_pixels = region.width - REGION_MARGIN_UNITS * unit_pixels
    return max(least_factor, 1 - right_units * unit_pixels / row_pixels) if row_pixels > 0 else least_factor


def _column_cells(layout: Any, properties: Any, shown: list[Column]) -> list[Any]:
    """One cell per shown column, aligned as it says, sharing a layout's width in proportion to the columns' widths."""
    cells = []
    remaining_units = sum(getattr(properties, column.units_property) for column in shown)
    for column in shown[:-1]:
        units = getattr(properties, column.units_property)
        split = layout.split(factor=units / remaining_units, align=True)  # this column, then the rest
        cells.append(split.row(align=True))
        layout = split.row(align=True)
        remaining_units -= units
    if shown:
        cells.append(layout.row(align=True))
    for cell, column in zip(cells, shown, strict=True):
        cell.alignment = column.alignment
    return cells


def _fixed_width(layout: Any, width_units: float) -> Any:
    cell = layout.row(align=True)
    cell.ui_units_x = width_units
    return cell


def _draw_guide_level(layout: Any) -> None:
    """One indent level, with the vertical line that runs down from its open parent's chevron.

    Every ancestor of a visible row is expanded, so each level of a row's indent holds a line, and the lines join
    from row to row into one under each open chevron. A layout can't draw a vertical line, so it is a disabled button
    squeezed to a hairline: disabled, it draws faint, and a click on it selects the row.
    """
    level = _fixed_width(layout, LEVEL_UNITS)
    before_line = (CHEVRON_UNITS - GUIDE_LINE_UNITS) / 2
    _fixed_width(level, before_line).label(text="")
    line = _fixed_width(level, GUIDE_LINE_UNITS)
    line.enabled = False
    line.operator(widget_operators.SceneGraphGuideLine.bl_idname, text="", icon="BLANK1")
    # The parts have fixed widths that fill the level, so the line keeps its place whatever the row's alignment.
    _fixed_width(level, LEVEL_UNITS - before_line - GUIDE_LINE_UNITS).label(text="")


def _instance_badge_color() -> tuple[float, float, float]:
    """The instance badge's collection color."""
    theme_colors = badge_icons.drawn_theme_colors()
    return theme_colors.collection_colors[badge_icons.BADGE_LOOKS[prim_descriptions.Badge.INSTANCE][0]]


def _instancing_color(text_weight: float) -> tuple[float, float, float]:
    """The instance badge's color mixed toward the list's text color, so it reads on the rows."""
    badge_color = _instance_badge_color()
    text_color = badge_icons.drawn_theme_colors().list_text_color
    red, green, blue = ((1 - text_weight) * badge_color[i] + text_weight * text_color[i] for i in range(3))
    return red, green, blue


def _relative_luminance(color: tuple[float, float, float]) -> float:
    """A display color's relative luminance, as WCAG's contrast ratio weighs it."""

    def linear(channel: float) -> float:
        return channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4

    red, green, blue = color
    return 0.2126 * linear(red) + 0.7152 * linear(green) + 0.0722 * linear(blue)


def _saturated_at_luminance(color: tuple[float, float, float], luminance: float) -> tuple[float, float, float]:
    """The color's hue and saturation, made as light as the luminance, or mixed toward white where full value isn't."""
    hue, saturation, _ = colorsys.rgb_to_hsv(*color)
    brightest = colorsys.hsv_to_rgb(hue, saturation, 1.0)

    def shade(amount: float) -> tuple[float, float, float]:  # 0 to 1: black to the brightest, then on to white
        if amount <= 1.0:
            return colorsys.hsv_to_rgb(hue, saturation, amount)
        white_weight = amount - 1.0
        red, green, blue = ((1 - white_weight) * channel + white_weight for channel in brightest)
        return red, green, blue

    low, high = 0.0, 2.0
    for _ in range(LUMINANCE_SEARCH_STEPS):  # luminance rises with the amount, so bisect for it
        middle = (low + high) / 2
        if _relative_luminance(shade(middle)) < luminance:
            low = middle
        else:
            high = middle
    return shade((low + high) / 2)


def _instance_color() -> tuple[float, float, float]:
    """The color an instance's row marks it in: as light as the text mix, as saturated as the badge."""
    mixed_color = _instancing_color(INSTANCE_TEXT_WEIGHT)
    return _saturated_at_luminance(_instance_badge_color(), _relative_luminance(mixed_color))


def _instance_proxy_color() -> tuple[float, float, float]:
    """The color an instance proxy's row marks it in: fainter, for what it shares from its prototype."""
    return _instancing_color(INSTANCE_PROXY_TEXT_WEIGHT)


def _find_row_instance(details: Any) -> Sdf.Path | None:
    """Find the instance a row marks: its own prim, if that's an instance, or the one above an instance proxy."""
    return details.path if details.is_instance else details.instance_path


def _draw_dashed_guide_level(layout: Any, color: tuple[float, float, float]) -> None:
    # A label, so a click on it selects its row, as on the plain line, whose disabled button does nothing.
    icon_value = guide_line_icons.dashed_line_icon_id(color)
    _fixed_width(layout, LEVEL_UNITS).label(text="", icon_value=icon_value)


def _draw_row_icon(layout: Any, details: Any) -> None:
    """The row's icon, an instance's in its color and a proxy's fainter, where it's one of Blender's."""
    icon = _row_icon(details)
    if details.is_instance or details.is_instance_proxy:
        color = _instance_proxy_color() if details.is_instance_proxy else _instance_color()
        icon_value = tinted_icons.icon_id(icon, color)
        if icon_value is not None:
            layout.label(text="", icon_value=icon_value)
            return
    layout.label(text="", icon=icon)


class SceneGraphList(bpy.types.UIList):
    """Draws a view's rows as an indented tree with disclosure triangles, in the header's columns.

    Its data is the view's properties, and its list ID is the view's name, so each view keeps its own scroll.
    """

    bl_idname = "PROSCENIUM_UL_scene_graph"

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
        _drawn_row_counts[data.name] = _drawn_row_counts.get(data.name, 0) + 1
        view = widget_views.find_view(data.name)
        tree = view.prim_tree_view.live_tree() if view is not None else None
        if tree is None or index is None or index >= len(tree.rows):
            return
        tree_row = tree.rows[index]
        details = tree.details(tree_row)  # read once, when the row first comes on screen
        split = layout.split(factor=_name_column_factor(context, data))
        row = split.row(align=True)
        # The levels from an instance's own down hold its proxies' lines, dashed: the instance's own in its color,
        # and those under the proxies below it fainter, as their icons. An instance's own row has none.
        instance_path = _find_row_instance(details)
        instance_depth = tree_row.depth - (
            details.path.pathElementCount - instance_path.pathElementCount if instance_path else 0
        )
        for level_depth in range(tree_row.depth):
            if instance_path is not None and level_depth >= instance_depth:
                color = _instance_color() if level_depth == instance_depth else _instance_proxy_color()
                _draw_dashed_guide_level(row, color)
            else:
                _draw_guide_level(row)
        content = row.row(align=True)  # dimmed apart from the guide lines, so each line has one look down its length
        # Inactive prims and rows that only hold search matches draw greyed.
        content.active = details.is_active and tree.is_match(tree_row)
        chevron = _fixed_width(content, CHEVRON_UNITS)
        if details.has_children:
            disclosure = EXPANDED_ICON if tree.is_expanded(tree_row) else COLLAPSED_ICON
            # Inside an instance, the chevron is a proxy's, in the color of its icon and the lines beside it.
            tinted = tinted_icons.icon_id(disclosure, _instance_proxy_color()) if details.is_instance_proxy else None
            toggle_idname = widget_operators.SceneGraphToggleRow.bl_idname
            if tinted is None:
                toggle = chevron.operator(toggle_idname, text="", icon=disclosure, emboss=False)
            else:
                toggle = chevron.operator(toggle_idname, text="", icon_value=tinted, emboss=False)
            toggle.view_name = data.name
            toggle.row_index = index
        else:
            chevron.label(text="", icon="BLANK1")
        # The icon in a cell of its own, and a separator before the name, set a narrower gap than a label's icon has.
        named = content.row(align=True)
        named.alert = details.is_orphaned_over  # red: nothing defines it, as a typo in an over's path leaves it
        icon = _fixed_width(named, ROW_ICON_UNITS)
        icon.alert = details.is_invalid_model  # the kind's icon red, as the kind column's text is
        _draw_row_icon(icon, details)
        named.separator(factor=NAME_GAP_FACTOR)
        # The name fills what its badges leave (NAME_CELL_UNITS). Left-aligned, so the badges hugged its text, a name
        # too long for its column would squeeze every cell in the row, indent and icon too.
        name_and_badges = named.row(align=True)
        name_cell = _fixed_width(name_and_badges, NAME_CELL_UNITS)
        name_cell.label(text=prim_descriptions.row_name(details, data.shown_name == "DISPLAY_NAME"))
        # Labels, so a click on one selects the row and the row's tooltip covers them; each icon draws its piece of
        # the block they sit on, so side by side they make one. The instance badge, which marks no arc, stands on
        # its own, and the arcs' badges share a block after a gap.
        row_badges = prim_descriptions.row_badges(details)
        arc_badges = [badge for badge in row_badges if badge is not prim_descriptions.Badge.INSTANCE]
        instance_badges = [badge for badge in row_badges if badge is prim_descriptions.Badge.INSTANCE]
        # Each cell sits in the name's row itself: the row is short of width, so it keeps each cell narrower than a
        # unit at its width, where a row of the cells, wider than a unit, would shrink with the name.
        for block_index, block in enumerate(block for block in (instance_badges, arc_badges) if block):
            if block_index:
                _fixed_width(name_and_badges, BADGE_GAP_UNITS).label(text="")
            for badge_index, badge in enumerate(block):
                place = badge_icons.BadgePlace.at(badge_index, len(block))
                is_greyed = not prim_descriptions.is_badge_in_effect(details, badge)
                icon_value = badge_icons.icon_id(badge, place, is_greyed)
                _fixed_width(name_and_badges, BADGE_UNITS).label(text="", icon_value=icon_value)
        column_texts = {
            CHILDREN_COLUMN: str(details.child_count) if details.has_children else "",  # a leaf's blank, as its chevron
            KIND_COLUMN: details.model_kind,
            TYPE_COLUMN: details.type_name or "-",
        }
        shown = _shown_columns(data)
        for cell, column in zip(_column_cells(split.row(align=True), data, shown), shown, strict=True):
            cell.alert = column == KIND_COLUMN and details.is_invalid_model
            cell.label(text=column_texts[column])

    @override
    def draw_filter(self, context: bpy.types.Context | None, layout: Any) -> None:
        # Nothing: the list's own name filter would hide rows without keeping their ancestors, and the search,
        # drawn below the list, does that. A text field drawn here lost its arrow keys to the key watcher.
        return


class SceneGraphSettings(bpy.types.Panel):
    """A view's settings, in a popover from the gear at its status line's end; drawn nowhere else."""

    bl_idname = "PROSCENIUM_PT_scene_graph_settings"
    bl_label = "Scene Graph Settings"
    bl_space_type = "TOPBAR"  # a header panel shows only where a popover opens it
    bl_region_type = "HEADER"

    @override
    def draw(self, context: bpy.types.Context | None) -> None:
        properties = getattr(context, SETTINGS_CONTEXT_MEMBER, None)
        layout = self.layout
        if properties is None or layout is None:
            return
        layout.label(text="Columns")
        for column in COLUMNS:
            row = layout.row()
            is_shown = getattr(properties, column.show_property)
            # The eye, open or closed, as the Outliner's; then the title, and the width, dimmed while hidden.
            eye_and_title = row.row(align=True)
            eye_and_title.prop(
                properties, column.show_property, text="", icon="HIDE_OFF" if is_shown else "HIDE_ON", emboss=False
            )
            eye_and_title.label(text=column.title)
            width = row.row()
            width.active = is_shown
            width.prop(properties, column.units_property)


def _draw_search(layout: Any, context: Any, properties: Any) -> None:
    # The text field takes what the mode and toggles leave; in a row, every item would grow with the width.
    options_units = SEARCH_MODE_UNITS + 2 * SEARCH_TOGGLE_UNITS
    split = layout.split(factor=_split_factor_leaving(context, options_units, SEARCH_TEXT_LEAST_FACTOR), align=True)
    split.row(align=True).prop(properties, "search_text", text="", icon="VIEWZOOM", placeholder="Search prims")
    options = split.row(align=True)
    options.prop(properties, "search_mode", text="")
    # As wide as the icon-only toggle after it.
    _fixed_width(options, SEARCH_TOGGLE_UNITS).prop(properties, "search_case_sensitive", text="Aa", toggle=True)
    _fixed_width(options, SEARCH_TOGGLE_UNITS).prop(
        properties, "search_shown_rows_only", text="", icon="FILTER", toggle=True
    )


def _draw_header(layout: Any, context: Any, properties: Any, is_list_scrolling: bool) -> None:
    # A row above the list, split like the rows; the list's own padding offsets its columns by a few pixels. A
    # scrolling list's rows are narrower by its scrollbar, so the header leaves the scrollbar's width blank and splits
    # the rest as they split theirs.
    if is_list_scrolling:
        scrollbar_split = layout.split(factor=_split_factor_leaving(context, SCROLLBAR_UNITS, 0.0))
        layout = scrollbar_split.row()
        scrollbar_split.label(text="")
    split = layout.split(factor=_name_column_factor(context, properties))
    name_header = split.row()
    name_header.alignment = "LEFT"
    # A menu with an arrow after its text, so the header reads as clickable; an unembossed button shows no hover.
    # Under PULLDOWN_MENU the menu draws no arrow of its own, which would be dimmer than the text, so the arrow is a
    # character of the text, in its color.
    name_header.emboss = "PULLDOWN_MENU"
    title = "Display Name" if properties.shown_name == "DISPLAY_NAME" else "Prim"
    name_header.prop_menu_enum(properties, "shown_name", text=f"    {title} ⌄")
    shown = _shown_columns(properties)  # chosen in the settings popover
    for cell, column in zip(_column_cells(split.row(align=True), properties, shown), shown, strict=True):
        if column.header_icon:
            cell.label(text="", icon=column.header_icon)
        else:
            cell.label(text=column.title)


def draw_tree(layout: Any, context: Any, view_name: str, list_rows: int = LIST_ROWS) -> None:
    """Draw a view's status, header, tree, and search box below it, and watch its window's keys."""
    view = widget_views.scene_graph_view(view_name)
    widget_keys.ensure_watcher(context.window)
    properties = widget_properties.view_properties(context.window_manager, view_name)
    if properties is None:
        layout.label(text="Loading")  # a file just loaded; its load handler makes the properties
        return
    prim_tree_view = view.prim_tree_view
    tree = prim_tree_view.live_tree()
    if tree is None:
        layout.label(text="No stage" if prim_tree_view.tree is None else "Stage closed")
        return
    status = prim_tree_view.search_status
    status_row = layout.row()
    status_row.label(
        text=status.text or f"{len(tree.rows):,} visible rows", icon="ERROR" if status.is_error else "NONE"
    )
    # The view's settings at the status line's end; the popover reads the view's properties from the context set here.
    settings = status_row.row()
    settings.alignment = "RIGHT"
    settings.emboss = "NONE"
    settings.context_pointer_set(SETTINGS_CONTEXT_MEMBER, properties)
    settings.popover(SceneGraphSettings.bl_idname, text="", icon="PREFERENCES")
    header = layout.column()  # filled once the list has drawn, when its drawn rows tell whether it scrolls
    badge_icons.redraw_icons_if_theme_changed()  # once per view drawn, not per row
    _drawn_row_counts[view_name] = 0
    layout.template_list(
        SceneGraphList.bl_idname,
        view_name,
        properties,
        "rows",
        properties,
        "active_row_index",
        item_dyntip_propname="tooltip",
        rows=list_rows,
        maxrows=list_rows * 3,
    )
    _draw_header(header, context, properties, _drawn_row_counts.pop(view_name, 0) < len(tree.rows))
    _draw_search(layout, context, properties)


def draw_details(layout: Any, view_name: str) -> None:
    """Draw what a view's selected prim is."""
    prim_tree_view = widget_views.scene_graph_view(view_name).prim_tree_view
    tree = prim_tree_view.live_tree()
    path = prim_tree_view.selected_path
    details = tree.details_at(path) if tree is not None and path else None
    prim_details = tree.prim_details(path) if tree is not None and path else None
    column = layout.column(align=True)
    if details is None or prim_details is None:
        column.label(text="Select a row")
        return
    for line in prim_descriptions.details_lines(details, prim_details):
        column.label(text=line)


# In registration order.
CLASSES = (SceneGraphList, SceneGraphSettings)
