"""What widgets register and draw with: the theme's colors, tinted and badge icons, tree rows, keys, the clipboard.

A widget's display registers it through `display_registration` with its own registration. It exports its modules.
"""

from . import (
    badge_icons,
    clipboard_operators,
    display_registration,
    keyframe_icons,
    list_keys,
    theme_colors,
    tinted_icons,
    tree_rows,
)

__all__ = [
    "badge_icons",
    "clipboard_operators",
    "display_registration",
    "keyframe_icons",
    "list_keys",
    "theme_colors",
    "tinted_icons",
    "tree_rows",
]
