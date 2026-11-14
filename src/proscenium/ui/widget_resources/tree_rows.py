"""What the rows of a widget's tree draw alike: indent levels with guide lines, chevrons, the row's icon, and badges.

A tree's row is an indent, a level per ancestor, each holding the guide line that runs down from its parent's
chevron; the row's own chevron, or a blank of its width; its icon in a cell of its own; its name, filling what its
badges leave; and its badges, side by side on blocks. Each widget draws its own chevrons, icons, and names from these
widths; the guide line is a button of the operator here, `TreeGuideLine`, which `display_registration` registers.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, override

import bpy

from ..columned_list.column_layout import fixed_width
from . import badge_icons

if TYPE_CHECKING:
    from collections.abc import Sequence

    from bpy.stub_internal.rna_enums import IconItems, OperatorReturnItems  # stub-only aliases

# Widths in UI units. A level holds its parent's guide line, under the center of that parent's chevron.
LEVEL_UNITS = 0.6
CHEVRON_UNITS = 0.6  # narrower than an icon button's 1.0, which leaves wide margins around the chevron
GUIDE_LINE_UNITS = 0.05
ROW_ICON_UNITS = 0.8  # the cell of the row's icon
NAME_GAP_FACTOR = 1.0  # the separator between the icon and the name
BADGE_UNITS = 0.8  # each badge's cell, after the name
BADGE_GAP_UNITS = 0.2  # between two blocks of badges
# The name cell's natural width, wider than any row, so each row is too narrow for what it holds. A row with width to
# spare grows every item in proportion to its natural width, which differs from row to row, so the guide lines would
# drift apart; a row short of width keeps each item narrower than a unit at its width and shrinks the rest, here only
# the name.
NAME_CELL_UNITS = 1000.0
# The disclosure triangle's icons, collapsed and expanded: chevrons, as the Outliner's.
COLLAPSED_ICON: IconItems = "RIGHTARROW"
EXPANDED_ICON: IconItems = "DOWNARROW_HLT"

# A badge: how it looks, and whether what it marks is in effect, which greys it out when it isn't.
Badge = tuple[badge_icons.BadgeLook, bool]


class TreeGuideLine(bpy.types.Operator):
    """A tree guide line: drawn as a disabled button, which a layout can squeeze to a hairline, so it never runs."""

    bl_idname = "proscenium.tree_guide_line"
    bl_label = ""
    bl_options = {"INTERNAL"}

    @override
    @classmethod
    def description(cls, context: Any, properties: Any) -> str:
        return ""  # a line has no tooltip of its own

    @override
    def execute(self, context: Any) -> set[OperatorReturnItems]:
        return {"CANCELLED"}


def draw_guide_level(layout: bpy.types.UILayout) -> None:
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
    line.operator(TreeGuideLine.bl_idname, text="", icon="BLANK1")
    # The parts have fixed widths that fill the level, so the line keeps its place whatever the row's alignment.
    fixed_width(level, LEVEL_UNITS - before_line - GUIDE_LINE_UNITS).label(text="")


def draw_badge_blocks(layout: bpy.types.UILayout, blocks: Sequence[Sequence[Badge]]) -> None:
    """Draw badges after a row's name: each block's side by side on one block, the blocks a gap apart.

    Labels, so a click on one selects the row and the row's tooltip covers them; each icon draws its piece of the
    block it sits on, so side by side they make one. Each cell sits in the name's row itself: the row is short of
    width (NAME_CELL_UNITS), so it keeps each cell narrower than a unit at its width, where a row of the cells, wider
    than a unit, would shrink with the name. An empty block draws nothing.
    """
    for block_index, block in enumerate(block for block in blocks if block):
        if block_index:
            fixed_width(layout, BADGE_GAP_UNITS).label(text="")
        for badge_index, (look, is_in_effect) in enumerate(block):
            place = badge_icons.BadgePlace.at(badge_index, len(block))
            icon_value = badge_icons.icon_id(look, place, is_greyed=not is_in_effect)
            fixed_width(layout, BADGE_UNITS).label(text="", icon_value=icon_value)


# In registration order.
CLASSES = (TreeGuideLine,)
