"""The scene graph list's columns: one module per column, the layout they share, and the columns after the name."""

from .. import badge_icons, widget_colors
from .children_column import CHILDREN_COLUMN
from .copy_path_column import COPY_PATH_COLUMN
from .kind_column import KIND_COLUMN
from .type_column import TYPE_COLUMN

# The columns after the name, in order.
COLUMNS = (CHILDREN_COLUMN, KIND_COLUMN, TYPE_COLUMN, COPY_PATH_COLUMN)


def redraw_icons_if_theme_changed() -> None:
    """Read the theme's colors, and redraw the rows' badge icons if they were drawn in others.

    Called once per view drawn, before its rows, not per row.
    """
    widget_colors.read_theme_colors()
    badge_icons.redraw_icons_if_theme_changed()
