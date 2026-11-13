"""What widgets register and draw with: the theme's colors, tinted and badge icons, and the clipboard operator.

A widget's display registers it through `display_registration` with its own registration. It exports its modules.
"""

from . import badge_icons, clipboard_operators, display_registration, theme_colors, tinted_icons

__all__ = ["badge_icons", "clipboard_operators", "display_registration", "theme_colors", "tinted_icons"]
